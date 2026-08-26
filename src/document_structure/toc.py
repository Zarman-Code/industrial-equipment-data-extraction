from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .models import (
    PageRepresentation,
    TableRepresentation,
    TOCAnalysis,
    TOCEntry,
)


# ---------------------------------------------------------------------------
# Semantic hints
# ---------------------------------------------------------------------------
#
# IMPORTANT:
# These are NOT all equivalent.
#
# Explicit TOC terminology is useful evidence.
# "index" is intentionally kept separate because an index is not necessarily
# useful for document segmentation.
#

STRONG_TOC_KEYWORDS: tuple[str, ...] = (
    "table of contents",
    "contents",
    "table des matières",
    "table des matieres",
    "sommaire",
    "inhoudsopgave",
    "inhalt",
    "inhaltsverzeichnis",
    "document contents",
    "instruction index",
    "operating & maintenance instruction index",
    "operating and maintenance instruction index",
)

AMBIGUOUS_STRUCTURE_KEYWORDS: tuple[str, ...] = (
    "index",
    "general index",
    "document index",
    "indice",
    "índice",
    "indis",
)


# ---------------------------------------------------------------------------
# Regular expressions
# ---------------------------------------------------------------------------

DOT_LEADER_RE = re.compile(
    r"^(.+?)(?:\.{2,}|_{2,}|-{2,}|\s{3,})(\d{1,4})\s*$"
)

TRAILING_PAGE_RE = re.compile(
    r"^(.+?)(?:\s+(?:page|p\.|pg\.)?\s*(\d{1,4}))\s*$",
    re.IGNORECASE,
)

PAGE_REFERENCE_RE = re.compile(
    r"^(?:page\s+|p\.\s*|pg\.\s*)?"
    r"\d{1,4}"
    r"(?:\s*[-–]\s*\d{1,4})?$",
    re.IGNORECASE,
)


