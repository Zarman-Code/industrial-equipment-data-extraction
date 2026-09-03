"""
Full raw-PDF -> LLM-extraction pipeline, gluing together the stages
implemented across this repository's `src/` package. See `main.py` (repo
root) for the CLI, and `pipeline/README.md` for the full description.

    Stage 1  toc_stage.build_candidate_sections()   src.document_structure.*
    Stage 1b classification_stage.classify()        src.llm.classifier (LLM #1)
    Stage 2  extraction_stage.run()                 src.information_extraction /
                                                     src.ocr / src.llm.extractor
                                                     (LLM #2)

`toc_stage` and `io_utils` are imported eagerly (they only depend on
PyMuPDF / the `document_structure` package, no API key or heavy model
load). `classification_stage` (needs `OPENAI_API_KEY`) and
`extraction_stage` (loads PaddleOCR on first use) are imported lazily,
inside `run_pipeline()`, only once it's clear they're actually needed -
this is what makes `--dry-run` work without any credentials or model
download.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import io_utils, toc_stage

logger = logging.getLogger("pipeline.run_pipeline")


def run_pipeline(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    max_workers: int = 4,
    dpi: int = 300,
    min_text_length: int = 50,
    relevance_threshold: int = 50,
    skip_classification: bool = False,
    skip_extraction: bool = False,
    dry_run: bool = False,
    max_sections: int | None = None,
) -> dict:
    """Run the full pipeline for one PDF and return a summary dict.

    See `main.py --help` for what each parameter controls.
    """

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    project_root = Path(__file__).resolve().parents[1]
    out_dir = Path(output_dir) if output_dir else project_root / "results" / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Stage 1 - candidate sections (no LLM call)
    # ------------------------------------------------------------------
    logger.info("=== Stage 1: building candidate sections from %s ===", pdf_path.name)

    candidates, raw_toc_info, path_used = toc_stage.build_candidate_sections(pdf_path)

    logger.info(
        "Stage 1 done (%s path): %d candidate sections",
        path_used,
        len(candidates),
    )

    io_utils.write_json(raw_toc_info, out_dir / "toc_raw.json")
    io_utils.write_candidate_sections_csv(candidates, out_dir / "sections_candidates.csv")

    if max_sections is not None:
        candidates = candidates[:max_sections]
        logger.info(
            "--max-sections applied: keeping the first %d candidate sections",
            len(candidates),
        )

    if dry_run:
        logger.info(
            "--dry-run: stopping after Stage 1 (no LLM call made, no OCR "
            "models loaded). See %s",
            out_dir / "sections_candidates.csv",
        )
        return {
            "output_dir": str(out_dir),
            "path_used": path_used,
            "candidates": candidates,
        }

    if not candidates:
        logger.warning("No candidate sections found - nothing to send to the LLM. Stopping.")
        return {
            "output_dir": str(out_dir),
            "path_used": path_used,
            "candidates": candidates,
        }

    # ------------------------------------------------------------------
    # Stage 1b - LLM #1 relevance classification
    # ------------------------------------------------------------------
    classification_result = None

    if skip_classification:
        logger.info(
            "--skip-classification: sending all %d candidate sections straight "
            "to Stage 2",
            len(candidates),
        )
        selected_candidates = candidates
    else:
        logger.info("=== Stage 1b: LLM #1 relevance classification ===")

        from . import classification_stage  # lazy: requires OPENAI_API_KEY

        classification_result, selected_ids = classification_stage.classify(candidates)

        if classification_result is not None:
            io_utils.write_json(
                classification_result.model_dump(),
                out_dir / "sections_classification.json",
            )

        selected_candidates = [c for c in candidates if c.section_id in selected_ids]

        # Belt-and-braces client-side cutoff on top of `selected_sections`
        # (the prompt itself already restricts that to relevance_score >= 50).
        # Raising --relevance-threshold above 50 only tightens the
        # selection further; it can never widen it.
        if classification_result is not None and relevance_threshold > 50:
            scores = {s.section_id: s.relevance_score for s in classification_result.sections}
            selected_candidates = [
                c for c in selected_candidates if scores.get(c.section_id, 0) >= relevance_threshold
            ]

        logger.info(
            "Stage 1b done: %d/%d sections kept for extraction",
            len(selected_candidates),
            len(candidates),
        )

    resolved_csv_path = out_dir / "resolved_sections.csv"
    io_utils.write_resolved_sections_csv(selected_candidates, resolved_csv_path)

    if not selected_candidates:
        logger.warning("No sections were selected for extraction - stopping before Stage 2.")
        return {
            "output_dir": str(out_dir),
            "path_used": path_used,
            "candidates": candidates,
            "selected_candidates": selected_candidates,
        }

    if skip_extraction:
        logger.info(
            "--skip-extraction: stopping before Stage 2. Resolved sections: %s",
            resolved_csv_path,
        )
        return {
            "output_dir": str(out_dir),
            "path_used": path_used,
            "candidates": candidates,
            "selected_candidates": selected_candidates,
        }

    # ------------------------------------------------------------------
    # Stage 2 - section content extraction + LLM #2
    # ------------------------------------------------------------------
    logger.info("=== Stage 2: section content extraction + LLM #2 ===")

    from . import extraction_stage  # lazy: loads PaddleOCR models on first use

    results = extraction_stage.run(
        pdf_path=pdf_path,
        resolved_csv_path=resolved_csv_path,
        max_workers=max_workers,
        dpi=dpi,
        min_text_length=min_text_length,
    )

    io_utils.write_json(results, out_dir / "extracted_sections.json")
    io_utils.write_extraction_summary_csv(results, out_dir / "extracted_sections_summary.csv")
    io_utils.flatten_equipment_csv(results, out_dir / "equipment_extraction.csv")

    succeeded = sum(1 for r in results if r.get("error") is None)
    logger.info(
        "=== Pipeline complete: %d/%d sections extracted successfully ===",
        succeeded,
        len(results),
    )
    logger.info("Outputs written to %s", out_dir)

    return {
        "output_dir": str(out_dir),
        "path_used": path_used,
        "candidates": candidates,
        "selected_candidates": selected_candidates,
        "results": results,
    }
