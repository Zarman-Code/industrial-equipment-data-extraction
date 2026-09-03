# `src/ocr/` OCR module overview

Table-focused OCR pipeline built on PaddleOCR (layout detection → table
structure recognition → cell-level text recognition), plus a small set of
post-processing helpers for turning the raw OCR output into equipment
specification fields.

## Files

### `config.py`
Project-wide constants and setup, imported by the other modules.

- `PROJECT_ROOT`, `DATA_DIR`, `RESULT_DIR`, `EXPORT_DIR` — resolved paths,
  created on import if missing.
- `DEFAULT_DPI = 300` — default render resolution for PDF pages.
- `IMAGE_EXTENSIONS` — recognized standalone image formats.
- `TESSERACT_EXE` — a Windows path to `tesseract.exe` (currently unused by
  `ocr_pipeline.py`, which uses PaddleOCR instead — leftover from an
  earlier Tesseract-based approach, harmless as-is).
- `DEVICE` — `"cuda"` if `torch` is installed and a GPU is available,
  else `"cpu"` (not currently wired into `OCRPipeline`, which always uses
  PaddleOCR's own device handling).

### `preprocessing.py`
Turns a PDF page or image file into an OpenCV BGR array for OCR.

- `load_pdf_page_as_image(pdf_path, page_number=0, dpi=300)` — opens the
  PDF with PyMuPDF, renders one page (0-indexed) at the given DPI, and
  returns it as a BGR `np.ndarray`. Raises `FileNotFoundError` if the PDF
  doesn't exist, `IndexError` if `page_number` is out of range.
- `load_input_document(file_path, page_number=0, dpi=300)` — dispatches
  to `load_pdf_page_as_image` for `.pdf`, or `cv2.imread` for any
  extension in `IMAGE_EXTENSIONS`. Returns `(image, info_string)`.
- `preprocess_image(image)` — currently a no-op passthrough (validates
  the image isn't `None`); the natural place to add deskew/contrast/etc.
  later without touching `OCRPipeline`.

### `ocr_pipeline.py`
The actual OCR engine. Defines `OCRPipeline` and one ready-to-use
instance, `ocr_pipeline`.

- `OCRPipeline.__init__()` — lazily imports and loads three PaddleOCR
  models: `LayoutDetection` (finds table regions),
  `TableStructureRecognition` (finds cells within a table),
  `TextRecognition` (reads text out of a cropped cell). This happens
  **once**, at import time, via the module-level `ocr_pipeline =
  OCRPipeline()` — importing this module always pays PaddleOCR's model
  load cost.
- `detect_tables(image)` — runs `LayoutDetection`, keeps only boxes
  labeled `"table"`.
- `recognize_table_structure(table_image)` — runs
  `TableStructureRecognition` on a cropped table region, returns cell
  bounding boxes/centers plus the model's structure/score.
- `ocr_cell(image, bbox, padding=3)` / `ocr_cells(image, cells)` — crop
  and OCR one cell (or a whole list of them) with `TextRecognition`.
- `reconstruct_table(cells)` — groups OCR'd cells into rows by vertical
  position, builds a `pandas.DataFrame` (first row becomes column
  headers, blank headers become `Col_N`).
- **`process(file_path, page_number=0, dpi=300)`** — the main entry
  point; runs the full pipeline end to end (see below).

### `utils.py`
Post-processing helpers that work on `process()`'s output.

- `normalize_text(text)` — cleans OCR text: fixes special
  spaces/dashes, `"°C"`/`"deg C"` → `"C"`, decimal commas → decimal
  points, collapses whitespace.
- `clean_dataframe(df)` — strips/collapses whitespace in every cell,
  drops fully-empty rows and columns.
- `extract_equipment_fields(df, free_text_corpus="")` — regex-based
  extraction of common equipment nameplate fields (manufacturer, model,
  serial number, power, voltage, frequency, current, speed, efficiency
  class, protection degree, insulation class, weight, operating
  pressure) from a table + optional extra free text. Returns a dict of
  `{field: {raw_value, normalized_value, unit, confidence}}` — a field
  not found still gets an entry, with everything `None`/`0.0`.
- `display_equipment_summary(fields)` — turns that dict into a friendly
  `DataFrame` (`Field`, `Value`, `Unit`, `Status`, `Confidence`) for
  quick display in a notebook.

### `__init__.py`
Empty — just marks `src/ocr` as a package. No re-exports, so everything
above is imported from its own submodule (see usage below).

## How to use it

### Minimal — OCR one page

```python
from src.ocr.ocr_pipeline import ocr_pipeline

result = ocr_pipeline.process(
    "path/to/document.pdf",
    page_number=0,   # 0-indexed PDF page
    dpi=300,
)

result["dataframe"]        # the reconstructed table, as a DataFrame
result["cells"]             # every OCR'd cell: text, score, bbox, cx, cy
result["tables"]            # raw table regions found by LayoutDetection
result["processing_time"]   # seconds
```

Import `ocr_pipeline` (the singleton instance), not `OCRPipeline` the
class — instantiating your own `OCRPipeline()` reloads all three
PaddleOCR models again, which is slow and unnecessary.

`process()` is **table-only**: if `detect_tables()` finds no table on
the page, it returns immediately with empty `tables`/`cells` and an
empty `dataframe` — there's no whole-page free-text OCR path. It also
only ever looks at the **first** detected table (`tables[0]`); a page
with multiple tables needs its own loop over `detect_tables()`'s result
if you want all of them.

### Full pipeline — OCR → clean → extract fields

```python
from src.ocr.ocr_pipeline import ocr_pipeline
from src.ocr.utils import clean_dataframe, extract_equipment_fields, display_equipment_summary

result = ocr_pipeline.process("path/to/document.pdf", page_number=3, dpi=300)

table = clean_dataframe(result["dataframe"])

fields = extract_equipment_fields(table)
# or, to also search any extra free text you've extracted separately:
# fields = extract_equipment_fields(table, free_text_corpus=some_raw_text)

display_equipment_summary(fields)
```

`display_equipment_summary` gives a nicely formatted DataFrame for
notebook display; the raw `fields` dict is what you'd want if you're
merging results across many pages into one big table/CSV — each field's
`confidence` is currently a flat `0.95` when a pattern matches and `0.0`
when it doesn't (not a true OCR/model confidence).

### Batching over many pages

`process()` only does one page at a time, so looping over a whole PDF
looks like:

```python
import fitz  # or pymupdf
from src.ocr.ocr_pipeline import ocr_pipeline
from src.ocr.utils import clean_dataframe, extract_equipment_fields

doc = fitz.open("path/to/document.pdf")

all_fields = []

for page_number in range(len(doc)):
    result = ocr_pipeline.process("path/to/document.pdf", page_number=page_number, dpi=300)

    if result["dataframe"].empty:
        continue  # no table found on this page

    table = clean_dataframe(result["dataframe"])
    fields = extract_equipment_fields(table)
    fields["page_number"] = page_number + 1  # 1-indexed for humans
    all_fields.append(fields)
```

### Adding your own preprocessing

`preprocess_image()` in `preprocessing.py` is currently a no-op. If OCR
accuracy is suffering on scanned/noisy pages, that's the single function
to extend (deskew, denoise, contrast/threshold, etc.) — `OCRPipeline.process()`
already calls it, so anything added there applies automatically without
touching `ocr_pipeline.py`.