SECTION_PATTERNS: tuple[
    tuple[str, re.Pattern[str]]
] = (
    (
        "four_level",
        re.compile(
            r"^([A-Z]?\d+[A-Z]?\.\d+\.\d+\.\d+)\s+(.+)$",
            re.DOTALL,
        ),
    ),
    (
        "three_level",
        re.compile(
            r"^([A-Z]?\d+[A-Z]?\.\d+\.\d+)\s+(.+)$",
            re.DOTALL,
        ),
    ),
    (
        "two_level",
        re.compile(
            r"^([A-Z]?\d+[A-Z]?\.\d+)\s+(.+)$",
            re.DOTALL,
        ),
    ),
    (
        "numeric_dot",
        re.compile(
            r"^(\d+)\.\s+(.+)$",
            re.DOTALL,
        ),
    ),
    (
        "numeric_paren",
        re.compile(
            r"^(\d+)\)\s+(.+)$",
            re.DOTALL,
        ),
    ),
    (
        "alpha_dot_paren",
        re.compile(
            r"^([A-Z])[.)]\s+(.+)$",
            re.DOTALL,
        ),
    ),
    (
        "roman",
        re.compile(
            r"^([IVXLCDM]+)[.)-]\s+(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@dataclass
class TOCEvidence:
    """
    Structured evidence used to determine whether a page is a TOC.

    The values are intentionally exposed so notebooks can explain the
    classification rather than showing only a final score.
    """

    positive: dict[str, Any] = field(
        default_factory=dict
    )

    negative: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def all_evidence(self) -> dict[str, Any]:
        return {
            "positive": self.positive,
            "negative": self.negative,
        }


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class TOCDetector:
    """
    Detect and parse table-of-contents pages.

    The detector uses multiple evidence families:

        Positive:
            - explicit TOC terminology
            - TOC-like table structure
            - section hierarchy
            - repeated page references
            - dot leaders
            - repeated entry-like rows
            - layout/structural consistency

        Negative:
            - index-like structure
            - ordinary data-table structure
            - prose dominance
            - insufficient entry structure
            - figure/drawing-like content

    IMPORTANT:
    A keyword alone never determines that a page is a TOC.
    """

    def __init__(
        self,
        toc_score_threshold: float = 0.50,
    ) -> None:

        self.toc_score_threshold = (
            toc_score_threshold
        )

    # ======================================================================
    # PUBLIC API
    # ======================================================================

    def analyze_page(
        self,
        page: PageRepresentation,
    ) -> TOCAnalysis:

        evidence = self._collect_evidence(page)

        score = self._calculate_score(
            evidence
        )

        is_toc = (
            score >= self.toc_score_threshold
        )

        entries: list[TOCEntry] = []

        extraction_source: str | None = None

        if is_toc:

            # --------------------------------------------------------------
            # Prefer structured table extraction.
            # --------------------------------------------------------------

            table = (
                self._select_best_toc_table(
                    page.tables
                )
            )

            if table is not None:

                entries = self._parse_table(
                    table,
                    source_page=page.page_number,
                )

                if entries:
                    extraction_source = "table"

            # --------------------------------------------------------------
            # Fall back to text extraction.
            # --------------------------------------------------------------

            if not entries:

                entries = self._parse_text(
                    page.raw_text,
                    source_page=page.page_number,
                )

                if entries:
                    extraction_source = "text"

        return TOCAnalysis(
            page_number=page.page_number,
            is_toc=is_toc,
            confidence=score,
            evidence=evidence.all_evidence,
            entries=entries,
            extraction_source=extraction_source,
        )

    def explain_page(
        self,
        page: PageRepresentation,
    ) -> dict[str, Any]:

        analysis = self.analyze_page(page)

        return {
            "page": page.page_number,
            "is_toc": analysis.is_toc,
            "confidence": round(
                analysis.confidence,
                3,
            ),
            "positive_evidence": (
                analysis.evidence.get(
                    "positive",
                    {},
                )
            ),
            "negative_evidence": (
                analysis.evidence.get(
                    "negative",
                    {},
                )
            ),
            "table_count": len(
                page.tables
            ),
            "text_block_count": len(
                page.text_blocks
            ),
            "extraction_source": (
                analysis.extraction_source
            ),
            "entry_count": len(
                analysis.entries
            ),
        }

    # ======================================================================
    # EVIDENCE COLLECTION
    # ======================================================================

    def _collect_evidence(
        self,
        page: PageRepresentation,
    ) -> TOCEvidence:

        text = page.raw_text or ""

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        normalized_text = self._normalize(
            text
        )

        # ------------------------------------------------------------------
        # Semantic evidence
        # ------------------------------------------------------------------

        strong_keywords = [
            keyword
            for keyword in STRONG_TOC_KEYWORDS
            if self._normalize(keyword)
            in normalized_text
        ]

        ambiguous_keywords = [
            keyword
            for keyword in AMBIGUOUS_STRUCTURE_KEYWORDS
            if self._normalize(keyword)
            in normalized_text
        ]

        # ------------------------------------------------------------------
        # Text structural evidence
        # ------------------------------------------------------------------

        section_matches = [
            line
            for line in lines
            if self._parse_section_number(
                line
            ) is not None
        ]

        page_reference_matches = [
            line
            for line in lines
            if (
                DOT_LEADER_RE.match(line)
                or TRAILING_PAGE_RE.match(line)
            )
        ]

        dot_leader_matches = [
            line
            for line in lines
            if DOT_LEADER_RE.match(line)
        ]

        # ------------------------------------------------------------------
        # Table evidence
        # ------------------------------------------------------------------

        toc_tables = [
            table
            for table in page.tables
            if self._looks_like_toc_table(
                table
            )
        ]

        data_tables = [
            table
            for table in page.tables
            if self._looks_like_data_table(
                table
            )
        ]

        # ------------------------------------------------------------------
        # Index evidence
        # ------------------------------------------------------------------

        index_evidence = (
            self._analyze_index_structure(
                lines
            )
        )

        # ------------------------------------------------------------------
        # Prose evidence
        # ------------------------------------------------------------------

        prose_evidence = (
            self._analyze_prose_structure(
                lines
            )
        )

        # ------------------------------------------------------------------
        # Layout / repetition evidence
        # ------------------------------------------------------------------

        consistency = (
            self._analyze_line_consistency(
                lines
            )
        )

        positive = {
            "strong_toc_keywords": (
                strong_keywords
            ),

            "section_structure": {
                "match_count": len(
                    section_matches
                ),
                "ratio": self._ratio(
                    len(section_matches),
                    len(lines),
                ),
            },

            "page_references": {
                "match_count": len(
                    page_reference_matches
                ),
                "ratio": self._ratio(
                    len(page_reference_matches),
                    len(lines),
                ),
            },

            "dot_leaders": {
                "match_count": len(
                    dot_leader_matches
                ),
                "ratio": self._ratio(
                    len(dot_leader_matches),
                    len(lines),
                ),
            },

            "toc_tables": [
                self._describe_table(table)
                for table in toc_tables
            ],

            "toc_table_count": len(
                toc_tables
            ),

            "entry_like_structure": {
                "line_count": len(lines),
                "short_line_ratio": (
                    self._short_line_ratio(
                        lines
                    )
                ),
            },

            "layout_consistency": consistency,
        }

        negative = {
            "ambiguous_keywords": (
                ambiguous_keywords
            ),

            "index_like_structure": (
                index_evidence
            ),

            "data_table_structure": {
                "data_table_count": len(
                    data_tables
                ),
                "tables": [
                    self._describe_table(
                        table
                    )
                    for table in data_tables
                ],
            },

            "prose_dominance": (
                prose_evidence
            ),

            "insufficient_structure": (
                self._insufficient_structure(
                    lines,
                    section_matches,
                    page_reference_matches,
                    toc_tables,
                )
            ),
        }

        return TOCEvidence(
            positive=positive,
            negative=negative,
        )

    # ======================================================================
    # SCORING
    # ======================================================================

    def _calculate_score(
        self,
        evidence: TOCEvidence,
    ) -> float:

        positive = evidence.positive
        negative = evidence.negative

        score = 0.0

        # ------------------------------------------------------------------
        # Positive evidence
        # ------------------------------------------------------------------

        # Explicit TOC terminology is useful, but NOT decisive.
        if positive["strong_toc_keywords"]:
            score += 0.15

        if positive["toc_table_count"] > 0:
            score += 0.35

        section_ratio = positive[
            "section_structure"
        ]["ratio"]

        if section_ratio >= 0.20:
            score += 0.15
        elif section_ratio >= 0.10:
            score += 0.08

        page_ratio = positive[
            "page_references"
        ]["ratio"]

        if page_ratio >= 0.40:
            score += 0.15
        elif page_ratio >= 0.20:
            score += 0.08

        dot_ratio = positive[
            "dot_leaders"
        ]["ratio"]

        if dot_ratio >= 0.20:
            score += 0.08

        consistency = positive[
            "layout_consistency"
        ]

        if consistency.get(
            "consistent_entry_structure"
        ):
            score += 0.10

        # ------------------------------------------------------------------
        # Negative evidence
        # ------------------------------------------------------------------

        index_score = negative[
            "index_like_structure"
        ].get(
            "score",
            0.0,
        )

        score -= 0.30 * index_score

        data_table_count = negative[
            "data_table_structure"
        ]["data_table_count"]

        # Data tables are not automatically fatal because a page can
        # contain multiple tables, one of which may actually be a TOC.
        if (
            data_table_count > 0
            and positive["toc_table_count"] == 0
        ):
            score -= 0.15

        prose_ratio = negative[
            "prose_dominance"
        ].get(
            "ratio",
            0.0,
        )

        if prose_ratio >= 0.70:
            score -= 0.20
        elif prose_ratio >= 0.50:
            score -= 0.10

        if negative[
            "insufficient_structure"
        ]["is_insufficient"]:
            score -= 0.15

        return max(
            0.0,
            min(score, 1.0),
        )

    # ======================================================================
    # INDEX DETECTION
    # ======================================================================

    def _analyze_index_structure(
        self,
        lines: list[str],
    ) -> dict[str, Any]:

        if not lines:
            return {
                "score": 0.0,
                "alphabetic_entry_ratio": 0.0,
                "comma_page_ratio": 0.0,
                "is_index_like": False,
            }

        alphabetic_entries = 0
        comma_page_entries = 0

        for line in lines:

            normalized = line.strip()

            # Typical index:
            #
            # pump, 12, 18, 25
            # valve, 14, 31
            #
            if re.match(
                r"^[A-Za-z][^,]{1,80},"
                r"\s*\d",
                normalized,
            ):
                comma_page_entries += 1

            # Typical alphabetically ordered index entries.
            if re.match(
                r"^[A-Za-z][A-Za-z0-9\s,\-()/]{1,80}"
                r"\s+\d+(?:\s*,\s*\d+)*$",
                normalized,
            ):
                alphabetic_entries += 1

        alphabetic_ratio = self._ratio(
            alphabetic_entries,
            len(lines),
        )

        comma_page_ratio = self._ratio(
            comma_page_entries,
            len(lines),
        )

        score = max(
            alphabetic_ratio,
            comma_page_ratio,
        )

        return {
            "score": min(score, 1.0),
            "alphabetic_entry_ratio": (
                alphabetic_ratio
            ),
            "comma_page_ratio": (
                comma_page_ratio
            ),
            "is_index_like": (
                score >= 0.30
            ),
        }

    # ======================================================================
    # PROSE DETECTION
    # ======================================================================

    def _analyze_prose_structure(
        self,
        lines: list[str],
    ) -> dict[str, Any]:

        if not lines:
            return {
                "ratio": 0.0,
                "long_sentence_count": 0,
            }

        prose_lines = 0

        for line in lines:

            words = line.split()

            if len(words) >= 18:
                prose_lines += 1
                continue

            if line.endswith(
                (".", "?", "!")
            ) and len(words) >= 8:
                prose_lines += 1

        return {
            "ratio": self._ratio(
                prose_lines,
                len(lines),
            ),
            "long_sentence_count": prose_lines,
        }

    # ======================================================================
    # LINE CONSISTENCY
    # ======================================================================

    def _analyze_line_consistency(
        self,
        lines: list[str],
    ) -> dict[str, Any]:

        if len(lines) < 3:
            return {
                "consistent_entry_structure": False,
                "page_reference_ratio": 0.0,
            }

        page_reference_count = sum(
            bool(
                DOT_LEADER_RE.match(line)
                or TRAILING_PAGE_RE.match(line)
            )
            for line in lines
        )

        ratio = self._ratio(
            page_reference_count,
            len(lines),
        )

        return {
            "consistent_entry_structure": (
                ratio >= 0.40
            ),
            "page_reference_ratio": ratio,
        }

    # ======================================================================
    # INSUFFICIENT STRUCTURE
    # ======================================================================

    def _insufficient_structure(
        self,
        lines: list[str],
        section_matches: list[str],
        page_reference_matches: list[str],
        toc_tables: list[TableRepresentation],
    ) -> dict[str, Any]:

        if len(lines) < 3:

            return {
                "is_insufficient": True,
                "reason": "too_few_lines",
            }

        if (
            not section_matches
            and not page_reference_matches
            and not toc_tables
        ):

            return {
                "is_insufficient": True,
                "reason": (
                    "no_toc_like_structure"
                ),
            }

        return {
            "is_insufficient": False,
            "reason": None,
        }

    # ======================================================================
    # TABLE ANALYSIS
    # ======================================================================

    def _looks_like_toc_table(
        self,
        table: TableRepresentation,
    ) -> bool:

        rows = self._clean_table_rows(
            table
        )

        if len(rows) < 3:
            return False

        section_rows = 0
        page_rows = 0

        for row in rows:

            row_text = " ".join(row)

            if self._parse_section_number(
                row_text
            ):
                section_rows += 1

            if any(
                self._looks_like_page_reference(
                    value
                )
                for value in row
            ):
                page_rows += 1

        row_count = len(rows)

        section_ratio = (
            section_rows / row_count
        )

        page_ratio = (
            page_rows / row_count
        )

        return (
            section_ratio >= 0.20
            or page_ratio >= 0.30
        )

    def _looks_like_data_table(
        self,
        table: TableRepresentation,
    ) -> bool:

        rows = self._clean_table_rows(
            table
        )

        if len(rows) < 3:
            return False

        if not rows:
            return False

        column_count = max(
            len(row)
            for row in rows
        )

        # Data tables tend to have several columns and don't show
        # the section/page-reference structure expected from TOCs.
        if column_count < 3:
            return False

        toc_like = self._looks_like_toc_table(
            table
        )

        if toc_like:
            return False

        return True

    def _clean_table_rows(
        self,
        table: TableRepresentation,
    ) -> list[list[str]]:

        rows: list[list[str]] = []

        for row in table.rows:

            values = [
                str(value).strip()
                for value in row
                if value is not None
                and str(value).strip()
            ]

            if values:
                rows.append(values)

        return rows

    def _select_best_toc_table(
        self,
        tables: list[TableRepresentation],
    ) -> TableRepresentation | None:

        candidates = [
            table
            for table in tables
            if self._looks_like_toc_table(
                table
            )
        ]

        if not candidates:
            return None

        return max(
            candidates,
            key=self._toc_table_score,
        )

    def _toc_table_score(
        self,
        table: TableRepresentation,
    ) -> float:

        rows = self._clean_table_rows(
            table
        )

        if not rows:
            return 0.0

        section_count = 0
        page_count = 0

        for row in rows:

            if self._parse_section_number(
                " ".join(row)
            ):
                section_count += 1

            if any(
                self._looks_like_page_reference(
                    value
                )
                for value in row
            ):
                page_count += 1

        count = len(rows)

        return (
            0.5 * section_count / count
            + 0.5 * page_count / count
        )

    def _describe_table(
        self,
        table: TableRepresentation,
    ) -> dict[str, Any]:

        return {
            "rows": len(table.rows),
            "columns": (
                len(table.columns)
                if table.columns
                else max(
                    (
                        len(row)
                        for row in table.rows
                    ),
                    default=0,
                )
            ),
            "bbox": table.bbox,
            "extraction_method": (
                table.extraction_method
            ),
            "sample_rows": table.rows[:5],
        }

    # ======================================================================
    # TABLE PARSING
    # ======================================================================

    def _parse_table(
        self,
        table: TableRepresentation,
        source_page: int,
    ) -> list[TOCEntry]:

        entries: list[TOCEntry] = []

        for row in table.rows:

            values = [
                str(value).strip()
                for value in row
                if value is not None
                and str(value).strip()
            ]

            if not values:
                continue

            entry = self._parse_table_row(
                values,
                source_page,
            )

            if entry is not None:
                entries.append(entry)

        return entries

    def _parse_table_row(
        self,
        values: list[str],
        source_page: int,
    ) -> TOCEntry | None:

        section_number = None
        title = None
        level = 1

        for index, value in enumerate(
            values
        ):

            parsed = (
                self._parse_section_number(
                    value
                )
            )

            if parsed is None:
                continue

            section_number, title = parsed

            level = self._infer_level(
                section_number
            )

            remaining = values[
                index + 1 :
            ]

            title_parts = [
                part
                for part in remaining
                if not self._looks_like_page_reference(
                    part
                )
            ]

            if title_parts:
                title = " ".join(
                    [title] + title_parts
                )

            break

        if section_number is None:
            title = values[0]

        page_ref = self._find_page_reference(
            values
        )

        if not title:
            return None

        if (
            section_number is None
            and page_ref is None
        ):
            return None

        return TOCEntry(
            text=title.strip(),
            section_number=section_number,
            level=level,
            printed_page_ref=page_ref,
            source_page=source_page,
            confidence=0.80,
        )

    # ======================================================================
    # TEXT PARSING
    # ======================================================================

    def _parse_text(
        self,
        text: str,
        source_page: int,
    ) -> list[TOCEntry]:

        entries: list[TOCEntry] = []

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            entry = self._parse_text_line(
                line,
                source_page,
            )

            if entry is not None:
                entries.append(entry)

        return entries

    def _parse_text_line(
        self,
        line: str,
        source_page: int,
    ) -> TOCEntry | None:

        section = self._parse_section_number(
            line
        )

        if section is not None:

            section_number, title = section

            page_ref = (
                self._extract_trailing_page(
                    title
                )
            )

            if page_ref is not None:

                title = (
                    self._remove_page_reference(
                        title,
                        page_ref,
                    )
                )

            return TOCEntry(
                text=title.strip(),
                section_number=section_number,
                level=self._infer_level(
                    section_number
                ),
                printed_page_ref=page_ref,
                source_page=source_page,
                confidence=0.75,
            )

        match = DOT_LEADER_RE.match(
            line
        )

        if match:

            return TOCEntry(
                text=match.group(1).strip(),
                printed_page_ref=match.group(2),
                source_page=source_page,
                confidence=0.70,
            )

        return None

    # ======================================================================
    # SECTION NUMBERS
    # ======================================================================

    def _parse_section_number(
        self,
        text: str,
    ) -> tuple[str, str] | None:

        stripped = text.strip()

        for _, pattern in SECTION_PATTERNS:

            match = pattern.match(
                stripped
            )

            if not match:
                continue

            section_number = (
                match.group(1).strip()
            )

            title = (
                match.group(2).strip()
            )

            if title:
                return (
                    section_number,
                    title,
                )

        return None

    @staticmethod
    def _infer_level(
        section_number: str,
    ) -> int:

        if not section_number:
            return 1

        return (
            section_number.count(".") + 1
            if "." in section_number
            else 1
        )

    # ======================================================================
    # PAGE REFERENCES
    # ======================================================================

    @staticmethod
    def _looks_like_page_reference(
        value: str,
    ) -> bool:

        return bool(
            PAGE_REFERENCE_RE.fullmatch(
                value.strip()
            )
        )

    @classmethod
    def _find_page_reference(
        cls,
        values: list[str],
    ) -> str | None:

        for value in reversed(values):

            if cls._looks_like_page_reference(
                value
            ):
                return value

        return None

    @staticmethod
    def _extract_trailing_page(
        text: str,
    ) -> str | None:

        match = TRAILING_PAGE_RE.match(
            text.strip()
        )

        if not match:
            return None

        return match.group(2)

    @staticmethod
    def _remove_page_reference(
        text: str,
        page_ref: str,
    ) -> str:

        pattern = re.compile(
            rf"\s+(?:page|p\.|pg\.)?\s*"
            rf"{re.escape(page_ref)}\s*$",
            re.IGNORECASE,
        )

        return pattern.sub(
            "",
            text,
        ).strip()

    # ======================================================================
    # GENERAL HELPERS
    # ======================================================================

    @staticmethod
    def _ratio(
        numerator: int,
        denominator: int,
    ) -> float:

        if denominator <= 0:
            return 0.0

        return numerator / denominator

    @staticmethod
    def _short_line_ratio(
        lines: list[str],
    ) -> float:

        if not lines:
            return 0.0

        short_lines = sum(
            len(line.split()) <= 15
            for line in lines
        )

        return (
            short_lines / len(lines)
        )

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:

        if not text:
            return ""

        normalized = (
            unicodedata.normalize(
                "NFKD",
                text,
            )
        )

        normalized = (
            normalized
            .encode(
                "ASCII",
                "ignore",
            )
            .decode("utf-8")
        )

        normalized = re.sub(
            r"[^\w\s]",
            " ",
            normalized.lower(),
        )

        return " ".join(
            normalized.split()
        )