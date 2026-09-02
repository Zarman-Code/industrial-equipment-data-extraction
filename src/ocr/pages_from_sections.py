"""
bookmark_page_resolution.py

Derniere etape du pipeline "bookmark PDF natif" : pour chaque section
retenue par le LLM #1 dont la page est inconnue (`page == -1`), retrouve
sa vraie page dans le PDF -- par lots de pages, avec un thread par page
DANS chaque lot (version parallelisee).

Regroupe dans une seule classe, `PageResolutionPipeline`, qui EXECUTE le
pipeline des sa construction (constructeur = point d'entree) : appelez-la
avec les entrees requises, le resultat (`resolved_df`) est deja pret en
sortie du constructeur.

    resolver = PageResolutionPipeline(
        pdf_path=PDF_PATH,
        raw_toc=raw_toc,
        clean_sections=clean_sections,
        overview=overview,
    )
    resolver.resolved_df   # deja calcule

Reprend telle quelle la logique du notebook (version parallelisee, un
thread par page d'un lot) :
    - `_configure_tesseract` / `ocr_top_of_page` : OCR du haut de page
      (pytesseract en priorite, repli sur `ocr_pipeline.ocr_cell` si
      pytesseract n'est pas installe) -- 3 tentatives de segmentation
      (PSM par defaut, 11, 6), correctif TESSDATA_PREFIX inclus.
    - `find_section_page` / `find_section_page_in_batches` : recherche
      par lots de pages (`BATCH_SIZE`), un thread par page DANS un lot,
      les lots eux-memes restant sequentiels (on s'arrete des qu'un lot
      trouve un match).
    - La boucle de resolution (cellule 17 du notebook) : parcourt les
      sections retenues (`overview["retenue"]`) dans l'ordre, resout
      celles de page inconnue, construit `resolved_df` (avec `page_end`).

Seules differences avec le notebook :
    - Toutes les ressources partagees entre threads (l'etat
      "pytesseract configure ?", l'annonce du repli PaddleOCR, l'objet
      `fitz.Document` du lot, le cache de `load_pdf_page_as_image`,
      l'appel a `ocr_pipeline.ocr_cell`) sont des ATTRIBUTS D'INSTANCE
      (`self._tesseract_ready`, `self._shared_resource_lock`, ...) au
      lieu de variables globales de module -- chaque instance de
      `PageResolutionPipeline` a son propre etat, ce qui evite qu'une
      execution n'en pollue une autre (deux notebooks/tests qui
      tourneraient en parallele, par exemple) tout en preservant EXACTEMENT
      le meme comportement de cache "configure une seule fois par run"
      a l'interieur d'une meme instance.
    - `display(...)` (specifique a Jupyter) est remplace par `print()`,
      actif seulement si `debug=True` (par defaut).
    - `extract_section_number` est appele via `BookmarkProcessor`
      (voir bookmark_processor.py) plutot que comme fonction independante.

ATTENTION -- deux optimisations discutees precedemment (le plafond de
`MAX_PAGES_TO_SCAN` et le passage a un seul mode PSM/une seule langue)
NE SONT PAS presentes dans le code que vous avez colle pour ce fichier :
`find_section_page_in_batches` balaie ici toute la plage jusqu'a
`search_end_page` SANS plafond, et `ocr_top_of_page` retente 3 modes
Tesseract (defaut, --psm 11, --psm 6) en "eng+fra". C'est repris a
l'identique de ce que vous avez fourni -- dites-le-moi si vous voulez
que je reintegre le plafond de pages et/ou le mode PSM unique par-dessus
la parallelisation.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
import pandas as pd

from src.document_structure.bookmark_processor import BookmarkProcessor
from src.ocr.config import TESSERACT_EXE
from src.ocr.preprocessing import close_cached_document, load_pdf_page_as_image

try:
    from src.ocr.ocr_pipeline import ocr_pipeline
except Exception as exc:
    ocr_pipeline = None
    print(f"[OCR (cellule) indisponible au chargement] {exc}")


class PageResolutionPipeline:
    """Resout la page reelle des sections retenues de page inconnue
    (`page == -1`), par lots de pages traites en parallele (un thread
    par page d'un lot).

    Le constructeur EXECUTE le pipeline (sauf `auto_run=False`) :
    `resolved_df` est deja disponible juste apres l'appel.

    Entrees requises :
        pdf_path        -- chemin du PDF (str ou Path)
        raw_toc         -- sortie de extract_raw_toc() (utilise pour
                           total_pages)
        clean_sections  -- sortie de BookmarkProcessor.process()
                           (index/level/title/page)
        overview        -- DataFrame avec une colonne "retenue"
                           (bool), alignee POSITIONNELLEMENT avec
                           clean_sections (overview.iloc[j] <->
                           clean_sections[j]) -- meme convention que
                           le notebook.

    Resultats exposes en attributs apres execution :
        resolved_rows   -- liste de dict (position/title/page_start/
                           source/page_end)
        resolved_df     -- meme chose en DataFrame
        non_trouvees    -- sous-ensemble de resolved_df sans page
                           resolue (page_start == None)
    """

    BATCH_SIZE = 5

    def __init__(
        self,
        pdf_path: str | Path,
        raw_toc: Dict[str, Any],
        clean_sections: List[Dict[str, Any]],
        overview: Optional[pd.DataFrame],
        processor: Optional[BookmarkProcessor] = None,
        batch_size: Optional[int] = None,
        top_ocr_ratio: float = 0.2,
        max_workers: Optional[int] = None,
        debug: bool = True,
        auto_run: bool = True,
    ):
        self.pdf_path = pdf_path
        self.raw_toc = raw_toc
        self.clean_sections = clean_sections
        self.overview = overview
        self.processor = processor or BookmarkProcessor()
        self.batch_size = batch_size or self.BATCH_SIZE
        self.top_ocr_ratio = top_ocr_ratio
        self.max_workers = max_workers
        self.debug = debug

        self.total_pages = raw_toc["total_pages"]

        # Etat OCR partage entre TOUS les threads lances par CETTE
        # instance (voir la note de classe plus haut sur pourquoi c'est
        # de l'etat d'instance plutot que des globales de module).
        self._tesseract_ready: Optional[bool] = None
        self._ocr_cell_repli_annonce = False
        self._shared_resource_lock = threading.Lock()

        self.resolved_rows: List[Dict[str, Any]] = []
        self.resolved_df: Optional[pd.DataFrame] = None
        self.non_trouvees: Optional[pd.DataFrame] = None

        if auto_run:
            self.run()

    # ------------------------------------------------------------------
    # OCR du haut de page (pytesseract, repli ocr_pipeline.ocr_cell)
    # ------------------------------------------------------------------

    def _configure_tesseract(self) -> bool:
        """Configure pytesseract avec le chemin Tesseract deja defini
        dans src/ocr/config.py (TESSERACT_EXE). Retourne False si
        pytesseract n'est pas installe -- dans ce cas on retombe sur
        ocr_pipeline.ocr_cell (voir ocr_top_of_page). Le resultat est
        mis en cache sur l'instance (teste une seule fois pour tout le
        run, pas a chaque page).

        Verrouillage en double controle ("double-checked locking") :
        plusieurs threads d'un meme lot peuvent appeler cette methode
        en meme temps au tout premier appel -- le verrou evite qu'ils
        ne fassent chacun leur propre detection/affichage en parallele.
        """
        if self._tesseract_ready is not None:
            return self._tesseract_ready

        with self._shared_resource_lock:
            if self._tesseract_ready is not None:  # un autre thread l'a fait entre-temps
                return self._tesseract_ready

            try:
                import pytesseract
            except ImportError as exc:
                print(f"[pytesseract indisponible] {exc} -- installez-le avec 'pip install pytesseract Pillow' pour un OCR plein-texte plus fiable. Repli sur ocr_pipeline.ocr_cell pour cette execution.")
                self._tesseract_ready = False
                return False

            tesseract_path = Path(TESSERACT_EXE)
            if tesseract_path.exists():
                pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)

            # TESSDATA_PREFIX (variable d'environnement Windows) est parfois
            # mal enregistree -- un piege classique de `setx` : une valeur
            # qui se termine par un antislash juste avant le guillemet
            # fermant fait entrer ce guillemet dans la valeur stockee (ex.
            # observe : "...\tessdata"/eng.traineddata" -- le '"' apres
            # 'tessdata' vient de la, pas de ce module). On la recalcule et
            # on l'ecrase ici, a partir du dossier "tessdata" a cote de
            # TESSERACT_EXE, pour ne plus dependre de la valeur
            # (potentiellement corrompue) deja presente dans
            # l'environnement Windows.
            tessdata_dir = tesseract_path.parent / "tessdata"
            if tessdata_dir.exists():
                os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
            else:
                print(f"[OCR] attention : dossier tessdata introuvable a {tessdata_dir} -- TESSDATA_PREFIX non corrige, l'OCR Tesseract risque d'echouer (fichiers eng.traineddata / fra.traineddata manquants ?).")

            print(f"[OCR] moteur utilise pour le haut de page : Tesseract (pytesseract) -- {tesseract_path} (TESSDATA_PREFIX={os.environ.get('TESSDATA_PREFIX', 'non defini')})")
            self._tesseract_ready = True
            return True

    def ocr_top_of_page(self, image, lang: str = "eng+fra"):
        """OCR d'une image deja recadree (le haut de page).

        Tente d'abord pytesseract/Tesseract (detection + reconnaissance
        plein-texte sur toute l'image). L'appel pytesseract lance un
        sous-processus Tesseract independant a chaque fois : plusieurs
        threads peuvent donc l'appeler en meme temps sans se gener, ce
        qui est exactement ce qu'on veut pour paralleliser un lot de
        pages.

        Si pytesseract n'est pas installe, retombe sur
        ocr_pipeline.ocr_cell() -- protege par `_shared_resource_lock`
        car un modele PaddleOCR partage n'est generalement pas garanti
        thread-safe pour de l'inference concurrente.

        Retourne (texte, source) ou (None, "indisponible") si aucun des
        deux moteurs n'est utilisable.
        """
        if self._configure_tesseract():
            import pytesseract
            import cv2
            from PIL import Image

            pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

            # Le mode de segmentation par defaut de Tesseract (PSM 3,
            # "page complete") suppose une mise en page de document
            # normale -- il echoue souvent a trouver quoi que ce soit sur
            # une page tres majoritairement blanche avec un seul petit
            # encadre de texte isole (ex. "SECTION 7.02"). On essaie donc
            # plusieurs modes de segmentation, du plus courant au plus
            # adapte a un texte "eparse" isole, et on garde le premier qui
            # rapporte quelque chose.
            psm_attempts = [
                ("", "pytesseract"),
                ("--psm 11", "pytesseract_psm11"),
                ("--psm 6", "pytesseract_psm6"),
            ]

            last_exc = None
            for config, source_label in psm_attempts:
                try:
                    text = pytesseract.image_to_string(pil_image, lang=lang, config=config) or ""
                except Exception:
                    try:
                        text = pytesseract.image_to_string(pil_image, config=config) or ""
                    except Exception as exc:
                        last_exc = exc
                        continue

                if text.strip():
                    return text, source_label

            if last_exc is not None:
                return "", "pytesseract_echec"

            return "", "pytesseract_vide"

        if ocr_pipeline is not None:
            with self._shared_resource_lock:
                if not self._ocr_cell_repli_annonce:
                    print("[OCR] moteur utilise pour le haut de page : ocr_pipeline.ocr_cell (PaddleOCR / TextRecognition) -- repli, pytesseract indisponible")
                    self._ocr_cell_repli_annonce = True
                h, w = image.shape[:2]
                result = ocr_pipeline.ocr_cell(image, [0, 0, w, h])
            return result.get("text", ""), "ocr_cell_repli"

        return None, "indisponible"

    @staticmethod
    def _normalize_for_search(text: str) -> str:
        return " ".join(text.upper().split())

    def _get_native_text(self, doc: "fitz.Document", page_num: int) -> str:
        """Lecture du texte natif d'une page, serialisee via le verrou
        partage (l'objet fitz.Document est partage entre tous les
        threads du lot)."""
        with self._shared_resource_lock:
            return doc[page_num - 1].get_text() or ""

    def _load_top_crop(self, pdf_path, page_num: int, top_ocr_ratio: float):
        """Charge l'image de la page et la recadre sur le haut. Le
        chargement (load_pdf_page_as_image) passe par un cache indexe
        par pdf_path, partage entre threads -- on le serialise via le
        verrou. Le recadrage lui-meme opere sur un tableau numpy local
        a ce thread : pas besoin de verrou une fois l'image obtenue."""
        with self._shared_resource_lock:
            image = load_pdf_page_as_image(pdf_path, page_number=page_num - 1)
        h, w = image.shape[:2]
        return image[0:max(1, int(h * top_ocr_ratio)), 0:w]

    def _process_single_page(self, doc, pdf_path, page_num, target_title, target_section, top_ocr_ratio) -> Dict[str, Any]:
        """Traite UNE page -- tourne dans un thread du pool, un thread
        par page du lot. Ne fait AUCUN print() directement : retourne
        un dict avec le resultat et les lignes de debug a afficher,
        pour que l'appelant les affiche dans l'ORDRE DES PAGES (l'ordre
        d'arrivee des threads est non deterministe).

        Retourne : {"page_num", "matched", "source", "debug_lines"}
        """
        def _matches(normalized_text: str) -> bool:
            if target_title and target_title in normalized_text:
                return True
            if target_section and target_section in normalized_text:
                return True
            return False

        debug_lines: List[str] = []

        try:
            native_text = self._get_native_text(doc, page_num)
        except Exception as exc:
            return {
                "page_num": page_num, "matched": False, "source": "erreur_texte_natif",
                "debug_lines": [f"    page {page_num} [erreur lecture texte natif] {exc}"],
            }

        native_stripped = native_text.strip()
        if native_stripped:
            is_match = _matches(self._normalize_for_search(native_text))
            apercu = " ".join(native_stripped.split())[:200]
            debug_lines.append(f"    page {page_num} [texte natif] \"{apercu}\" -> {'MATCH' if is_match else 'pas de match'}")
            return {"page_num": page_num, "matched": is_match, "source": "texte_natif", "debug_lines": debug_lines}

        debug_lines.append(f"    page {page_num} [texte natif] vide -> tentative OCR")

        try:
            top_crop = self._load_top_crop(pdf_path, page_num, top_ocr_ratio)
        except Exception as exc:
            debug_lines.append(f"    page {page_num} [chargement image echoue] {exc}")
            return {"page_num": page_num, "matched": False, "source": "erreur_chargement_image", "debug_lines": debug_lines}

        # >>> Partie couteuse, reellement executee en parallele entre threads <<<
        ocr_text, ocr_source = self.ocr_top_of_page(top_crop)

        if ocr_text is None:
            debug_lines.append(f"    page {page_num} [OCR indisponible] ni pytesseract ni ocr_pipeline disponibles")
            return {"page_num": page_num, "matched": False, "source": "indisponible", "debug_lines": debug_lines}

        ocr_stripped = ocr_text.strip()
        is_match = _matches(self._normalize_for_search(ocr_text))
        apercu = " ".join(ocr_stripped.split())[:200] if ocr_stripped else "(rien detecte)"
        debug_lines.append(f"    page {page_num} [OCR haut de page / {ocr_source}] \"{apercu}\" -> {'MATCH' if is_match else 'pas de match'}")

        source = f"ocr_haut_de_page_{ocr_source}"
        return {"page_num": page_num, "matched": is_match, "source": source, "debug_lines": debug_lines}

    # ------------------------------------------------------------------
    # Recherche de page (par lots, parallelisee a l'interieur d'un lot)
    # ------------------------------------------------------------------

    def find_section_page(
        self,
        pdf_path,
        title: str,
        search_start_page: int,
        search_end_page: int,
        top_ocr_ratio: float = 0.2,
        section_number: Optional[str] = None,
        debug: bool = True,
        max_workers: Optional[int] = None,
    ) -> tuple:
        """Cherche la page (1-indexee) ou apparait `title`, entre
        `search_start_page` et `search_end_page` inclus -- un thread
        par page de la plage (typiquement un lot de `batch_size`
        pages, voir find_section_page_in_batches).

        Cherche DEUX cibles sur chaque page : le titre complet, ET, si
        `section_number` est fourni, "SECTION <numero>" -- la page est
        retenue des que L'UNE des deux correspond.

        Consequence de la parallelisation : contrairement a une version
        sequentielle qui s'arrete des la premiere page correspondante
        (dans l'ordre des pages), TOUTES les pages de la plage sont
        traitees avant de conclure, puisqu'on ne sait pas a l'avance
        laquelle va correspondre. On garde ensuite la plus PETITE page
        parmi celles qui correspondent, pour un resultat identique a la
        version sequentielle.

        Retourne (page_1indexee, source) ou (None, "non_trouve") /
        (None, "titre_vide").
        """
        target_title = self._normalize_for_search(title)
        target_section = self._normalize_for_search(f"SECTION {section_number}") if section_number else ""

        if not target_title and not target_section:
            return None, "titre_vide"

        # Pre-chauffe la configuration Tesseract une fois depuis le
        # thread principal, avant de lancer le pool.
        self._configure_tesseract()

        with fitz.open(str(pdf_path)) as doc:
            total = len(doc)
            start = max(1, search_start_page)
            end = min(total, search_end_page)

            page_numbers = list(range(start, end + 1))
            if not page_numbers:
                return None, "non_trouve"

            workers = max_workers or len(page_numbers)
            results: Dict[int, Dict[str, Any]] = {}

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_page = {
                    executor.submit(
                        self._process_single_page, doc, pdf_path, page_num,
                        target_title, target_section, top_ocr_ratio,
                    ): page_num
                    for page_num in page_numbers
                }

                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        results[page_num] = future.result()
                    except Exception as exc:
                        results[page_num] = {
                            "page_num": page_num, "matched": False, "source": "erreur_thread",
                            "debug_lines": [f"    page {page_num} [erreur thread] {exc}"],
                        }

            if debug:
                for page_num in page_numbers:
                    for line in results[page_num].get("debug_lines") or []:
                        print(line)

            matched_pages = [p for p in page_numbers if results[p]["matched"]]
            if matched_pages:
                best_page = min(matched_pages)
                return best_page, results[best_page]["source"]

        return None, "non_trouve"

    def find_section_page_in_batches(
        self,
        pdf_path,
        title: str,
        search_start_page: int,
        search_end_page: int,
        batch_size: Optional[int] = None,
        top_ocr_ratio: float = 0.2,
        section_number: Optional[str] = None,
        debug: bool = True,
        max_workers: Optional[int] = None,
    ) -> tuple:
        """Cherche `title` (et "SECTION <section_number>" si fourni) par
        lots de `batch_size` pages (5 par defaut) a partir de
        search_start_page. Les LOTS restent sequentiels (on s'arrete
        des qu'un lot trouve un match) ; a l'INTERIEUR de chaque lot,
        les pages sont traitees en parallele (voir find_section_page)."""
        batch_size = batch_size or self.batch_size
        batch_start = search_start_page
        while batch_start <= search_end_page:
            batch_end = min(batch_start + batch_size - 1, search_end_page)
            print(f"    lot de pages {batch_start}-{batch_end} (traitement parallele, {batch_end - batch_start + 1} thread(s))...")

            found_page, source = self.find_section_page(
                pdf_path,
                title,
                batch_start,
                batch_end,
                top_ocr_ratio=top_ocr_ratio,
                section_number=section_number,
                debug=debug,
                max_workers=max_workers,
            )
            if found_page is not None:
                return found_page, source

            batch_start = batch_end + 1

        return None, "non_trouve"

    # ------------------------------------------------------------------
    # Boucle de resolution (reprend la cellule 17 du notebook)
    # ------------------------------------------------------------------

    def _resolve_all_sections(self) -> None:
        if self.overview is None or len(self.overview) == 0:
            print("Pas de vue d'ensemble disponible -- executez d'abord la section 4 (LLM #1).")
            return

        retained_positions = [
            j for j in range(len(self.clean_sections))
            if bool(self.overview.iloc[j]["retenue"])
        ]

        if not retained_positions:
            print("Aucune section retenue par le LLM #1 -- rien a resoudre.")
            return

        last_retained = retained_positions[-1]
        cursor_page = 1  # borne de debut de recherche, avance au fil des sections resolues

        for j in retained_positions:
            section = self.clean_sections[j]
            known_page = section["page"]

            if known_page != -1:
                self.resolved_rows.append({
                    "position": j,
                    "title": section["title"],
                    "page_start": known_page,
                    "source": "bookmark",
                })
                cursor_page = max(cursor_page, known_page)
                if j == last_retained:
                    break
                continue

            # Page inconnue -- borne de fin = prochaine section (retenue
            # ou non) de page connue, sinon fin de document.
            next_known_page = self.total_pages
            for k in range(j + 1, len(self.clean_sections)):
                if self.clean_sections[k]["page"] != -1:
                    next_known_page = self.clean_sections[k]["page"]
                    break

            section_number = self.processor.extract_section_number(section["title"])

            print(f"Recherche de la page pour '{section['title']}' par lots de {self.batch_size} pages, entre {cursor_page} et {next_known_page}...")
            found_page, source = self.find_section_page_in_batches(
                self.pdf_path, section["title"], cursor_page, next_known_page,
                section_number=section_number, max_workers=self.max_workers,
                debug=self.debug,
            )

            self.resolved_rows.append({
                "position": j,
                "title": section["title"],
                "page_start": found_page,
                "source": source,
            })

            if found_page is not None:
                cursor_page = found_page

            if j == last_retained:
                break

    def _finalize_page_ends(self) -> None:
        # page_end : chaque section resolue va jusqu'a la page qui
        # precede le debut de la section retenue suivante (ou fin de
        # document pour la derniere).
        for i, row in enumerate(self.resolved_rows):
            if row["page_start"] is None:
                row["page_end"] = None
                continue
            next_starts = [r["page_start"] for r in self.resolved_rows[i + 1:] if r["page_start"] is not None]
            row["page_end"] = (next_starts[0] - 1) if next_starts else self.total_pages

    def _build_resolved_df(self) -> pd.DataFrame:
        if self.resolved_rows:
            self.resolved_df = pd.DataFrame(self.resolved_rows)
            if self.debug:
                print(self.resolved_df)
            self.non_trouvees = self.resolved_df[self.resolved_df["page_start"].isna()]
            if len(self.non_trouvees) > 0:
                print(f"{len(self.non_trouvees)} section(s) retenue(s) sans page resolue -- a verifier manuellement :")
                if self.debug:
                    print(self.non_trouvees[["title"]])
        else:
            self.resolved_df = pd.DataFrame(columns=["position", "title", "page_start", "source", "page_end"])
            self.non_trouvees = pd.DataFrame(columns=["title"])

        return self.resolved_df

    # ------------------------------------------------------------------
    # Point d'entree -- appele automatiquement par __init__ (auto_run=True)
    # ------------------------------------------------------------------

    def run(self) -> pd.DataFrame:
        """Execute la resolution complete et retourne `resolved_df`.
        Toutes les pages necessaires du PDF ont ete traitees (OCR
        inclus) une fois cette methode terminee -- le document mis en
        cache par load_pdf_page_as_image est alors libere
        (`close_cached_document`), meme en cas d'erreur."""
        try:
            self._resolve_all_sections()
        finally:
            close_cached_document(self.pdf_path)

        self._finalize_page_ends()
        return self._build_resolved_df()
# resolved_df est un dataframe si tu veux tranformer en Json on peut faire :
# records = resolver.resolved_df.to_dict(orient="records")
# import json 
# json_str = json.dumps(records, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print("[OK] PageResolutionPipeline definie (version parallelisee : un thread par page du lot).")
