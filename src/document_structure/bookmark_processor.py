"""
bookmark_processor.py

Nettoyage et restructuration d'un bookmark PDF natif (sortie de
`extract_raw_toc()`, voir src/document_structure/extract_raw_pdf_toc.py)
avant sa conversion en `TOCEntry`.

Toute la logique est reprise telle quelle des notebooks
`01_extract_raw_pdf_toc.ipynb` et `06_bookmark_llm1_pipeline.ipynb` --
regroupee ici dans une seule classe, sans aucun changement de
comportement :

- `is_numeric_only_title` / `remove_duplicate_numeric_titles` :
  suppression des faux titres qui ne sont qu'un numero de section
  (doublons d'un titre deja complet a un autre niveau).
- `is_english_only_title` : detection des sous-sections uniquement en
  anglais dans un document bilingue ENG/FRE (les titres explicitement
  bilingues sont conserves).
- `extract_section_number` / `clean_title` : extraction du numero de
  section et nettoyage du titre (marqueurs ENG/FRE retires en fin de
  titre).
- `build_clean_structure` : reconstruit la hierarchie Level 1 ->
  Level 2 avec les plages de pages de chaque sous-section, en excluant
  les sous-sections uniquement anglaises et leurs pages.
- `clean_structure_to_bookmark_sections` : aplatit cette hierarchie
  vers la meme forme plate (index/level/title/page) que
  `raw_toc["sections"]`, pour que la conversion en `TOCEntry` en aval
  n'ait rien a changer.
- `bookmark_sections_to_entries` : convertit cette forme plate en
  `TOCEntry` (meme type que `TOCDetector`, src/document_structure/models.py).
- `region_entries_to_payload` : construit le payload envoye au LLM #1
  (`classify_sections`, src/llm/classifier.py) a partir d'une liste de
  `TOCEntry`.
"""

import re
from typing import Any, Dict, List, Optional

from src.document_structure.models import TOCEntry


