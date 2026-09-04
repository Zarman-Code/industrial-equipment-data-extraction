# Industrial Equipment Data Extraction

## Overview

Industrial equipment manuals are rarely organized in a way that makes equipment data easy to extract automatically. A single PDF may contain hundreds or thousands of pages, multiple machines, technical tables, drawings, bilingual sections, scanned pages, and document-level navigation such as bookmarks or tables of contents.

This project turns those complex PDF documents into structured equipment information that can be used by an asset-management system such as **i-Sense**.

The main objective is to answer two questions reliably:

1. **Where in the document is the useful equipment information?**
2. **What equipment information can be extracted from those pages?**

To achieve this, the project processes the document progressively instead of sending the entire PDF directly to an LLM.

---

## The Problem

A typical industrial document can contain:

- general documentation and administrative pages
- tables of contents
- installation and maintenance instructions
- technical specifications
- equipment data sheets
- electrical information
- drawings and diagrams
- spare-parts information
- several machines described in the same document
- scanned pages with no usable native text
- complex tables and merged cells
- bilingual content

Only a small portion of this information may be relevant to equipment creation in i-Sense.

A naive approach would send large amounts of the document to an LLM and ask it to extract everything. This is expensive, difficult to control, and can cause relevant information to be missed.

The project therefore uses a **document-first pipeline**: understand the document structure first, identify promising sections, and only then perform detailed information extraction.

---

# Processing Pipeline

```text
                         INDUSTRIAL PDF
                              │
                              ▼
                 ┌────────────────────────┐
                 │  Stage 1               │
                 │  Document Structure    │
                 │                        │
                 │  • Bookmarks            │
                 │  • TOC                 │
                 │  • Titles / headings   │
                 │  • Page structure      │
                 └───────────┬────────────┘
                             │
                             ▼
                    Candidate sections
                             │
                             ▼
                 ┌────────────────────────┐
                 │  Stage 2               │
                 │  Section Classification│
                 │                        │
                 │  LLM identifies which  │
                 │  sections are useful   │
                 └───────────┬────────────┘
                             │
                             ▼
                     Useful sections
                             │
                             ▼
                 ┌────────────────────────┐
                 │  Stage 3               │
                 │  Information Extraction│
                 │                        │
                 │  • Native text         │
                 │  • Native tables       │
                 │  • OCR when needed     │
                 │  • LLM extraction      │
                 └───────────┬────────────┘
                             │
                             ▼
                  Structured equipment data
                             │
                             ▼
                 ┌────────────────────────┐
                 │  Post-processing       │
                 │  Family normalization  │
                 └───────────┬────────────┘
                             │
                             ▼
                       i-Sense-ready JSON
```

The pipeline is intentionally divided into independent stages so that document analysis, section selection, and information extraction can be developed and evaluated separately.

---

# Stage 1: Document Structure

The first stage does **not** use an LLM.

Its purpose is to understand how the PDF is organized and produce a list of candidate sections with page ranges.

### First choice: native PDF bookmarks

If the PDF contains usable bookmarks, the project uses them because they provide explicit document structure.

The bookmark information is cleaned and reorganized before being converted into sections.

The `BookmarkProcessor` handles document-specific issues such as:

- duplicate numeric-only bookmark entries
- bilingual English/French bookmark structures
- section numbering
- title cleaning
- hierarchy reconstruction
- section page ranges

### Fallback: structural analysis

Some PDFs do not contain useful bookmarks.

In that case, the project analyzes the document itself:

```text
PDF pages
   │
   ├── Page analysis
   │
   ├── Heading/title detection
   │
   ├── Printed TOC detection
   │
   └── Document segmentation
```

This allows the system to recover useful document structure even when the PDF's internal navigation is missing.

### Stage 1 output

The result is a list of candidate sections:

```json
{
  "section_id": "bm_3",
  "title": "Compressor Data Sheet",
  "section_number": "3.02",
  "level": 1,
  "start_page": 107,
  "end_page": 115,
  "source": "bookmark",
  "confidence": 0.95
}
```

At this point, the system knows **where sections are**, but not yet whether they contain useful equipment information.

More details are available in:

`src/document_structure/README.md`

---

# Stage 2: Finding Useful Sections

Stage 2 uses an LLM to determine which sections are worth processing in detail.

The LLM receives the candidate sections produced by Stage 1, including information such as:

- section ID
- title
- section number
- page range
- hierarchy level

It does **not** receive the full page content at this stage.

For every candidate section, the classifier produces:

- a relevance score from 0 to 100
- a reason for the score
- the type of information that might be present

The model also returns the IDs of the sections selected for the next stage.

Example:

