"""
Small persistence helpers for the pipeline:

- writing the resolved-sections CSV that
  `src.information_extraction.load_sections` reads (`title;page_start;page_end`,
  semicolon-separated - same convention as the existing
  `data/processed/resolved_sections.csv`);
- writing a human-readable candidate-sections CSV for Stage 1 review;
- turning Stage 2's raw per-section results into a flat, spreadsheet-friendly
  CSV of extracted equipment fields.

Nothing here touches any existing file under `data/` or `results/`; every
path used by `pipeline.run_pipeline` is namespaced under
`results/<pdf_stem>/`.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .toc_stage import CandidateSection

# The 7 i-Sense-relevant fields defined in src/llm/schemas.py::LLMExtraction
# / src/llm/prompts.py::LLM_INSTRUCTIONS.
EQUIPMENT_FIELDS = (
    "family",
    "asset_name",
    "reference",
    "power",
    "outlier",
    "manufacturer",
    "asset_diagram",
)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)


def write_candidate_sections_csv(
    candidates: list[CandidateSection],
    path: Path,
) -> None:
    """Full Stage 1 output (every candidate, before LLM #1 filtering) -
    useful to sanity-check TOC detection / segmentation on its own."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            [
                "section_id",
                "title",
                "section_number",
                "level",
                "page_start",
                "page_end",
                "source",
                "confidence",
            ]
        )
        for candidate in candidates:
            writer.writerow(
                [
                    candidate.section_id,
                    candidate.title,
                    candidate.section_number or "",
                    candidate.level,
                    candidate.start_page,
                    candidate.end_page,
                    candidate.source,
                    f"{candidate.confidence:.2f}",
                ]
            )


def write_resolved_sections_csv(
    candidates: list[CandidateSection],
    path: Path,
) -> None:
    """Write the CSV consumed by `src.information_extraction.load_sections`
    (requires at least `title`, `page_start`, `page_end` columns,
    semicolon-separated)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["section_id", "title", "page_start", "page_end", "source"])
        for candidate in candidates:
            writer.writerow(
                [
                    candidate.section_id,
                    candidate.title,
                    candidate.start_page,
                    candidate.end_page,
                    candidate.source,
                ]
            )


def write_extraction_summary_csv(results: Iterable[dict], path: Path) -> None:
    """Mirrors the `results_df` built in
    `notebook/06_llm_section_extraction.ipynb.ipynb` (success/error per
    section)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["title", "start_page", "end_page", "success", "error"])
        for result in results:
            writer.writerow(
                [
                    result.get("title"),
                    result.get("start_page"),
                    result.get("end_page"),
                    result.get("error") is None,
                    result.get("error") or "",
                ]
            )


def flatten_equipment_csv(results: Iterable[dict], path: Path) -> None:
    """Flatten Stage 2's per-section LLM #2 result (see
    `src.llm.schemas.LLMExtraction`) into one row per section, with each
    of the 7 equipment fields split into its `_value` / `_confidence` /
    `_page` columns - the most directly usable deliverable of the
    pipeline."""

    path.parent.mkdir(parents=True, exist_ok=True)

    header = ["title", "start_page", "end_page"]
    for field in EQUIPMENT_FIELDS:
        header.extend([f"{field}_value", f"{field}_confidence", f"{field}_page"])
    header.append("error")

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(header)

        for result in results:
            llm_result = result.get("llm_result") or {}
            extracted = (
                llm_result.get("result") if isinstance(llm_result, dict) else None
            )

            row: list[Any] = [
                result.get("title"),
                result.get("start_page"),
                result.get("end_page"),
            ]

            for field in EQUIPMENT_FIELDS:
                field_data = (extracted or {}).get(field) or {}
                row.extend(
                    [
                        field_data.get("value"),
                        field_data.get("confidence"),
                        field_data.get("page"),
                    ]
                )

            row.append(result.get("error") or "")

            writer.writerow(row)
