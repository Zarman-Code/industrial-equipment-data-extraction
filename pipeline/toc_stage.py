"""
Stage 1: build a candidate list of sections (title, start_page, end_page)
from a raw PDF, without calling any LLM.

Two paths, chosen automatically depending on the PDF:

- BOOKMARK PATH - the PDF has a native outline/bookmarks
  (`extract_raw_toc` returns at least one entry). We reuse
  `BookmarkProcessor` to clean and flatten the bookmark hierarchy exactly
  the way `notebook/06_bookmark_llm1_pipeline.ipynb` does, then turn every
  entry with a resolvable page number into a candidate section by pairing
  its start page with the next entry's start page (or the end of the
  document).

- STRUCTURAL PATH - no native bookmarks. We fall back to the
  `document_structure` structural pipeline:
  `PageAnalyzer` (per-page extraction) -> `TitleDetector` (title
  candidates) -> `TOCDetector` (printed/OCR-independent TOC detection) ->
  `DocumentSegmenter` (structural segmentation, already returns segments
  with resolved start/end pages).

Nothing here calls an LLM; this module only prepares the material later
sent to `src.llm.classifier.classify_sections` (LLM #1) by
`pipeline.classification_stage`.
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

logger = logging.getLogger("pipeline.toc_stage")


@dataclass
class CandidateSection:
    """One candidate section, before LLM #1 relevance filtering."""

    section_id: str
    title: str
    section_number: str | None
    level: int
    start_page: int
    end_page: int
    source: str  # "bookmark" or "structural:<DocumentSegment.source>"
    confidence: float


def _resolve_ranges_from_bookmark_entries(
    entries: list[TOCEntry],
    total_pages: int,
) -> list[CandidateSection]:
    """Pair each bookmark entry with an end_page.

    `BookmarkProcessor` only carries a single reference page per entry
    (`source_page`), not a range, so the end page is derived here: the
    page right before the NEXT entry with a resolvable page (regardless of
    whether that next entry ends up selected by LLM #1), or the end of the
    document for the last entry. Entries whose page could not be resolved
    (source_page is None or -1, e.g. a bilingual/duplicate title dropped
    upstream) are skipped - they cannot anchor a page range.
    """

    usable = [
        entry
        for entry in entries
        if entry.source_page is not None and entry.source_page >= 1
    ]

    candidates: list[CandidateSection] = []

    for position, entry in enumerate(usable):
        start_page = entry.source_page

        if position + 1 < len(usable):
            end_page = usable[position + 1].source_page - 1
        else:
            end_page = total_pages

        if end_page < start_page:
            end_page = start_page

        candidates.append(
            CandidateSection(
                section_id=f"bm_{position}",
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
    """Build candidate sections from an already-extracted native bookmark
    TOC (see `extract_raw_toc`)."""

    processor = BookmarkProcessor()
    clean_data = processor.build_clean_structure(raw_toc)
    clean_sections = processor.clean_structure_to_bookmark_sections(clean_data)
    entries = processor.bookmark_sections_to_entries(clean_sections)

    return _resolve_ranges_from_bookmark_entries(entries, raw_toc["total_pages"])


def build_from_structure(pdf_path: str | Path) -> list[CandidateSection]:
    """Build candidate sections using the structural pipeline, for PDFs
    with no usable native bookmarks."""

    doc = fitz.open(str(pdf_path))
    try:
        total_pages = len(doc)
        logger.info(
            "No usable native bookmarks - running structural analysis on %d pages",
            total_pages,
        )
        pages = PageAnalyzer().extract_document(doc)
    finally:
        doc.close()

    title_detector = TitleDetector()
    title_candidates = {
        page.page_number: title_detector.detect(page) for page in pages
    }

    toc_detector = TOCDetector()
    toc_analyses = [toc_detector.analyze_page(page) for page in pages]

    segments = DocumentSegmenter().segment(
        pages=pages,
        toc_analyses=toc_analyses,
        title_candidates=title_candidates,
    )

    return [
        CandidateSection(
            section_id=f"seg_{idx}",
            title=segment.title or f"Pages {segment.start_page}-{segment.end_page}",
            section_number=segment.section_number,
            level=1,
            start_page=segment.start_page,
            end_page=segment.end_page,
            source=f"structural:{segment.source}",
            confidence=segment.confidence,
        )
        for idx, segment in enumerate(segments)
    ]


def build_candidate_sections(
    pdf_path: str | Path,
) -> tuple[list[CandidateSection], dict[str, Any], str]:
    """Entry point for Stage 1: pick the bookmark or structural path
    automatically.

    Returns (candidates, raw_toc_info, path_used) where `raw_toc_info` is
    the dict returned by `extract_raw_toc` (saved as-is for debugging) and
    `path_used` is "bookmark" or "structural".
    """

    raw_toc = extract_raw_toc(pdf_path)

    if raw_toc["sections"]:
        logger.info(
            "Found %d native bookmark entries - using the bookmark path",
            len(raw_toc["sections"]),
        )
        candidates = build_from_bookmarks(raw_toc)

        if candidates:
            return candidates, raw_toc, "bookmark"

        logger.warning(
            "Native bookmarks were present but none had a resolvable page "
            "number - falling back to the structural path"
        )

    candidates = build_from_structure(pdf_path)
    return candidates, raw_toc, "structural"
