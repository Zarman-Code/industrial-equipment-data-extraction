# `pipeline/` — raw PDF → LLM extraction, end to end

This folder (plus `main.py` at the project root) is the only thing added
to run the existing pipeline as one command. **Nothing under `src/`,
`notebook/`, `data/`, or `results/` was changed** — every file here only
imports and calls the classes/functions that already existed:

| Stage | Module | Existing code it calls |
|---|---|---|
| 1. Sections from the PDF | `toc_stage.py` | `src.document_structure.extract_raw_pdf_toc`, `.bookmark_processor`, and — for PDFs with no native bookmarks — `.page_analysis`, `.titles`, `.toc`, `.analyzer` |
| 1b. Relevance filter (LLM #1) | `classification_stage.py` | `src.llm.classifier.classify_sections` |
| 2. Content + equipment extraction (LLM #2) | `extraction_stage.py` | `src.information_extraction.process_sections_parallel` (native text/tables, `src.ocr` fallback, `src.llm.extractor.extract_with_llm`) |
| glue + outputs | `run_pipeline.py`, `io_utils.py` | — |

## Why two paths in Stage 1

`AUSTCOLD.pdf` has native PDF bookmarks, so `notebook/06_bookmark_llm1_pipeline.ipynb`
builds sections straight from them via `BookmarkProcessor`. A PDF with no
bookmarks (e.g. a scanned manual) has nothing to flatten there, so
`toc_stage.py` automatically falls back to the structural pipeline
(`PageAnalyzer` → `TitleDetector` → `TOCDetector` → `DocumentSegmenter`)
that already exists in `src/document_structure/` for exactly that case.
Both paths converge on the same shape: a list of `CandidateSection(title,
start_page, end_page, ...)`.

## Usage

From the project root, with the same Python environment the notebooks use
(the one with `pymupdf`, `pdfplumber`, `openai`, `pydantic`, `paddleocr`,
`opencv-python`, `pandas` already installed) and `OPENAI_API_KEY` set in
`.env`:

```bash
python main.py --pdf data/raw/AUSTCOLD.pdf
```

```bash
python main.py --pdf "data/raw/MYCOM Operating and Maintenance Manual Refrigeration Unit (1).pdf" \
    --max-workers 4 --dpi 300
```

Useful flags while iterating (see `python main.py --help` for the full list):

- `--dry-run` — Stage 1 only. No LLM call, no PaddleOCR model load. Good
  first check that TOC/segment detection looks right for a new PDF.
- `--skip-extraction` — stop after LLM #1, so you can review
  `sections_classification.json` (relevance scores + reasons per section)
  before spending LLM #2 calls.
- `--skip-classification` — send every detected section straight to
  Stage 2, bypassing the relevance filter entirely.
- `--max-sections N` — cap how many candidate sections go into
  classification/extraction, for a cheap smoke test on a huge document.

## Outputs

Everything is written under `results/<pdf_stem>/` (never into `data/`, and
never overwriting the existing `results/extracted_sections.json` or
`data/processed/*.csv`, which stay exactly as they were):

- `toc_raw.json` — raw `extract_raw_toc()` dump, for debugging.
- `sections_candidates.csv` — every candidate section from Stage 1,
  before LLM #1 filtering.
- `sections_classification.json` — LLM #1's full response: relevance
  score, reason and potential_information per section.
- `resolved_sections.csv` — only the selected sections, in the
  `title;page_start;page_end` shape `src.information_extraction.load_sections`
  reads (same convention as the existing `data/processed/resolved_sections.csv`).
- `extracted_sections.json` / `extracted_sections_summary.csv` — Stage 2's
  raw per-section results and a success/error summary (same shape as
  `results/extracted_sections.json`, produced the same way
  `notebook/06_llm_section_extraction.ipynb.ipynb` does).
- `equipment_extraction.csv` — the flattened, spreadsheet-ready version:
  one row per section, with `family`, `asset_name`, `reference`, `power`,
  `outlier`, `manufacturer`, `asset_diagram` each split into
  `_value` / `_confidence` / `_page` columns.

## Known pre-existing quirks (not introduced here, not fixed here)

- `requirements.txt` only lists 3 of the packages the code actually
  imports (`pymupdf`, `openai`, `pydantic`, `python-dotenv`, `paddleocr`,
  `opencv-python`, `pandas`, `numpy`, … are all required too) — this
  script relies on whatever environment already runs the notebooks
  successfully.
- `src/ocr/ocr_pipeline.py` loads all three PaddleOCR models at *import*
  time (`ocr_pipeline = OCRPipeline()` at module scope). Stage 2 therefore
  pays that cost the first time it's used in a process; Stage 1/1b never
  import that module, so `--dry-run` / `--skip-extraction` avoid it
  entirely.
- On this project's Windows/PaddlePaddle setup, some OCR-fallback pages
  currently fail with
  `(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support …`
  (visible in `notebook/06_llm_section_extraction.ipynb.ipynb`'s own
  output) — an existing PaddleOCR/oneDNN environment issue, unrelated to
  this pipeline wiring. Those sections come back with
  `error` set instead of a value in `equipment_extraction.csv`.
