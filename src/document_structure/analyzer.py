from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .models import PageRepresentation, TOCAnalysis
from .titles import TitleCandidate


logger = logging.getLogger(
    "document_structure.segmentation"
)


@dataclass
class DocumentSegment:
    """
    A logical section/document contained within the PDF.
    """

    start_page: int
    end_page: int

    title: str | None = None
    section_number: str | None = None

    source: str = "title"

    confidence: float = 0.0

    evidence: list[str] = field(
        default_factory=list
    )

    @property
    def page_count(self) -> int:
        return (
            self.end_page
            - self.start_page
            + 1
        )


class DocumentSegmenter:
    """
    Build logical document/section segments from structural evidence.

    Inputs:
        - extracted pages
        - TOC analysis
        - title candidates

    The segmenter does NOT extract text or tables.

    It only decides where logical boundaries are.
    """

    def segment(
        self,
        pages: list[PageRepresentation],
        toc_analyses: list[TOCAnalysis] | None = None,
        title_candidates: dict[
            int,
            list[TitleCandidate],
        ] | None = None,
    ) -> list[DocumentSegment]:

        if not pages:
            return []

        toc_analyses = (
            toc_analyses
            if toc_analyses is not None
            else []
        )

        title_candidates = (
            title_candidates
            if title_candidates is not None
            else {}
        )

        boundaries = self._collect_boundaries(
            pages=pages,
            toc_analyses=toc_analyses,
            title_candidates=title_candidates,
        )

        return self._build_segments(
            pages=pages,
            boundaries=boundaries,
        )

    # ==============================================================
    # BOUNDARY DETECTION
    # ==============================================================

    def _collect_boundaries(
        self,
        pages: list[PageRepresentation],
        toc_analyses: list[TOCAnalysis],
        title_candidates: dict[
            int,
            list[TitleCandidate],
        ],
    ) -> list[tuple[int, str, float, list[str]]]:

        boundaries: list[
            tuple[int, str, float, list[str]]
        ] = []

        toc_boundaries = (
            self._boundaries_from_toc(
                toc_analyses
            )
        )

        boundaries.extend(
            toc_boundaries
        )

        title_boundaries = (
            self._boundaries_from_titles(
                pages=pages,
                title_candidates=title_candidates,
            )
        )

        boundaries.extend(
            title_boundaries
        )

        return self._merge_boundaries(
            boundaries
        )

    # ==============================================================
    # TOC-BASED BOUNDARIES
    # ==============================================================

    def _boundaries_from_toc(
        self,
        toc_analyses: list[TOCAnalysis],
    ) -> list[
        tuple[int, str, float, list[str]]
    ]:

        boundaries: list[
            tuple[int, str, float, list[str]]
        ] = []

        for toc in toc_analyses:

            if not toc.is_toc:
                continue

            for entry in toc.entries:

                if not entry.printed_page_ref:
                    continue

                # Document/drawing reference codes (e.g.
                # "P1-REF-2012-123-030") are not page numbers. Feeding
                # one into _resolve_printed_page would grab the first
                # 1-4 digit run out of the code (e.g. "2012") and
                # silently misuse it as a PDF page number.
                if (
                    getattr(
                        entry,
                        "reference_kind",
                        None,
                    )
                    == "doc_code"
                ):
                    continue

                pdf_page = self._resolve_printed_page(
                    entry.printed_page_ref
                )

                if pdf_page is None:
                    continue

                evidence = [
                    "TOC entry points to page"
                ]

                if entry.section_number:
                    evidence.append(
                        "TOC contains section number"
                    )

                boundaries.append(
                    (
                        pdf_page,
                        entry.text,
                        0.90,
                        evidence,
                    )
                )

        return boundaries

    @staticmethod
    def _resolve_printed_page(
        page_reference: str,
    ) -> int | None:

        """
        Convert a printed-page reference to an integer.

        This is intentionally conservative.

        We do NOT yet attempt to solve:
            PDF page 15 = printed page 3
        or:
            Roman numeral front matter
        or:
            page labels.

        Those require a separate page-label mapping layer.
        """

        import re

        match = re.search(
            r"\d{1,4}",
            str(page_reference),
        )

        if not match:
            return None

        return int(
            match.group(0)
        )

    # ==============================================================
    # TITLE-BASED BOUNDARIES
    # ==============================================================

    def _boundaries_from_titles(
        self,
        pages: list[PageRepresentation],
        title_candidates: dict[
            int,
            list[TitleCandidate],
        ],
    ) -> list[
        tuple[int, str, float, list[str]]
    ]:

        boundaries: list[
            tuple[int, str, float, list[str]]
        ] = []

        for page in pages:

            candidates = title_candidates.get(
                page.page_number,
                [],
            )

            if not candidates:
                continue

            candidate = self._select_title(
                candidates
            )

            if candidate is None:
                continue

            evidence = [
                "page title candidate"
            ]

            if candidate.is_bold:
                evidence.append(
                    "bold typography"
                )

            if candidate.font_size is not None:
                evidence.append(
                    "title font information"
                )

            if candidate.reasons:
                evidence.extend(
                    candidate.reasons
                )

            boundaries.append(
                (
                    page.page_number,
                    candidate.text,
                    candidate.confidence,
                    evidence,
                )
            )

        return boundaries

    @staticmethod
    def _select_title(
        candidates: list[TitleCandidate],
    ) -> TitleCandidate | None:

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda candidate: (
                candidate.confidence,
                candidate.font_size or 0,
            ),
        )

    # ==============================================================
    # BOUNDARY MERGING
    # ==============================================================

    def _merge_boundaries(
        self,
        boundaries: list[
            tuple[int, str, float, list[str]]
        ],
    ) -> list[
        tuple[int, str, float, list[str]]
    ]:

        if not boundaries:
            return []

        boundaries.sort(
            key=lambda item: item[0]
        )

        merged: list[
            tuple[int, str, float, list[str]]
        ] = []

        for boundary in boundaries:

            page, title, confidence, evidence = (
                boundary
            )

            if not merged:

                merged.append(boundary)
                continue

            previous = merged[-1]

            if page != previous[0]:

                merged.append(boundary)
                continue

            # Same page: combine evidence.
            previous_page = previous[0]

            previous_title = previous[1]

            previous_confidence = max(
                previous[2],
                confidence,
            )

            previous_evidence = list(
                previous[3]
            )

            for item in evidence:
                if item not in previous_evidence:
                    previous_evidence.append(
                        item
                    )

            # Prefer the richer title.
            selected_title = self._choose_title(
                previous_title,
                title,
            )

            merged[-1] = (
                previous_page,
                selected_title,
                previous_confidence,
                previous_evidence,
            )

        return merged

    @staticmethod
    def _choose_title(
        first: str | None,
        second: str | None,
    ) -> str | None:

        if not first:
            return second

        if not second:
            return first

        if len(second) > len(first):
            return second

        return first

    # ==============================================================
    # SEGMENT CONSTRUCTION
    # ==============================================================

    def _build_segments(
        self,
        pages: list[PageRepresentation],
        boundaries: list[
            tuple[int, str, float, list[str]]
        ],
    ) -> list[DocumentSegment]:

        if not pages:
            return []

        if not boundaries:

            return [
                DocumentSegment(
                    start_page=pages[0].page_number,
                    end_page=pages[-1].page_number,
                    title=None,
                    source="fallback",
                    confidence=0.10,
                    evidence=[
                        "no structural boundaries detected"
                    ],
                )
            ]

        segments: list[DocumentSegment] = []

        # If the first detected boundary occurs after page 1,
        # preserve the preceding material as a segment.
        first_boundary_page = boundaries[0][0]

        if first_boundary_page > pages[0].page_number:

            segments.append(
                DocumentSegment(
                    start_page=pages[0].page_number,
                    end_page=first_boundary_page - 1,
                    title=None,
                    source="preceding_material",
                    confidence=0.30,
                    evidence=[
                        "pages before first detected boundary"
                    ],
                )
            )

        for index, boundary in enumerate(
            boundaries
        ):

            start_page, title, confidence, evidence = (
                boundary
            )

            if index + 1 < len(boundaries):

                next_start = boundaries[
                    index + 1
                ][0]

                end_page = next_start - 1

            else:

                end_page = pages[-1].page_number

            if end_page < start_page:
                continue

            source = self._infer_source(
                evidence
            )

            segments.append(
                DocumentSegment(
                    start_page=start_page,
                    end_page=end_page,
                    title=title,
                    source=source,
                    confidence=confidence,
                    evidence=evidence,
                )
            )

        return segments

    @staticmethod
    def _infer_source(
        evidence: list[str],
    ) -> str:

        if "TOC entry points to page" in evidence:
            return "toc"

        if "page title candidate" in evidence:
            return "title"

        return "unknown"