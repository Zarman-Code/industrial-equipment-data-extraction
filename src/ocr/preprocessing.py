from pathlib import Path
from typing import Union, Tuple

import cv2
import pymupdf as fitz
import numpy as np

from .config import DEFAULT_DPI, IMAGE_EXTENSIONS


def load_pdf_page_as_image(
    pdf_path: Union[str, Path],
    page_number: int = 0,
    dpi: int = DEFAULT_DPI
) -> np.ndarray:
    """
    Convert one PDF page into an OpenCV BGR image.
    """

    pdf_path = str(pdf_path)

    if not Path(pdf_path).exists():
        raise FileNotFoundError(
            f"Le fichier PDF n'existe pas : {pdf_path}"
        )

    doc = fitz.open(pdf_path)

    if page_number < 0 or page_number >= len(doc):
        doc.close()
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

    doc.close()

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