```json
{
  "sections": [
    {
      "section_id": "bm_3",
      "relevance_score": 95,
      "reason": "The section appears to contain technical data for a specific compressor.",
      "potential_information": [
        "manufacturer",
        "model",
        "power"
      ]
    }
  ],
  "selected_sections": [
    "bm_3"
  ]
}
```

This step reduces the amount of document content that needs to go through the more expensive extraction process.

The implementation is in:

- `src/llm/classifier.py`
- `src/llm/prompts.py`
- `src/llm/schemas.py`

---

# Stage 3: Information Extraction

Stage 3 works only on the sections selected by Stage 2.

For every selected section, the system processes its pages and combines the available information before sending it to the extraction LLM.

The extraction strategy is:

```text
Selected section
      │
      ▼
Native text extraction
      │
      ├───────────────┐
      ▼               ▼
Native tables       insufficient?
                      │
                      ▼
                     OCR
                      │
                      ▼
             Combined section content
                      │
                      ▼
               LLM extraction
```

### Native text

PyMuPDF is used to extract text directly from the PDF when the document contains a usable text layer.

### Native tables

`pdfplumber` is used to detect and reconstruct tables.

This is important for technical documents because specifications are often stored in tabular form.

### OCR fallback

Some pages are scanned or have too little usable native text.

When native extraction is insufficient, the project falls back to the OCR pipeline.

The current OCR path uses PaddleOCR to reconstruct information from those pages.

This means OCR is not automatically run on every page. It is used when native extraction does not provide enough information.

More details are available in:

`src/ocr/OCR_README.md`

### LLM extraction

Once the section content has been collected, the combined text and tables are passed to:

```python
extract_with_llm(...)
```

The extraction schema supports equipment information such as:

- asset name
- reference / model
- family
- power
- manufacturer
- outlier
- asset diagram

The project also supports documents containing multiple machines, ensuring that information belonging to different machines is not automatically merged into a single asset.

The LLM extraction logic is implemented in:

- `src/llm/extractor.py`
- `src/llm/prompts.py`
- `src/llm/schemas.py`

---

# Family Normalization

Family normalization is a separate post-processing step.

The extraction model may return a family name that does not exactly match the vocabulary used by i-Sense.

For example, a document might use a more specific or slightly different equipment-family name than the canonical i-Sense catalog.

The family matcher therefore attempts to map the extracted family to the official catalog using:

1. exact / normalized matching
2. offline fuzzy matching
3. semantic matching when necessary

The semantic matching step uses embeddings rather than another chat-based LLM.

The canonical family catalog is stored in:

```text
data/reference/families.json
```

This step keeps family normalization separate from the main information extraction process.

---

# What the Pipeline Produces

The final result is structured JSON representing the equipment found in the document.

A simplified result looks like:

```json
{
  "machines": [
    {
      "machine_id": "machine_1",
      "name": "Screw Compressor 101",
      "fields": {
        "manufacturer": {
          "value": "Sabroe",
          "confidence": 0.95,
          "page": 107
        },
        "reference": {
          "value": "SAB 202 SL",
          "confidence": 0.80,
          "page": 108
        },
        "power": {
          "value": "250 kW",
          "confidence": 0.70,
          "page": 109
        }
      }
    }
  ]
}
```

The exact response structure is defined by the Pydantic models in:

```text
src/llm/schemas.py
```

The extracted information can then be consumed by the i-Sense interface or another downstream system.

---

# Project Structure

```text
.
├── main.py
│
├── frontend/
│   └── index.html
│
├── backend/
│   ├── pipeline.py
│   ├── stage1_document_structure.py
│   ├── stage2_section_classification.py
│   ├── stage3_information_extraction.py
│   ├── family_matcher.py
│   └── test.py
│
├── src/
│   ├── document_structure/
│   │   ├── models.py
│   │   ├── extract_raw_pdf_toc.py
│   │   ├── bookmark_processor.py
│   │   ├── page_analysis.py
│   │   ├── titles.py
│   │   ├── toc.py
│   │   └── analyzer.py
│   │
│   ├── llm/
│   │   ├── classifier.py
│   │   ├── extractor.py
│   │   ├── prompts.py
│   │   ├── schemas.py
│   │   └── config.py
│   │
│   ├── ocr/
│   │   └── ...
│   │
│   └── information_extraction.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── reference/
│       └── families.json
│
├── results/
├── notebook/
├── docs/
├── requirements.txt
└── .env
```

### Main components

| Component | Role |
|---|---|
| `backend/pipeline.py` | Connects the processing stages |
| `stage1_document_structure.py` | Builds candidate document sections |
| `stage2_section_classification.py` | Sends candidate sections to the relevance classifier |
| `stage3_information_extraction.py` | Extracts content from selected sections |
| `family_matcher.py` | Normalizes equipment families |
| `src/document_structure/` | Document structure analysis |
| `src/llm/` | LLM classification and extraction |
| `src/ocr/` | OCR and table reconstruction |
| `frontend/index.html` | Simple upload and result interface |
| `main.py` | FastAPI entry point |

