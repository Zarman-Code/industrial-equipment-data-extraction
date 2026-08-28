 
from __future__ import annotations
 
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union
 
import fitz  # PyMuPDF
 
__all__ = ["extract_raw_toc", "process_and_save_pdf"]
 
 
def extract_raw_toc(pdf_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Extrait de manière exhaustive, déterministe et sans altération
    la table des matières interne (bookmarks/TOC) d'un document PDF.
 
    Args:
        pdf_path: Chemin vers le fichier PDF.
 
    Returns:
        Dictionnaire contenant les métadonnées du document et la liste RAW
        des sections, au format :
        {
            "document": {
                "filename": str,
                "total_pages": int,
                "toc_available": bool,
                "toc_entries_count": int
            },
            "sections": [
                {"index": int, "level": int, "title": str, "page": int},
                ...
            ]
        }
 
    Raises:
        FileNotFoundError: si le fichier PDF n'existe pas.
        PermissionError: si le fichier PDF est protégé/chiffré.
        RuntimeError: pour toute autre erreur de lecture PyMuPDF.
    """
    path = Path(pdf_path)
 
    # 1. Vérification de l'existence du fichier
    if not path.exists():
        raise FileNotFoundError(f"Le fichier PDF est introuvable : {path.resolve()}")
 
    # 2. Ouverture sécurisée avec PyMuPDF
    try:
        with fitz.open(str(path)) as doc:
            if doc.is_encrypted:
                raise PermissionError(
                    f"Le fichier '{path.name}' est protégé / chiffré par mot de passe."
                )
 
            total_pages = len(doc)
 
            # Extraction pure des bookmarks natifs du PDF
            # Format retourné par doc.get_toc(simple=True) : [[level, title, page], ...]
            raw_toc = doc.get_toc(simple=True)
 
            toc_entries_count = len(raw_toc)
            toc_available = toc_entries_count > 0
 
            # Construction de la liste des sections avec préservation stricte
            # de l'ordre et des valeurs
            sections = [
                {
                    "index": idx,
                    "level": int(entry[0]),
                    "title": str(entry[1]),
                    "page": int(entry[2]),
                }
                for idx, entry in enumerate(raw_toc)
            ]
 
            return {
                "filename": path.name,
                "total_pages": total_pages,
                "sections": sections,
            }
 
    except (FileNotFoundError, PermissionError):
        raise
    except Exception as e:
        raise RuntimeError(
            f"Erreur lors de la lecture du document '{path.name}' avec PyMuPDF : {e}"
        ) from e
 
 
def process_and_save_pdf(
    pdf_path: Union[str, Path],
    output_dir: Union[str, Path] = ".",
    custom_name: Optional[str] = None,
    suffix: str = "_sections_raw.json",
) -> Dict[str, Any]:
    """
    Extrait le TOC RAW d'un PDF (via extract_raw_toc), l'enregistre au
    format JSON (UTF-8) et affiche un résumé clair et lisible.
 
    Args:
        pdf_path: Chemin vers le fichier PDF source.
        output_dir: Dossier de sortie pour le fichier JSON (créé si absent).
        custom_name: Nom de base personnalisé pour le fichier de sortie
            (par défaut : le nom du fichier PDF sans extension).
        suffix: Suffixe ajouté au nom de base pour former le nom du fichier
            JSON de sortie.
 
    Returns:
        Le dictionnaire retourné par extract_raw_toc().
    """
    pdf_p = Path(pdf_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
 
    # 1. Extraction RAW
    data = extract_raw_toc(pdf_p)
 
    # 2. Détermination du chemin de sortie : <STEM>_sections_raw.json
    stem = custom_name if custom_name else pdf_p.stem
    output_filename = f"{stem}{suffix}"
    output_path = out_dir / output_filename
 
    # 3. Écriture du fichier JSON (UTF-8, indent=2, accents préservés)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
 
    return data
 