class BookmarkProcessor:
    """Nettoie et restructure la sortie de `extract_raw_toc()` (bookmark
    natif d'un PDF) avant conversion en `TOCEntry`.

    Usage :

        processor = BookmarkProcessor()

        # etape par etape (comme dans le notebook) :
        clean_data = processor.build_clean_structure(raw_toc)
        clean_sections = processor.clean_structure_to_bookmark_sections(clean_data)

        # ou en un seul appel :
        clean_sections, clean_data = processor.process(raw_toc)
    """

    # ============================================================
    # ETAPE 1 : suppression des faux titres / doublons numeriques
    # (repris de 01_extract_raw_pdf_toc.ipynb, non modifie)
    # ============================================================

    @staticmethod
    def is_numeric_only_title(title: str) -> bool:
        """Detecte les titres qui ne contiennent qu'un numero de section
        ('1.01' -> True, '1.01 Contact details' -> False)."""
        title = title.strip()
        return bool(re.fullmatch(r"\d+(?:\.\d+)+", title))

    @classmethod
    def remove_duplicate_numeric_titles(cls, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Supprime les entrees de niveau >= 3 dont le titre n'est qu'un
        numero et qui partagent la page d'un voisin immediat (doublon
        d'un titre deja complet a un niveau different)."""
        cleaned = []
        for i, section in enumerate(sections):
            title = section["title"]
            page = section["page"]
            level = section["level"]

            if level >= 3 and cls.is_numeric_only_title(title):
                previous_same_page = i > 0 and sections[i - 1]["page"] == page
                next_same_page = i < len(sections) - 1 and sections[i + 1]["page"] == page
                if previous_same_page or next_same_page:
                    continue

            cleaned.append(section)
        return cleaned

    # ============================================================
    # ETAPE 2 : identification des sections anglaises
    # (repris de 01_extract_raw_pdf_toc.ipynb, non modifie)
    # ============================================================

    @staticmethod
    def is_english_only_title(title: str) -> bool:
        """True si le titre est la version anglaise seule d'une section
        bilingue ('... - ENG'). Les titres explicitement bilingues
        ('ENG & FRE', 'FRE & ENG', 'FR & ENG') sont conserves."""
        normalized = " ".join(title.upper().split())

        if "ENG & FRE" in normalized:
            return False
        if "FRE & ENG" in normalized:
            return False
        if "FR & ENG" in normalized:
            return False

        if re.search(r"(?:^|\s|[-–])ENG\s*$", normalized):
            return True

        return False

    # ============================================================
    # ETAPE 3 : construction de la hierarchie Level 1 -> Level 2
    # (repris de 01_extract_raw_pdf_toc.ipynb, non modifie)
    # ============================================================

    @staticmethod
    def extract_section_number(title: str) -> Optional[str]:
        """Extrait le numero au debut du titre.

        Formes reconnues :
            '3.02 Compressor data sheet' -> '3.02'
            'Section 1 Technical data'   -> '1'
            'section 1.2'                -> '1.2'

        Retourne None si aucun numero n'est trouve.
        """
        title = title.strip()

        match = re.match(r"^\s*(\d+(?:\.\d+)*)", title)
        if match:
            return match.group(1)

        match = re.match(r"^\s*section\s+(\d+(?:\.\d+)*)", title, flags=re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def clean_title(title: str) -> str:
        """Nettoie le titre : espaces normalises, marqueurs ENG/FRE
        retires en fin de titre."""
        title = " ".join(title.split())
        title = re.sub(r"\s+(?:ENG\s*&\s*FRE|FRE\s*&\s*ENG)\s*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*[-–]?\s*(?:ENG|FRE|FR)\s*$", "", title, flags=re.IGNORECASE)
        return title.strip()

    def build_clean_structure(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Nettoie et restructure la sortie de extract_raw_toc() : retire
        les doublons numeriques, exclut les sous-sections Level 2
        uniquement anglaises et leurs pages, reconstruit la hierarchie
        Level 1 -> Level 2 avec plages de pages."""

        # 1. Suppression des faux titres numeriques
        sections = self.remove_duplicate_numeric_titles(raw_data["sections"])

        # 2. On travaille avec les sections LEVEL 1 / LEVEL 2 : ce sont
        #    elles qui definissent les frontieres.
        major_sections = [s for s in sections if s["level"] <= 2]

        # 3. Determiner les frontieres des LEVEL 2
        level2_boundaries = []
        for i, section in enumerate(major_sections):
            if section["level"] != 2:
                continue

            start_page = section["page"]
            next_page = None

            for next_section in major_sections[i + 1:]:
                if next_section["level"] in (1, 2):
                    if next_section["page"] != -1:
                        next_page = next_section["page"]
                    break

            level2_boundaries.append({
                "section": section,
                "start": start_page,
                "end": (
                    next_page - 1
                    if next_page is not None
                    else raw_data["total_pages"]
                ),
            })

        # 4. Construire la hierarchie Level 1 -> Level 2
        result = []
        current_level1 = None
        section_counter = 1

        for section in sections:
            level = section["level"]

            if level == 1:
                current_level1 = {
                    "id": f"S{section_counter:03d}",
                    "number": self.extract_section_number(section["title"]),
                    "title": self.clean_title(section["title"]),
                    "level": 1,
                    "page": [],
                    "subsections": [],
                }
                section_counter += 1
                result.append(current_level1)

            elif level == 2:
                if self.is_english_only_title(section["title"]):
                    continue
                if current_level1 is None:
                    continue

                boundary = None
                for b in level2_boundaries:
                    if b["section"]["index"] == section["index"]:
                        boundary = b
                        break
                if boundary is None:
                    continue

                start = boundary["start"]
                end = boundary["end"]

                if start == -1:
                    pages = []
                else:
                    pages = list(range(start, min(end, raw_data["total_pages"]) + 1))

                current_level2 = {
                    "id": f"S{section_counter:03d}",
                    "number": self.extract_section_number(section["title"]),
                    "title": self.clean_title(section["title"]),
                    "level": 2,
                    "page": pages,
                }
                section_counter += 1
                current_level1["subsections"].append(current_level2)

        # 5. Supprimer les pages correspondant aux sections ENG exclues
        english_ranges = []
        for b in level2_boundaries:
            if self.is_english_only_title(b["section"]["title"]):
                start = b["start"]
                end = b["end"]
                if start != -1:
                    english_ranges.append((start, end))

        for level1 in result:
            for level2 in level1["subsections"]:
                cleaned_pages = []
                for page in level2["page"]:
                    is_english = any(start <= page <= end for start, end in english_ranges)
                    if not is_english:
                        cleaned_pages.append(page)
                level2["page"] = cleaned_pages

            all_pages = []
            for level2 in level1["subsections"]:
                all_pages.extend(level2["page"])
            level1["page"] = sorted(set(all_pages))

        return {"document": raw_data["total_pages"], "sections": result}

    @staticmethod
    def clean_structure_to_bookmark_sections(clean_data: dict) -> List[Dict[str, Any]]:
        """Aplati la structure hierarchique Level1/Level2 renvoyee par
        build_clean_structure() vers la meme forme que
        raw_toc["sections"] (index/level/title/page unique), pour que
        bookmark_sections_to_entries() n'ait rien a changer.

        Le premier element de la liste de pages de chaque sous-section
        est pris comme page unique de reference (meme convention que le
        bookmark natif, qui n'a qu'une page par entree).
        """
        flat: List[Dict[str, Any]] = []
        idx = 0
        for level1 in clean_data["sections"]:
            page1 = level1["page"][0] if level1["page"] else -1
            flat.append({"index": idx, "level": 1, "title": level1["title"], "page": page1})
            idx += 1
            for level2 in level1["subsections"]:
                page2 = level2["page"][0] if level2["page"] else -1
                flat.append({"index": idx, "level": 2, "title": level2["title"], "page": page2})
                idx += 1
        return flat

    # ============================================================
    # ETAPE 4 : conversion en TOCEntry (repris de
    # 06_bookmark_llm1_pipeline.ipynb, section 3, non modifie)
    # ============================================================

    @classmethod
    def bookmark_sections_to_entries(cls, sections: list[dict]) -> list[TOCEntry]:
        return [
            TOCEntry(
                text=str(section["title"]).strip() or f"Section {section['index']}",
                section_number=cls.extract_section_number(section["title"]),  # pas de numero de section dans les bookmarks PDF
                level=int(section["level"]),
                printed_page_ref=str(section["page"]),
                reference_kind="page",
                source_page=int(section["page"]),
                confidence=0.95,  # meme convention que pipeline/toc_stage.py::_sections_from_bookmarks
            )
            for section in sections
        ]

    # ============================================================
    # ETAPE 5 : payload pour le LLM #1 (repris de
    # 06_bookmark_llm1_pipeline.ipynb, section 4, non modifie)
    # ============================================================

    @staticmethod
    def region_entries_to_payload(region_index: int, entries) -> list[dict]:
        payload = []
        for j, entry in enumerate(entries):
            payload.append({
                "section_id": f"toc{region_index}_e{j}",
                "title": entry.text,
                "section_number": entry.section_number,
                "page_start": entry.printed_page_ref,
                "level": entry.level,
                "confidence": round(entry.confidence, 3),
                "text": "",  # le contenu EST le bookmark -- pas d'extrait de corps de page
            })
        return payload

    # ============================================================
    # Raccourci : les deux etapes precedentes enchainees
    # ============================================================

    def process(self, raw_toc: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Enchaine build_clean_structure() puis
        clean_structure_to_bookmark_sections() -- equivalent a
        l'appel combine fait dans le notebook (section 2).

        Retourne (clean_sections, clean_data).
        """
        clean_data = self.build_clean_structure(raw_toc)
        clean_sections = self.clean_structure_to_bookmark_sections(clean_data)
        return clean_sections, clean_data



