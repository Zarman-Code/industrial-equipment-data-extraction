from pathlib import Path
from typing import Union, Tuple

import cv2
import pymupdf as fitz
import numpy as np

from .config import DEFAULT_DPI, IMAGE_EXTENSIONS


# ------------------------------------------------------------------
# Cache de documents PDF ouverts.
#
# Avant : load_pdf_page_as_image() faisait fitz.open(pdf_path) puis
# doc.close() a CHAQUE appel -- donc a chaque page. Sur un traitement qui
# boucle page par page sur le meme PDF (nettoye/reduit ou non), ca relit
# et re-parse le fichier depuis le disque autant de fois qu'il y a de
# pages traitees.
#
# Maintenant : le fichier n'est ouvert qu'une seule fois par chemin ; les
# appels suivants sur le meme chemin reutilisent le meme fitz.Document
# deja en memoire. Le document reste ouvert tant qu'il n'est pas ferme
# explicitement via close_cached_document()/clear_document_cache() --
# a appeler une fois le traitement de ce PDF termine (fin de boucle),
# pour liberer le descripteur de fichier (important sous Windows,
# ou un fichier encore ouvert ne peut pas etre deplace/supprime).
# ------------------------------------------------------------------

_document_cache: dict[str, "fitz.Document"] = {}


def _get_cached_document(pdf_path: str) -> "fitz.Document":
    """Retourne le fitz.Document pour ce chemin, en l'ouvrant une seule
    fois puis en le reutilisant pour tous les appels suivants."""

    key = str(Path(pdf_path).resolve())

    doc = _document_cache.get(key)
    if doc is not None and not doc.is_closed:
        return doc

    doc = fitz.open(key)
    _document_cache[key] = doc
    return doc


def close_cached_document(pdf_path: Union[str, Path]) -> None:
    """Ferme et retire du cache le document associe a ce chemin.

    A appeler une fois qu'on a fini de traiter toutes les pages d'un PDF
    donne (fin de boucle), pour ne pas garder son descripteur de fichier
    ouvert indefiniment."""

    key = str(Path(pdf_path).resolve())
    doc = _document_cache.pop(key, None)
    if doc is not None and not doc.is_closed:
        doc.close()


def clear_document_cache() -> None:
    """Ferme tous les documents actuellement en cache (tous PDF confondus)."""

    for doc in _document_cache.values():
        if not doc.is_closed:
            doc.close()
    _document_cache.clear()


def load_pdf_page_as_image(
    pdf_path: Union[str, Path],
    page_number: int = 0,
    dpi: int = DEFAULT_DPI
) -> np.ndarray:
    """
    Convert one PDF page into an OpenCV BGR image.

    Le fichier n'est lu depuis le disque qu'une seule fois par chemin
    (voir _get_cached_document ci-dessus) : les appels suivants sur le
    meme pdf_path (typiquement une page a la fois, dans une boucle OCR
    sur le PDF nettoye/reduit) reutilisent le document deja ouvert au
    lieu de le rouvrir a chaque page. Pensez a appeler
    close_cached_document(pdf_path) une fois toutes les pages de ce PDF
    traitees.
    """

    pdf_path = str(pdf_path)

    if not Path(pdf_path).exists():
        raise FileNotFoundError(
            f"Le fichier PDF n'existe pas : {pdf_path}"
        )

    doc = _get_cached_document(pdf_path)

    if page_number < 0 or page_number >= len(doc):
        raise IndexError(
            f"Page {page_number} invalide "
            f"pour un PDF de {len(doc)} page(s)."
        )

    page = doc[page_number]

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    pix = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    img = np.frombuffer(
        pix.samples,
        dtype=np.uint8
    ).reshape(
        (pix.height, pix.width, pix.n)
    )

    if pix.n == 3:
        img_bgr = cv2.cvtColor(
            img,
            cv2.COLOR_RGB2BGR
        )
    elif pix.n == 4:
        img_bgr = cv2.cvtColor(
            img,
            cv2.COLOR_RGBA2BGR
        )
    else:
        img_bgr = cv2.cvtColor(
            img,
            cv2.COLOR_GRAY2BGR
        )

    # Le document N'EST PLUS ferme ici -- il reste en cache pour les
    # appels suivants sur ce meme fichier (voir close_cached_document).

    return img_bgr


def load_input_document(
    file_path: Union[str, Path],
    page_number: int = 0,
    dpi: int = DEFAULT_DPI
) -> Tuple[np.ndarray, str]:
    """
    Load a PDF page or an image and return:
        - image as OpenCV BGR
        - description of the input
    """

    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":

        image = load_pdf_page_as_image(
            path,
            page_number=page_number,
            dpi=dpi
        )

        info = (
            f"PDF '{path.name}' "
            f"(Page {page_number + 1}, {dpi} DPI)"
        )

    elif suffix in IMAGE_EXTENSIONS:

        image = cv2.imread(str(path))

        if image is None:
            raise ValueError(
                f"Impossible de lire l'image : {file_path}"
            )

        info = f"Image '{path.name}'"

    else:
        raise ValueError(
            f"Format non supporté : {suffix}"
        )

    return image, info


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """
    Basic image preprocessing before OCR.

    Currently keeps the original image.
    Additional preprocessing steps can be added here later.
    """

    if image is None:
        raise ValueError("L'image fournie est vide.")

    return image
