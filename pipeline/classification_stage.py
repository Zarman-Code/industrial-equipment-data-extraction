"""
Stage 1b: LLM #1 - relevance classification of candidate sections.

Thin wrapper around `src.llm.classifier.classify_sections`, which expects
a single JSON payload shaped exactly like
`BookmarkProcessor.region_entries_to_payload()`'s output:

    [{"section_id", "title", "section_number", "page_start", "level"}, ...]

The classifier is asked to score EVERY candidate section in one request,
the same way `BookmarkProcessor.process()` / the notebooks do (they build
one single "region" containing the whole bookmark tree). For a PDF with a
very large table of contents this means one large request - use
`--max-sections` on the CLI to cap it while testing.

Importing this module imports `src.llm.classifier`, which raises at
import time if `OPENAI_API_KEY` is not configured (see `src/llm/config.py`).
`pipeline.run_pipeline` therefore only imports this module lazily, once a
`--dry-run` has been ruled out.
"""
from __future__ import annotations

import logging
from typing import Any

from src.llm.classifier import classify_sections
from src.llm.schemas import SectionClassificationResult

from .toc_stage import CandidateSection

logger = logging.getLogger("pipeline.classification_stage")


def build_payload(candidates: list[CandidateSection]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": candidate.section_id,
            "title": candidate.title,
            "section_number": candidate.section_number,
            "page_start": str(candidate.start_page),
            "level": candidate.level,
        }
        for candidate in candidates
    ]


def classify(
    candidates: list[CandidateSection],
) -> tuple[SectionClassificationResult | None, set[str]]:
    """Call LLM #1 once over every candidate section.

    Returns the raw `SectionClassificationResult` (so callers can inspect
    relevance_score/reason per section) together with the set of selected
    section_ids. Returns (None, empty set) if there are no candidates.
    """

    if not candidates:
        return None, set()

    payload = build_payload(candidates)

    logger.info(
        "Calling LLM #1 (classify_sections) on %d candidate sections",
        len(payload),
    )

    result = classify_sections(payload)
    selected = set(result.selected_sections)

    logger.info(
        "LLM #1 selected %d/%d sections (relevance_score >= 50)",
        len(selected),
        len(candidates),
    )

    return result, selected