---

# Setup

## Requirements

The project uses Python 3.13.

Install the project dependencies:

```bash
pip install -r requirements.txt
```

The current `requirements.txt` may need to be completed depending on the environment. The project uses libraries including:

```text
fastapi
uvicorn
python-dotenv
openai
pydantic

pymupdf
pdfplumber
pandas
numpy

opencv-python
pillow
paddleocr
pytesseract
```

PaddleOCR is the heaviest component because its models must be downloaded and loaded before OCR processing can begin.

GPU acceleration can be used when the environment supports it; otherwise the OCR pipeline falls back to CPU processing.

## Environment variables

Create a `.env` file at the project root:

```env
OPENAI_API_KEY=your_api_key_here
```

The LLM configuration is loaded from:

```text
src/llm/config.py
```

The model used by the current configuration is defined there as `LLM_MODEL`.

---

# Running the Project

The project can be run either through the web interface or directly from the command line.

## Option 1: Run the Web Application

### Step 1: Start the Backend

Open a terminal at the project root and run:

```bash
python main.py
```

This starts the FastAPI backend responsible for receiving the PDF and running the extraction pipeline.

### Step 2: Start the Frontend

Open a **second terminal** and run:

```bash
python -m http.server 5500 -d frontend
```

Then open the following address in your browser:

```text
http://localhost:5500
```

You can now upload a PDF through the web interface.

### Environment Setup

Before running the application, create a `.env` file at the project root containing your OpenAI API key:

```env
OPENAI_API_KEY=sk-...
```

This is a one-time setup. The backend and pipeline modules require this variable to be available when they are imported.

---

## Option 2: Test the Pipeline Directly

If you want to test the extraction pipeline without starting the frontend, run:

```bash
python -m backend.test
```

This executes the complete pipeline directly on the PDF configured in:

```text
backend/test.py
```

The PDF path is defined by the `PDF_PATH` variable.

The test script:

1. Runs the document-structure stage
2. Classifies relevant sections
3. Extracts equipment information
4. Prints a stage-by-stage summary
5. Saves the final result to:

```text
results/pipeline_result.json
```

This mode is particularly useful during development because it allows the pipeline to be tested independently of the web interface.

---

# Development Philosophy

The project is deliberately built as a sequence of smaller decisions rather than one large LLM call.

### 1. Understand the document first

Before extracting information, determine how the document is organized.

### 2. Narrow the search space

Use Stage 2 to identify the sections most likely to contain equipment information.

### 3. Extract only where it matters

Run detailed text, table, OCR, and LLM extraction on the selected sections instead of the entire document.

### 4. Keep responsibilities separate

The main components have distinct roles:

```text
Document structure
        ↓
Section selection
        ↓
Information extraction
        ↓
Normalization
```

This makes individual stages easier to test, replace, and improve.

---

# Development History

The current pipeline grew out of a series of exploratory notebooks.

The notebooks remain useful for understanding how the different components were developed and tested.

| Notebook | Purpose |
|---|---|
| `01_pdf_exploration.ipynb` | Initial PDF exploration |
| `02_information_extraction.ipynb` | Early information extraction experiments |
| `03_document_structure_analysis.ipynb` | Development of document structure analysis |
| `04_Ocr_Dual_Pipeline.ipynb` | OCR and table extraction experiments |
| `05_toc_ocr_llm1_pipeline2.ipynb` | TOC, OCR, and section classification experiments |
| `06_bookmark_llm1_pipeline.ipynb` | Bookmark-based section classification |
| `06_llm_section_extraction.ipynb.ipynb` | LLM information extraction |

The notebooks are primarily development and experimentation material. The `backend/` pipeline is the main implementation path.

---

# Documentation

For deeper technical details, see:

- `src/document_structure/README.md` — document structure analysis, bookmarks, TOC detection, title detection, and segmentation
- `src/llm/README.md` — prompts, schemas, classification, and extraction behavior
- `src/ocr/OCR_README.md` — OCR and table extraction
- `docs/document_structure_architecture.md` — design of the bookmark and structural paths
- `docs/isense-field-mapping.md` — mapping extracted information to the i-Sense asset model

---

# Current Direction

The project is designed to evolve as more industrial documents are tested.

The main development priorities are:

- improving document-structure detection on difficult PDFs
- improving identification of useful equipment sections
- improving extraction from complex and merged tables
- using OCR when document layout is important
- supporting documents containing multiple machines
- improving confidence and validation of extracted fields
- improving the mapping from extracted equipment information to the i-Sense data model

The goal is not simply to extract text from PDFs. The goal is to reliably transform **complex industrial documentation into structured equipment records that can be used downstream**.
