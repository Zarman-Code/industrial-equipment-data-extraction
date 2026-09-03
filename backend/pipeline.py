"""
Global PDF processing pipeline.

Flow:

    PDF
      ↓
    Stage 1: document structure
      ↓
    CandidateSection[]
      ↓
    Stage 2: LLM section classification
      ↓
    selected section IDs
      ↓
    Stage 3: text/table/OCR extraction + LLM extraction
      ↓
    Final structured result
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .stage1_document_structure import CandidateSection, build_candidate_sections
from .stage2_section_classification import classify_candidate_sections
from .stage3_information_extraction import run_stage_3


logger = logging.getLogger(__name__)


def _candidate_to_dict(section: CandidateSection) -> dict[str, Any]:
    """
    Convert a CandidateSection dataclass into the dictionary format
    expected by Stage 3 / API responses.
    """

    return {
        "section_id": section.section_id,
        "title": section.title,
        "section_number": section.section_number,
        "level": section.level,
        "start_page": section.start_page,
        "end_page": section.end_page,
        "source": section.source,
        "confidence": section.confidence,
    }


def _serialize_pydantic(model: Any) -> Any:
    """
    Convert a Pydantic model to a normal dictionary.

    Supports both Pydantic v2 and v1.
    """

    if model is None:
        return None

    if hasattr(model, "model_dump"):
        return model.model_dump()

    if hasattr(model, "dict"):
        return model.dict()

    return model


def _select_sections(
    candidates: list[CandidateSection],
    selected_ids: list[str],
) -> tuple[list[CandidateSection], list[str]]:
    """
    Map Stage 2's selected section IDs back to the original
    CandidateSection objects from Stage 1.

    Selection is ID-based, not title/position-based.
    """

    candidates_by_id = {
        candidate.section_id: candidate
        for candidate in candidates
    }

    selected_sections: list[CandidateSection] = []
    unknown_ids: list[str] = []

    for section_id in selected_ids:
        candidate = candidates_by_id.get(section_id)

        if candidate is None:
            unknown_ids.append(section_id)
            continue

        selected_sections.append(candidate)

    return selected_sections, unknown_ids


def run_pipeline(
    pdf_path: str | Path,
    ocr_pipeline=None,
    max_workers: int = 4,
    dpi: int = 300,
    min_text_length: int = 50,
) -> dict[str, Any]:
    """
    Run the complete PDF → equipment information pipeline.

    Parameters
    ----------
    pdf_path:
        Path to the uploaded PDF.

    ocr_pipeline:
        Existing OCR pipeline instance used by Stage 3 when native
        PDF text is insufficient.

    max_workers:
        Maximum number of sections processed concurrently in Stage 3.

    dpi:
        OCR resolution.

    min_text_length:
        Minimum native text length before OCR fallback is considered.

    Returns
    -------
    dict
        Complete pipeline result containing the output of all three stages.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF file does not exist: {pdf_path}"
        )

    if not pdf_path.is_file():
        raise ValueError(
            f"PDF path is not a file: {pdf_path}"
        )

    logger.info("Starting PDF pipeline: %s", pdf_path)

    # ============================================================
    # STAGE 1 — DOCUMENT STRUCTURE
    # ============================================================

    logger.info("Stage 1 started")

    candidates, raw_toc, structure_path = build_candidate_sections(
        pdf_path
    )

    logger.info(
        "Stage 1 completed: %d candidate sections using %s path",
        len(candidates),
        structure_path,
    )

    stage_1_result = {
        "path": structure_path,
        "total_candidates": len(candidates),
        "candidates": [
            _candidate_to_dict(candidate)
            for candidate in candidates
        ],
        "raw_toc": raw_toc,
    }

    # Nothing to classify.
    if not candidates:
        logger.warning(
            "Stage 1 produced no candidate sections. "
            "Skipping Stage 2 and Stage 3."
        )

        return {
            "pdf_path": str(pdf_path),
            "stage_1": stage_1_result,
            "stage_2": {
                "total_candidates": 0,
                "classification": None,
                "selected_section_ids": [],
                "selected_sections": [],
            },
            "stage_3": {
                "stage": 3,
                "total_sections": 0,
                "results": [],
            },
        }

    # ============================================================
    # STAGE 2 — LLM SECTION CLASSIFICATION
    # ============================================================

    logger.info("Stage 2 started")

    classification = classify_candidate_sections(candidates)

    if classification is None:
        logger.warning(
            "Stage 2 returned no classification. "
            "Skipping Stage 3."
        )

        return {
            "pdf_path": str(pdf_path),
            "stage_1": stage_1_result,
            "stage_2": {
                "total_candidates": len(candidates),
                "classification": None,
                "selected_section_ids": [],
                "selected_sections": [],
            },
            "stage_3": {
                "stage": 3,
                "total_sections": 0,
                "results": [],
            },
        }

    selected_ids = list(
        classification.selected_sections
    )

    useful_sections, unknown_ids = _select_sections(
        candidates=candidates,
        selected_ids=selected_ids,
    )

    if unknown_ids:
        logger.warning(
            "Stage 2 returned unknown section IDs: %s",
            unknown_ids,
        )

    logger.info(
        "Stage 2 completed: %d/%d sections selected",
        len(useful_sections),
        len(candidates),
    )

    stage_2_result = {
        "total_candidates": len(candidates),
        "classification": _serialize_pydantic(
            classification
        ),
        "selected_section_ids": selected_ids,
        "selected_sections": [
            _candidate_to_dict(section)
            for section in useful_sections
        ],
        "unknown_section_ids": unknown_ids,
    }

    # Nothing useful was selected.
    if not useful_sections:
        logger.info(
            "Stage 2 selected no useful sections. "
            "Skipping Stage 3."
        )

        return {
            "pdf_path": str(pdf_path),
            "stage_1": stage_1_result,
            "stage_2": stage_2_result,
            "stage_3": {
                "stage": 3,
                "total_sections": 0,
                "results": [],
            },
        }

    # ============================================================
    # STAGE 3 — INFORMATION EXTRACTION
    # ============================================================

    logger.info("Stage 3 started")

    stage_3_result = run_stage_3(
        pdf_path=pdf_path,
        useful_sections=[_candidate_to_dict(s) for s in useful_sections],
        ocr_pipeline=ocr_pipeline,
        max_workers=max_workers,
        dpi=dpi,
        min_text_length=min_text_length,
    )

    logger.info(
        "Stage 3 completed: %d sections processed",
        len(useful_sections),
    )

    # ============================================================
    # FINAL RESULT
    # ============================================================

    return {
        "pdf_path": str(pdf_path),
        "stage_1": stage_1_result,
        "stage_2": stage_2_result,
        "stage_3": stage_3_result,
    }
