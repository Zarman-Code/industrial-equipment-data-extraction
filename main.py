#!/usr/bin/env python
"""
Global entry point: raw PDF -> LLM extraction.

This script does not change anything inside `src/`. It only *orchestrates*
the building blocks that already exist there (document_structure, llm, ocr,
information_extraction) into one end-to-end command, the way the notebooks
under `notebook/` currently do by hand, one cell at a time.

Pipeline
--------

Stage 1 - Table of contents / segmentation (no LLM call)
    raw PDF
      -> src.document_structure.extract_raw_pdf_toc.extract_raw_toc()
         (native PDF bookmarks, when present)
      -> src.document_structure.bookmark_processor.BookmarkProcessor
         (clean + flatten the bookmark hierarchy)
         ... or, when the PDF has no native bookmarks ...
      -> src.document_structure.page_analysis.PageAnalyzer      (per page)
      -> src.document_structure.titles.TitleDetector            (titles)
      -> src.document_structure.toc.TOCDetector                 (TOC pages)
      -> src.document_structure.analyzer.DocumentSegmenter      (segments)
    -> a list of candidate sections {title, start_page, end_page}

Stage 1b - LLM #1: section relevance classification
    candidate sections
      -> src.llm.classifier.classify_sections()
    -> only the sections the model marked relevant are kept

Stage 2 - LLM #2: per-section content + equipment extraction
    selected sections
      -> src.information_extraction.process_sections_parallel()
         (native text/tables, src.ocr PaddleOCR fallback,
          src.llm.extractor.extract_with_llm)
    -> results/<pdf_stem>/extracted_sections.json (+ CSV summaries)

Usage
-----

    python main.py --pdf data/raw/AUSTCOLD.pdf
    python main.py --pdf "data/raw/MYCOM Operating and Maintenance Manual Refrigeration Unit (1).pdf" \\
        --max-workers 4 --dpi 300

    # Inspect the detected sections without spending any LLM call:
    python main.py --pdf data/raw/AUSTCOLD.pdf --dry-run

    # Review LLM #1's picks before paying for LLM #2 on every section:
    python main.py --pdf data/raw/AUSTCOLD.pdf --skip-extraction

See pipeline/README.md for the full option list and output layout.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.run_pipeline import run_pipeline  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the raw-PDF -> LLM-extraction pipeline end to end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to the source PDF (e.g. data/raw/AUSTCOLD.pdf).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to write pipeline outputs. Defaults to results/<pdf_stem>/.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Parallel section workers for Stage 2 (default: 4).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI used when the OCR fallback is triggered (default: 300).",
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=50,
        help="Minimum native text length considered sufficient before "
        "falling back to OCR (default: 50).",
    )
    parser.add_argument(
        "--relevance-threshold",
        type=int,
        default=50,
        help="Extra client-side cutoff (0-100) applied on top of LLM #1's "
        "own relevance_score >= 50 selection. Raising this above 50 only "
        "tightens the selection further; it can never widen it "
        "(default: 50, i.e. no extra filtering).",
    )
    parser.add_argument(
        "--skip-classification",
        action="store_true",
        help="Send every detected section straight to Stage 2, skipping "
        "the LLM #1 relevance filter.",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Stop after Stage 1b (LLM #1). Useful to review which "
        "sections were selected before spending LLM #2 calls on them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after Stage 1. No LLM call is made and the (slow) "
        "PaddleOCR models are never loaded. Only writes "
        "sections_candidates.csv.",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=None,
        help="Debug/cost-control cap: only keep the first N candidate "
        "sections before classification.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        run_pipeline(
            pdf_path=args.pdf,
            output_dir=args.output_dir,
            max_workers=args.max_workers,
            dpi=args.dpi,
            min_text_length=args.min_text_length,
            relevance_threshold=args.relevance_threshold,
            skip_classification=args.skip_classification,
            skip_extraction=args.skip_extraction,
            dry_run=args.dry_run,
            max_sections=args.max_sections,
        )
    except FileNotFoundError as exc:
        logging.getLogger("main").error(str(exc))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
