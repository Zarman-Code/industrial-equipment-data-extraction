"""
Stage 1: Document Structure Analysis
------------------------------------

Build a candidate list of document sections from a raw PDF.

--- Processing strategy ---

1. Check for native PDF bookmarks / outline entries.

   If usable bookmarks exist:
       PDF
        ↓
       Native bookmarks
        ↓
       BookmarkProcessor
        ↓
       Candidate sections

2. If no usable bookmarks exist, use structural analysis:

       PDF
        ↓
       PageAnalyzer
        ↓
       TitleDetector
        ↓
       TOCDetector
        ↓
       DocumentSegmenter
        ↓
       Candidate sections

The structural path can therefore detect a printed Table of Contents
and use it as part of the document segmentation process.

The output of this stage is always the same:

    list[CandidateSection]

This allows later pipeline stages to remain independent of how the
document structure was discovered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from src.document_structure.analyzer import DocumentSegmenter
from src.document_structure.bookmark_processor import BookmarkProcessor
from src.document_structure.extract_raw_pdf_toc import extract_raw_toc
from src.document_structure.models import TOCEntry
from src.document_structure.page_analysis import PageAnalyzer
from src.document_structure.titles import TitleDetector
from src.document_structure.toc import TOCDetector


logger = logging.getLogger(__name__)


@dataclass
class CandidateSection:
    """
    A document section identified during Stage 1.

    This is only a candidate. It has NOT yet been classified as useful
    or irrelevant for equipment information.

    Attributes
    ----------
    section_id:
        Unique identifier for the section.

    title:
        Section title.

    section_number:
        Optional section number such as "3.2" or "4".

    level:
        Hierarchical level of the section when available.

    start_page:
        First page of the section, using 1-based PDF page numbering.

    end_page:
        Last page of the section, using 1-based PDF page numbering.

    source:
        Method used to identify the section.
        Examples:
            "bookmark"
            "structural:toc"
            "structural:title"
            "structural:..."

    confidence:
        Confidence score provided by the underlying structure detector.
    """

    section_id: str
    title: str
    section_number: str | None
    level: int
    start_page: int
    end_page: int
    source: str
    confidence: float



# Bookmark path
def _resolve_bookmark_ranges(
    entries: list[TOCEntry],
    total_pages: int,
) -> list[CandidateSection]:
    """
    Convert bookmark TOC entries into page ranges.

    A bookmark gives us a starting page.

    The end of a section is therefore:

        next section start page - 1

    For the last section:

        end of document
    """

    usable_entries = [
        entry
        for entry in entries
        if entry.source_page is not None
        and entry.source_page >= 1
    ]

    candidates: list[CandidateSection] = []

    for index, entry in enumerate(usable_entries):

        start_page = entry.source_page

        if index + 1 < len(usable_entries):
            end_page = usable_entries[index + 1].source_page - 1
        else:
            end_page = total_pages

        if end_page < start_page:
            end_page = start_page

        candidates.append(
            CandidateSection(
                section_id=f"bm_{index}",
                title=entry.text,
                section_number=entry.section_number,
                level=entry.level,
                start_page=start_page,
                end_page=end_page,
                source="bookmark",
                confidence=entry.confidence,
            )
        )

    return candidates


def build_from_bookmarks(
    raw_toc: dict[str, Any],
) -> list[CandidateSection]:
    """
    Build candidate sections from native PDF bookmarks.

    BookmarkProcessor contains the actual bookmark-cleaning logic.

    We deliberately keep that logic inside BookmarkProcessor rather than
    duplicating it here.
    """

    processor = BookmarkProcessor()

    # 1. Clean and restructure the raw bookmark hierarchy
    clean_data = processor.build_clean_structure(raw_toc)

    # 2. Flatten the cleaned hierarchy
    clean_sections = (
        processor.clean_structure_to_bookmark_sections(
            clean_data
        )
    )

    # 3. Convert to the common TOCEntry representation
    entries = processor.bookmark_sections_to_entries(
        clean_sections
    )

    # 4. Convert bookmark entries into page ranges
    candidates = _resolve_bookmark_ranges(
        entries,
        raw_toc["total_pages"],
    )

    logger.info(
        "Bookmark path produced %d candidate sections",
        len(candidates),
    )

    return candidates


def build_from_structure(
    pdf_path: str | Path,
) -> list[CandidateSection]:
    """
    Build candidate sections when no usable native bookmarks exist.

    The structural pipeline is:

        PDF
         ↓
        PageAnalyzer
         ↓
        TitleDetector
         ↓
        TOCDetector
         ↓
        DocumentSegmenter
         ↓
        CandidateSection
    """

    pdf_path = Path(pdf_path)

    logger.info(
        "Running structural document analysis on %s",
        pdf_path,
    )

    # 1. Extract page-level information
    doc = fitz.open(str(pdf_path))

    try:
        total_pages = len(doc)

        logger.info(
            "Analyzing %d pages using PageAnalyzer",
            total_pages,
        )

        pages = PageAnalyzer().extract_document(doc)

    finally:
        doc.close()

    # 2. Detect title candidates
    logger.info("Detecting title candidates")

    title_detector = TitleDetector()

    title_candidates = {
        page.page_number: title_detector.detect(page)
        for page in pages
    }

    # 3. Detect printed / structural TOC pages
    logger.info("Analyzing pages for printed Table of Contents")

    toc_detector = TOCDetector()

    toc_analyses = [
        toc_detector.analyze_page(page)
        for page in pages
    ]

    # 4. Segment the document
    logger.info("Segmenting document into structural sections")

    segmenter = DocumentSegmenter()

    segments = segmenter.segment(
        pages=pages,
        toc_analyses=toc_analyses,
        title_candidates=title_candidates,
    )

    # 5. Convert structural segments into our common data model
    candidates: list[CandidateSection] = []

    for index, segment in enumerate(segments):

        title = (
            segment.title
            or f"Pages {segment.start_page}-{segment.end_page}"
        )

        candidates.append(
            CandidateSection(
                section_id=f"seg_{index}",
                title=title,
                section_number=segment.section_number,
                level=1,
                start_page=segment.start_page,
                end_page=segment.end_page,
                source=f"structural:{segment.source}",
                confidence=segment.confidence,
            )
        )

    logger.info(
        "Structural path produced %d candidate sections",
        len(candidates),
    )

    return candidates


def build_candidate_sections(
    pdf_path: str | Path,
) -> tuple[
    list[CandidateSection],
    dict[str, Any],
    str,
]:
    """
    Run Stage 1 and automatically select the appropriate structure path.

    Decision logic
    --------------

        PDF
         │
         ▼
        extract_raw_toc()
         │
         ├── usable native bookmarks
         │        │
         │        ▼
         │   bookmark path
         │
         └── no usable bookmarks
                  │
                  ▼
             structural path
                  │
                  ├── PageAnalyzer
                  ├── TitleDetector
                  ├── TOCDetector
                  └── DocumentSegmenter

    Parameters
    ----------
    pdf_path:
        Path to the input PDF.

    Returns
    -------
    candidates:
        Candidate sections identified by Stage 1.

    raw_toc:
        Raw bookmark information returned by `extract_raw_toc`.
        Kept for debugging and later inspection.

    path_used:
        Either "bookmark" or "structural".
    """

    pdf_path = Path(pdf_path)

    logger.info(
        "Starting Stage 1 document structure analysis: %s",
        pdf_path,
    )

    # First attempt: native PDF bookmarks
    raw_toc = extract_raw_toc(pdf_path)

    native_bookmarks = raw_toc.get("sections", [])

    if native_bookmarks:

        logger.info(
            "Found %d native bookmark entries",
            len(native_bookmarks),
        )

        candidates = build_from_bookmarks(raw_toc)

        # Bookmarks existed and at least one section has a valid
        # page reference.
        if candidates:

            logger.info(
                "Stage 1 completed using bookmark path"
            )

            return candidates, raw_toc, "bookmark"

        # Bookmarks existed but could not provide usable page ranges.
        logger.warning(
            "Native bookmarks were found, but none had a "
            "resolvable page number."
        )

    # Fallback: structural document analysis
    logger.info(
        "Falling back to structural document analysis"
    )

    candidates = build_from_structure(pdf_path)

    logger.info(
        "Stage 1 completed using structural path"
    )

    return candidates, raw_toc, "structural"


def run_stage_1(
    pdf_path: str | Path,
) -> dict[str, Any]:
    """
    Convenience wrapper around `build_candidate_sections()`.

    This returns a serializable dictionary that can be passed to
    later pipeline stages or returned by an API.

    Example
    -------
    result = run_stage_1("manual.pdf")

    result["path_used"]
    result["sections"]
    """

    candidates, raw_toc, path_used = build_candidate_sections(
        pdf_path
    )

    return {
        "path_used": path_used,
        "total_candidates": len(candidates),
        "sections": [
            {
                "section_id": section.section_id,
                "title": section.title,
                "section_number": section.section_number,
                "level": section.level,
                "start_page": section.start_page,
                "end_page": section.end_page,
                "source": section.source,
                "confidence": section.confidence,
            }
            for section in candidates
        ],
        "raw_toc": raw_toc,
    }
