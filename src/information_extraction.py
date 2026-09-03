from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from pydoc import doc
from src.llm.extractor import extract_with_llm
from src.ocr.ocr_pipeline import ocr_pipeline

import pandas as pd
import pdfplumber
import pymupdf as fitz



def extract_native_text(pdf_path, page_number):
    """
    Extract native text from a single PDF page using PyMuPDF.
    """
    doc = fitz.open(pdf_path)
    text = doc[page_number - 1].get_text('text')
    return {'text': text, 'page': page_number, 'method': 'native_text'}


def extract_tables(pdf_path, page_number):
    """
    Extract tables from a PDF page using pdfplumber.
    """
    result = {'page': page_number, 'method': 'table', 'success': False, 'tables': [], 'message': ''}
    if pdfplumber is None:
        result['message'] = 'pdfplumber indisponible ; extraction de tableaux ignorée.'
        return result
    try:
        with pdfplumber.open(pdf_path) as pdf:
            raw_tables = pdf.pages[page_number - 1].extract_tables()
        result['tables'] = [pd.DataFrame(t[1:], columns=t[0]) if t and len(t) > 1 else pd.DataFrame(t) for t in raw_tables]
        result['success'] = bool(result['tables'])
        result['message'] = f"{len(result['tables'])} tableau(x) détecté(s)"
    except Exception as exc:
        result['message'] = f'Échec table extraction : {exc}'
    return result


def extract_page_content(
    pdf_path,
    page_number,
    ocr_pipeline=None,
    min_text_length=50,
    dpi=300
):
    """
    Extract text and tables from one PDF page.

    Strategy:
    1. Extract native text using PyMuPDF.
    2. Extract native tables using pdfplumber.
    3. If native text and tables are insufficient, use OCR
       as a fallback.

    Parameters
    ----------
    pdf_path : str or Path
        Path to the PDF.

    page_number : int
        1-based PDF page number.

    ocr_pipeline : OCRPipeline instance, optional
        Existing OCRPipeline instance. If None, OCR is not used.

    min_text_length : int
        Minimum amount of native text considered sufficient.

    dpi : int
        DPI used when OCR is triggered.

    Returns
    -------
    dict
        {
            "page": page_number,
            "text": ...,
            "tables": [...],
            "method": ...
        }
    """

    # 1. Native text

    native_text_result = extract_native_text(
        pdf_path,
        page_number
    )

    native_text = native_text_result.get("text", "").strip()

    # 2. Native tables

    native_tables_result = extract_tables(
        pdf_path,
        page_number
    )

    native_tables = native_tables_result.get(
        "tables",
        []
    )

    # 3. Check whether native extraction is sufficient

    has_text = len(native_text) >= min_text_length
    has_tables = len(native_tables) > 0

    if has_text or has_tables:

        return {
            "page": page_number,
            "text": native_text,
            "tables": native_tables,
            "method": "native",
            "text_method": "native_text",
            "table_method": "native_table"
        }

    # 4. Native extraction insufficient → OCR fallback

    if ocr_pipeline is None:

        return {
            "page": page_number,
            "text": native_text,
            "tables": native_tables,
            "method": "native_only",
            "text_method": "native_text",
            "table_method": "native_table"
        }

    print(
        f"Native extraction insufficient on page "
        f"{page_number}. Using OCR..."
    )

    # OCRPipeline expects 0-based page numbers
    ocr_result = ocr_pipeline.process(
        pdf_path,
        page_number=page_number - 1,
        dpi=dpi
    )

    # 5. Get OCR reconstructed table

    ocr_table = ocr_result.get("dataframe")

    ocr_tables = []

    if ocr_table is not None and not ocr_table.empty:
        ocr_tables.append(ocr_table)

    # 6. Convert OCR table to text

    ocr_text_parts = []

    for table in ocr_tables:

        table = table.fillna("")

        for _, row in table.iterrows():

            values = [
                str(value).strip()
                for value in row.tolist()
                if str(value).strip()
            ]

            if values:
                ocr_text_parts.append(
                    " | ".join(values)
                )

    ocr_text = "\n".join(
        ocr_text_parts
    )

    # 7. Return OCR result

    return {
        "page": page_number,
        "text": ocr_text,
        "tables": ocr_tables,
        "method": "ocr",
        "text_method": "paddleocr",
        "table_method": "paddleocr",
        "ocr_result": ocr_result
    }



def load_sections(csv_path):
    """
    Load section definitions from a CSV file.

    Parameters
    ----------
    csv_path : str or Path
        Path to the CSV file containing section definitions.

    Returns
    -------
    list of dict
        List of section dictionaries.
    """
    df = pd.read_csv(csv_path, sep=";")

    sections = []

    for _, row in df.iterrows():

        section = {
            "title": row["title"],
            "start_page": int(row["page_start"]),
            "end_page": int(row["page_end"])
        }

        sections.append(section)

    return sections


def process_section(
    pdf_path,
    section,
    ocr_pipeline,
    dpi=300,
    min_text_length=50
):
    """
    Process one section:
        PDF pages
            ↓
        native text + native tables
            ↓
        OCR fallback if necessary
            ↓
        combined section content
            ↓
        LLM extraction
    """

    section_title = section["title"]
    start_page = section["start_page"]
    end_page = section["end_page"]

    print(
        f"Processing section: {section_title} "
        f"(pages {start_page}-{end_page})"
    )

    all_text = []
    all_tables = []
    extraction_methods = []

    # Extract every page belonging to the section

    for page_number in range(
        start_page,
        end_page + 1
    ):

        page_result = extract_page_content(
            pdf_path=pdf_path,
            page_number=page_number,
            ocr_pipeline=ocr_pipeline,
            min_text_length=min_text_length,
            dpi=dpi
        )

        # Text
        if page_result["text"]:
            all_text.append(
                f"--- PAGE {page_number} ---\n"
                f"{page_result['text']}"
            )

        # Tables
        all_tables.extend(
            page_result["tables"]
        )

        extraction_methods.append(
            page_result["method"]
        )

    # Combine section text

    section_text = "\n\n".join(
        all_text
    )

    # Add tables to the text sent to the LLM

    table_text_parts = []

    for table_index, table in enumerate(
        all_tables,
        start=1
    ):

        if table is None or table.empty:
            continue

        table = table.fillna("")

        table_text_parts.append(
            f"--- TABLE {table_index} ---\n"
            + table.to_string(index=False)
        )

    tables_text = "\n\n".join(
        table_text_parts
    )

    # Combine text + tables
    content_for_llm = section_text

    if tables_text:
        content_for_llm += (
            "\n\n"
            "===== TABLES =====\n"
            f"{tables_text}"
        )

    # Run LLM extraction

    llm_result = extract_with_llm(content_for_llm)

    # Return everything

    return llm_result


def process_sections_parallel(
    pdf_path,
    csv_path,
    max_workers=4,
    dpi=300,
    min_text_length=50
):
    """
    Process all useful sections in parallel.

    Each section goes through:
        PDF pages
            ↓
        native text + native tables
            ↓
        OCR fallback if necessary
            ↓
        combined section content
            ↓
        LLM extraction

    Parameters
    ----------
    pdf_path : str or Path
        Path to the PDF.

    csv_path : str or Path
        Path to the CSV containing the useful sections.

    ocr_pipeline : OCRPipeline instance
        Existing OCRPipeline instance.

    max_workers : int
        Maximum number of sections processed simultaneously.

    dpi : int
        DPI used when OCR is triggered.

    min_text_length : int
        Minimum native text length considered sufficient.

    Returns
    -------
    list
        LLM results for all sections, kept in CSV order.
    """

    # 1. Load sections

    sections = load_sections(csv_path)

    print(
        f"Found {len(sections)} sections."
    )

    # 2. Prepare result list
    #
    # We create an empty list with the same size
    # as the number of sections.
    #
    # This allows us to preserve the original CSV order
    # even though sections finish at different times.

    results = [None] * len(sections)

    # 3. Run sections in parallel

    print(
        f"\nStarting parallel processing "
        f"with {max_workers} workers...\n"
    )

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {}

        # Submit every section
        for index, section in enumerate(sections):

            future = executor.submit(
                process_section,
                pdf_path,
                section,
                ocr_pipeline,
                dpi,
                min_text_length
            )

            futures[future] = index

        # 4. Collect results as they finish

        for future in as_completed(futures):

            index = futures[future]
            section = sections[index]

            try:

                llm_result = future.result()

                results[index] = {
                    "title": section["title"],
                    "start_page": section["start_page"],
                    "end_page": section["end_page"],
                    "llm_result": llm_result,
                    "error": None
                }

                print(
                    f"✓ Finished: {section['title']}"
                )

            except Exception as exc:

                results[index] = {
                    "title": section["title"],
                    "start_page": section["start_page"],
                    "end_page": section["end_page"],
                    "llm_result": None,
                    "error": str(exc)
                }

                print(
                    f"✗ Failed: {section['title']} "
                    f"→ {exc}"
                )

    print(
        "\nAll sections have been processed."
    )

    return results