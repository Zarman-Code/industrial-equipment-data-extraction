"""
Stage 2: section content extraction + LLM #2 equipment extraction.

Thin wrapper around `src.information_extraction.process_sections_parallel`,
which already implements, per section, in parallel:

    native text/table extraction (PyMuPDF/pdfplumber)
      -> PaddleOCR fallback (src.ocr.ocr_pipeline) when native text is
         insufficient
      -> src.llm.extractor.extract_with_llm  (LLM #2)

Importing `src.information_extraction` loads the PaddleOCR models,
because `src.ocr.ocr_pipeline.ocr_pipeline` is a module-level singleton
instantiated at import time. That import is deferred to `run()` (rather
than done at module load) so that Stage 1 / Stage 1b can be exercised via
`--dry-run` or `--skip-extraction` without paying that cost.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("pipeline.extraction_stage")


def run(
    pdf_path: str | Path,
    resolved_csv_path: str | Path,
    max_workers: int = 4,
    dpi: int = 300,
    min_text_length: int = 50,
) -> list[dict]:
    """Run Stage 2 over every section listed in `resolved_csv_path`.

    `resolved_csv_path` must be a ";"-separated CSV with at least
    `title`, `page_start`, `page_end` columns - see
    `pipeline.io_utils.write_resolved_sections_csv`, which is exactly the
    format `src.information_extraction.load_sections` expects.
    """

    from src.information_extraction import process_sections_parallel

    logger.info(
        "Calling LLM #2 (extract_with_llm) over the resolved sections in %s "
        "(max_workers=%d, dpi=%d, min_text_length=%d)",
        resolved_csv_path,
        max_workers,
        dpi,
        min_text_length,
    )

    return process_sections_parallel(
        pdf_path=pdf_path,
        csv_path=resolved_csv_path,
        max_workers=max_workers,
        dpi=dpi,
        min_text_length=min_text_length,
    )
