"""
Stage 3: Information Extraction
================================

This module takes the useful sections identified by Stage 2 and
extracts the equipment information contained in those sections.

Pipeline:

    Useful sections from Stage 2
              ↓
        Section page ranges
              ↓
        Native text extraction
              +
        Native table extraction
              ↓
        OCR fallback when necessary
              ↓
        Combined section content
              ↓
        LLM information extraction
              ↓
        Structured equipment information

Stage 3 does NOT decide whether a section is useful.
That decision belongs to Stage 2.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import pymupdf as fitz

from src.llm.extractor import extract_with_llm
from src.ocr.ocr_pipeline import ocr_pipeline as default_ocr_pipeline

try:
    from backend.family_matcher import match_batch as _match_families
except Exception:  # matcher is optional; Stage 3 still works without it
    _match_families = None

logger = logging.getLogger(__name__)


# PAGE EXTRACTION
def extract_native_text(
    doc,
    page_number: int,
) -> dict[str, Any]:
    """
    Extract native text from one page of an already-open PyMuPDF document.

    Page numbers are 1-based.
    """

    text = doc[page_number - 1].get_text("text")

    return {
        "text": text,
        "page": page_number,
        "method": "native_text",
    }


def extract_tables(
    pdf,
    page_number: int,
) -> dict[str, Any]:
    """
    Extract native tables from one page of an already-open pdfplumber PDF.

    Page numbers are 1-based.
    """

    result = {
        "page": page_number,
        "method": "table",
        "success": False,
        "tables": [],
        "message": "",
    }

    try:
        raw_tables = pdf.pages[
            page_number - 1
        ].extract_tables()

        tables = []

        for table in raw_tables:

            if not table:
                continue

            if len(table) > 1:
                df = pd.DataFrame(
                    table[1:],
                    columns=table[0],
                )
            else:
                df = pd.DataFrame(table)

            tables.append(df)

        result["tables"] = tables
        result["success"] = bool(tables)
        result["message"] = (
            f"{len(tables)} table(s) detected"
        )

    except Exception as exc:

        result["message"] = (
            f"Table extraction failed: {exc}"
        )

    return result


# PAGE CONTENT EXTRACTION
def extract_page_content(
    doc,
    pdf,
    page_number: int,
    pdf_path: str | Path,
    ocr_pipeline=None,
    min_text_length: int = 50,
    dpi: int = 300,
) -> dict[str, Any]:
    """
    Extract text and tables from one page.

    Strategy:

        1. Native text
        2. Native tables
        3. If native extraction is insufficient:
               OCR fallback

    Page numbers are 1-based.
    """

    # 1. Native text
    native_text_result = extract_native_text(
        doc,
        page_number,
    )

    native_text = (
        native_text_result
        .get("text", "")
        .strip()
    )

    # 2. Native tables
    native_tables_result = extract_tables(
        pdf,
        page_number,
    )

    native_tables = native_tables_result.get(
        "tables",
        [],
    )

    # 3. Check native extraction
    has_text = (
        len(native_text) >= min_text_length
    )

    has_tables = bool(native_tables)

    if has_text or has_tables:

        return {
            "page": page_number,
            "text": native_text,
            "tables": native_tables,
            "method": "native",
            "text_method": "native_text",
            "table_method": "native_table",
        }

    # 4. OCR fallback
    if ocr_pipeline is None:

        return {
            "page": page_number,
            "text": native_text,
            "tables": native_tables,
            "method": "native_only",
            "text_method": "native_text",
            "table_method": "native_table",
        }

    logger.info(
        "Native extraction insufficient on page %s. "
        "Using OCR.",
        page_number,
    )

    # OCR pipeline expects 0-based page number
    ocr_result = ocr_pipeline.process(
        pdf_path,
        page_number=page_number - 1,
        dpi=dpi,
    )

    # 5. OCR reconstructed table
    ocr_table = ocr_result.get(
        "dataframe"
    )

    ocr_tables = []

    if (
        ocr_table is not None
        and not ocr_table.empty
    ):
        ocr_tables.append(
            ocr_table
        )

    # 6. Convert OCR table to text
    ocr_text_parts = []

    for table in ocr_tables:

        table = table.fillna("")

        for _, row in table.iterrows():

            values = [
                str(value).strip()                for value in row.tolist()
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
        "ocr_result": ocr_result,
    }


# SECTION EXTRACTION
def process_section(
    pdf_path: str | Path,
    section: dict[str, Any],
    ocr_pipeline=None,
    dpi: int = 300,
    min_text_length: int = 50,
) -> dict[str, Any]:
    """
    Extract information from one useful section.

    The section must contain:

        section_id
        title
        page_start
        page_end

    or:

        start_page
        end_page
    """

    section_title = section["title"]

    start_page = section.get(
        "start_page",
        section.get("page_start"),
    )

    end_page = section.get(
        "end_page",
        section.get("page_end"),
    )

    if start_page is None or end_page is None:
        raise ValueError(
            f"Section '{section_title}' has no valid page range."
        )

    logger.info(
        "Processing section '%s' (pages %s-%s)",
        section_title,
        start_page,
        end_page,
    )

    all_text = []
    all_tables = []
    extraction_methods = []

    doc = fitz.open(str(pdf_path))
    pdf = pdfplumber.open(str(pdf_path))

    try:
        # Extract every page in the section
        for page_number in range(
            start_page,
            end_page + 1,
        ):

            page_result = extract_page_content(
                doc=doc,
                pdf=pdf,
                page_number=page_number,
                pdf_path=pdf_path,
                ocr_pipeline=ocr_pipeline,
                min_text_length=min_text_length,
                dpi=dpi,
            )

            # Text
            if page_result["text"]:

                all_text.append(
                    f"--- PAGE {page_number} ---\n"
                    f"{page_result['text']}"
                )

            # Tables
            all_tables.extend(
                page_result.get(
                    "tables",
                    [],
                )
            )

            extraction_methods.append(
                page_result["method"]
            )
    finally:
        doc.close()
        pdf.close()

    # Combine section text
    section_text = "\n\n".join(
        all_text
    )

    # Convert tables to text
    table_text_parts = []

    for table_index, table in enumerate(
        all_tables,
        start=1,
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

    # LLM INFORMATION EXTRACTION
    llm_result = extract_with_llm(
        content_for_llm
    )

    return {
        "section_id": section.get(
            "section_id"
        ),
        "title": section_title,
        "start_page": start_page,
        "end_page": end_page,
        "extraction_methods": extraction_methods,
        "llm_result": llm_result,
        "error": None,
    }


# PARALLEL SECTION PROCESSING
def process_sections_parallel(
    pdf_path: str | Path,
    sections: list[dict[str, Any]],
    ocr_pipeline=None,
    max_workers: int = 4,
    dpi: int = 300,
    min_text_length: int = 50,
) -> list[dict[str, Any]]:
    """
    Process all useful sections in parallel.

    IMPORTANT:
        Unlike the previous implementation, this function does NOT
        read sections from a CSV.

        Sections come directly from Stage 2.

    Results are returned in the same order as the input sections.
    """

    if not sections:

        logger.warning(
            "Stage 3 received no useful sections."
        )

        return []

    logger.info(
        "Stage 3: processing %d useful sections.",
        len(sections),
    )

    results = [None] * len(sections)

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {}

        for index, section in enumerate(
            sections
        ):

            future = executor.submit(
                process_section,
                pdf_path,
                section,
                ocr_pipeline,
                dpi,
                min_text_length,
            )

            futures[future] = index

        for future in as_completed(
            futures
        ):

            index = futures[future]
            section = sections[index]

            try:

                results[index] = (
                    future.result()
                )

                logger.info(
                    "Finished section '%s'.",
                    section["title"],
                )

            except Exception as exc:

                logger.exception(
                    "Failed section '%s'.",
                    section["title"],
                )

                results[index] = {
                    "section_id": section.get(
                        "section_id"
                    ),
                    "title": section["title"],
                    "start_page": section.get(
                        "start_page",
                        section.get("page_start"),
                    ),
                    "end_page": section.get(
                        "end_page",
                        section.get("page_end"),
                    ),
                    "llm_result": None,
                    "error": str(exc),
                }

    logger.info(
        "Stage 3 completed."
    )

    return results


# STAGE 3 ENTRY POINT
def run_stage_3(
    pdf_path: str | Path,
    useful_sections: list[dict[str, Any]],
    ocr_pipeline=None,
    max_workers: int = 4,
    dpi: int = 300,
    min_text_length: int = 50,
) -> dict[str, Any]:
    """
    Run the complete Stage 3 information extraction pipeline.

    Parameters
    ----------
    pdf_path:
        Input PDF.

    useful_sections:
        Sections selected by Stage 2.

    ocr_pipeline:
        Existing OCR pipeline instance.

    max_workers:
        Maximum number of sections processed in parallel.

    dpi:
        OCR resolution.

    min_text_length:
        Minimum native text length before OCR fallback.

    Returns
    -------
    dict
        JSON-friendly Stage 3 result.
    """

    results = process_sections_parallel(
        pdf_path=pdf_path,
        sections=useful_sections,
        ocr_pipeline=ocr_pipeline,
        max_workers=max_workers,
        dpi=dpi,
        min_text_length=min_text_length,
    )

    _apply_family_matching(results)

    return {
        "stage": 3,
        "total_sections": len(
            useful_sections
        ),
        "results": results,
    }


# FAMILY NORMALIZATION
def _field_value(fields: dict[str, Any], key: str) -> Any:
    v = fields.get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _apply_family_matching(results: list[dict[str, Any]]) -> None:
    """
    Fill / canonicalize the `family` field on every extracted machine by
    mapping its raw family text (or asset name) onto the i-Sense family
    catalog via backend.family_matcher.

    - The original extractor value is preserved as `family_raw`.
    - When the family was NOT explicitly stated, the filled value is
      tagged `"inferred": true`.
    - Runs one batched embeddings call for the whole document (only for
      assets that offline matching could not resolve).
    - No-op if the matcher is unavailable or nothing needs matching.
    """

    if _match_families is None or not results:
        return

    queries: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []

    for item in results:
        if not item or item.get("error"):
            continue

        lr = item.get("llm_result")
        res = lr.get("result") if isinstance(lr, dict) else None
        if not isinstance(res, dict):
            continue

        machines = res.get("machines")
        machines = machines if isinstance(machines, list) else [res]

        for machine in machines:
            fields = machine.get("fields") if isinstance(machine, dict) else None
            if not isinstance(fields, dict):
                fields = machine if isinstance(machine, dict) else None
            if not isinstance(fields, dict):
                continue

            name = _field_value(fields, "asset_name")
            raw = _field_value(fields, "family")
            if not name and not raw:
                continue

            queries.append({
                "asset_name": name,
                "reference": _field_value(fields, "reference"),
                "family_raw": raw,
                "section_title": item.get("title"),
            })
            targets.append(fields)

    if not queries:
        return

    try:
        matches = _match_families(queries)
    except Exception as exc:
        logger.warning("Family matching skipped: %s", exc)
        return

    filled = 0
    for fields, query, match in zip(targets, queries, matches):
        fields["family_raw"] = query["family_raw"]
        if not match.get("family"):
            continue

        prev_page = None
        if isinstance(fields.get("family"), dict):
            prev_page = fields["family"].get("page")

        fields["family"] = {
            "value": match["family"],
            "confidence": match.get("family_score", 0.0),
            "page": prev_page,
            "inferred": not query["family_raw"],
            "match_source": match.get("family_source"),
        }
        filled += 1

    logger.info(
        "Family matching: %d/%d machines mapped to a catalog family.",
        filled,
        len(queries),
    )