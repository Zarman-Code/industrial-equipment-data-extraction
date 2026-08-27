from pathlib import Path
import os
import sys


# Project directories

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RESULT_DIR = PROJECT_ROOT / "result_ppstructure"
EXPORT_DIR = RESULT_DIR / "extracted"

DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# OCR configuration

DEFAULT_DPI = 300

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".webp",
)


# Tesseract

TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# Compute device

try:
    import torch

    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
except ImportError:
    DEVICE = "cpu"


# Display / encoding

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )