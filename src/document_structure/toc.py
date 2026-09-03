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
    TOCRegion,
)



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

# ---------------------------------------------------------------------------
# Document / drawing reference codes
# ---------------------------------------------------------------------------

DOC_CODE_RE = re.compile(
    r"^[A-Za-z0-9]{1,12}(?:[-/][A-Za-z0-9]{1,12}){2,}$"
)

TRAILING_DOC_CODE_RE = re.compile(
    r"^(.+?)\s+([A-Za-z0-9]{1,12}(?:[-/][A-Za-z0-9]{1,12}){2,})\s*$"
)

# Header terms that mark the right-hand column of a two-column tabl
DOC_REGISTER_HEADER_TERMS: tuple[str, ...] = (
    "doc. no",
    "doc no",
    "document no",
    "document number",
    "doc code",
    "doc. code",
    "drawing no",
    "dwg no",
    "drawing number",
    "dwg number",
)

POSITION_CODE_RE = re.compile(
    r"[\w./-]{2,40}\s+Pos\.\s*\d+(?:\s*-\s*\d+)?",
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

# A cell/line that is JUST a section number with no title alongside it
BARE_SECTION_NUMBER_RE = re.compile(
    r"^([A-Z]?\d+[A-Z]?(?:\.\d+){0,3}\.?)$"
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

    def detect_printed_tocs(
        self,
        pages: list[PageRepresentation],
    ) -> list[TOCRegion]:
        """
        Run analyze_page() across a whole document and group the
        result into TOCRegion objects.
        """

        toc_pages: list[
            tuple[int, TOCAnalysis]
        ] = []

        for pdf_page, page in enumerate(
            pages,
            start=1,
        ):

            analysis = self.analyze_page(
                page
            )

            if analysis.is_toc:
                toc_pages.append(
                    (pdf_page, analysis)
                )

        regions: list[TOCRegion] = []

        for pdf_page, analysis in toc_pages:

            previous_region = (
                regions[-1]
                if regions
                else None
            )

            is_continuation = (
                previous_region is not None
                and pdf_page
                == previous_region.pages[-1]
                + 1
            )

            if is_continuation:

                previous_region.pages.append(
                    pdf_page
                )

                previous_region.entries.extend(
                    analysis.entries
                )

                previous_region.confidence = max(
                    previous_region.confidence,
                    analysis.confidence,
                )

            else:

                regions.append(
                    TOCRegion(
                        pages=[pdf_page],
                        entries=list(
                            analysis.entries
                        ),
                        confidence=analysis.confidence,
                        toc_type="printed",
                    )
                )

        for region in regions:

            region.has_page_references = any(
                entry.reference_kind == "page"
                for entry in region.entries
            )

        return regions

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
        

    def _analyze_position_list_structure(
        self,
        lines: list[str],
        tables: list[TableRepresentation] | None = None,
    ) -> dict[str, Any]:
        """
        Detect a page dominated by "<code> Pos. N[-M]" position-list
        entries (e.g. spare-parts / bill-of-materials listings) -- these
        can superficially resemble a TOC/document-register (short,
        code-like lines) but are a distinct, non-TOC structure.

        Text is flattened into one blob (all lines, plus every non-empty
        table cell) before matching, rather than matched per-line --
        real extracted text often collapses logically separate position
        entries into fewer, longer lines, so a per-line match would find
        ~0 of them even on a page dominated by the pattern.
        """

        text = "\n".join(lines)

        for table in tables or []:
            for row in table.rows:
                for value in row:
                    if value:
                        text += "\n" + str(value)

        matches = POSITION_CODE_RE.findall(text)
        match_count = len(matches)
        ratio = self._ratio(match_count, len(lines))

        return {
            "match_count": match_count,
            "ratio": ratio,
            "is_position_list": ratio >= 0.20 or match_count >= 10,
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

        # `_has_plausible_title_text` guards against the structural
        # patterns below (DOT_LEADER_RE/TRAILING_PAGE_RE) matching a
        # line purely because it happens to end in a small number --
        # e.g. a spec/measurement line ("Diametre 25", "Poids 12") or a
        # numbered legal/regulatory clause. Those patterns are
        # deliberately language-agnostic (so they work on a TOC in any
        # language), which is exactly why, without this guard, a page
        # of ordinary prose IN ANY LANGUAGE that happens to have several
        # short lines ending in digits can look like a TOC.
        page_reference_matches = [
            line
            for line in lines
            if self._has_plausible_title_text(line)
            and (
                DOT_LEADER_RE.match(line)
                or TRAILING_PAGE_RE.match(line)
                or TRAILING_DOC_CODE_RE.match(line)
            )
        ]

        dot_leader_matches = [
            line
            for line in lines
            if DOT_LEADER_RE.match(line)
        ]

        # A second, complementary guard, this one on the NUMBERS
        # themselves rather than the surrounding text: real TOC entries
        # are listed in reading order with page numbers that increase
        # (or stay flat) down the page. Incidental numbers on an
        # ordinary paragraph (measurements, clause numbers, percentages)
        # have no such order. This is language-agnostic by construction
        # -- it only looks at the numbers, never at vocabulary -- so it
        # catches the foreign-language false-positive case just as well
        # as an English one.
        reference_numbers = [
            number
            for line in page_reference_matches
            if (number := self._extract_trailing_number(line)) is not None
        ]

        reference_monotonicity = self._monotonicity_score(reference_numbers)

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

        document_register_header = (
            self._page_has_document_register_header(
                page.tables
            )
        )

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
        # Position-list evidence
        # ------------------------------------------------------------------

        position_list_evidence = (
            self._analyze_position_list_structure(
                lines,
                tables=page.tables,
            )
        )

        # ------------------------------------------------------------------
        # Layout / repetition evidence
        # ------------------------------------------------------------------

        consistency = (
            self._analyze_line_consistency(
                lines,
                page_reference_matches,
            )
        )

        positive = {
            "strong_toc_keywords": (
                strong_keywords
            ),

            "document_register_header": (
                document_register_header
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
                "monotonicity": (
                    reference_monotonicity
                ),
                "monotonicity_sample_size": len(
                    reference_numbers
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
        #
        # A document-register header ("Description" / "Doc. No.") is
        # treated as an equally strong, alternate heading signal --
        # vendor document registers often carry no "Contents"-style
        # title at all, especially on continuation pages, but the
        # column headers themselves are just as reliable a tell.
        if positive["strong_toc_keywords"]:
            score += 0.15
        elif positive["document_register_header"]:
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

        # Numbers that superficially look like page references but do
        # not behave like a real TOC's page numbers (which are listed
        # in reading order and increase, or stay flat, down the page)
        # are a strong sign this is an ordinary paragraph with
        # incidental numbers (measurements, clause numbers, percentages)
        # rather than an actual table of contents -- see
        # `_monotonicity_score` / `_has_plausible_title_text`. Gated on
        # `monotonicity_sample_size` (not just `page_ratio`), since a
        # page whose reference evidence is mostly doc-code matches
        # (see TRAILING_DOC_CODE_RE, which _monotonicity_score cannot
        # judge -- doc codes aren't page numbers) can have a high
        # page_ratio with too few actual numbers to say anything about
        # ordering; that must never be misread as "not monotonic".
        monotonicity = positive[
            "page_references"
        ]["monotonicity"]

        monotonicity_sample_size = positive[
            "page_references"
        ]["monotonicity_sample_size"]

        if (
            page_ratio >= 0.20
            and monotonicity_sample_size >= 3
        ):

            if monotonicity >= 0.70:
                score += 0.08
            elif monotonicity <= 0.30:
                score -= 0.20

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
        page_reference_matches: list[str],
    ) -> dict[str, Any]:
        """
        `page_reference_matches` is passed in (rather than recomputed
        here with the raw, unguarded regexes) so this reuses the same
        `_has_plausible_title_text`-filtered matches used for scoring --
        otherwise a page of prose with several digit-ending lines could
        still be marked as having a "consistent entry structure" even
        after the false-positive guard rejected those same lines
        everywhere else.
        """

        if len(lines) < 3:
            return {
                "consistent_entry_structure": False,
                "page_reference_ratio": 0.0,
            }

        ratio = self._ratio(
            len(page_reference_matches),
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
        reference_rows = 0
        reference_numbers: list[int] = []

        for row in rows:

            row_text = " ".join(row)

            if self._parse_section_number(
                row_text
            ):
                section_rows += 1

            if self._row_has_single_trailing_reference(row):

                reference_rows += 1

                ref_index, ref_value, ref_kind = (
                    self._find_reference_with_index(row)
                )

                if ref_kind == "page":
                    try:
                        reference_numbers.append(
                            int(ref_value.strip())
                        )
                    except ValueError:
                        pass

        row_count = len(rows)

        section_ratio = (
            section_rows / row_count
        )

        reference_ratio = (
            reference_rows / row_count
        )

        if (
            section_ratio >= 0.20
            or reference_ratio >= 0.30
        ):

            # Same false-positive guard as the text-page path (see
            # `_monotonicity_score`): a genuine TOC table's page-number
            # column increases down the page. A foreign-language
            # (or any-language) data/spec table whose rows happen to
            # end in numbers -- measurements, IDs, tolerances -- clears
            # the ratios above just as easily, but its numbers are not
            # in page order. Only trust the ratios alone when there
            # either isn't enough numeric evidence to judge ordering,
            # or the ordering actually looks like page numbers.
            monotonicity = self._monotonicity_score(
                reference_numbers
            )

            looks_scrambled = (
                len(reference_numbers) >= 3
                and monotonicity <= 0.30
            )

            if not looks_scrambled:
                return True

        # Fallback: a document-register header ("Description" /
        # "Doc. No.") on its own is strong enough evidence, even when
        # the entry rows didn't independently clear the ratios above
        # -- e.g. a short continuation page with only a couple of rows,
        # or a table rejected just above for having scrambled numbers.
        return self._has_document_register_header(
            rows
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

    def _has_document_register_header(
        self,
        rows: list[list[str]],
    ) -> bool:
        """
        Detect a "Description" / "Doc. No." (or "Drawing No.", etc.)
        style header pair, which marks the table as a document-register
        index regardless of what the entries' reference values look
        like.
        """

        for row in rows[:2]:

            normalized_cells = [
                self._normalize(cell)
                for cell in row
            ]

            has_description = any(
                "description" in cell
                for cell in normalized_cells
            )

            has_doc_reference = any(
                any(
                    term in cell
                    for term in DOC_REGISTER_HEADER_TERMS
                )
                for cell in normalized_cells
            )

            if has_description and has_doc_reference:
                return True

        return False

    def _page_has_document_register_header(
        self,
        tables: list[TableRepresentation],
    ) -> bool:

        for table in tables:

            rows = self._clean_table_rows(
                table
            )

            if self._has_document_register_header(
                rows
            ):
                return True

        return False

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
        reference_count = 0

        for row in rows:

            if self._parse_section_number(
                " ".join(row)
            ):
                section_count += 1

            if any(
                self._classify_reference(
                    value
                )
                for value in row
            ):
                reference_count += 1

        count = len(rows)

        return (
            0.5 * section_count / count
            + 0.5 * reference_count / count
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

    @staticmethod
    def _clean_text(
        text: str,
    ) -> str:
        """
        Normalize a TOC entry's display text before it goes into a
        TOCEntry.

        PyMuPDF table/text extraction on this document type inserts
        raw control characters (observed: \\x02 STX, \\x03 ETX) where a
        real space belongs -- e.g. "DOCUMENTS\\x02&\\x02DRAWINGS\\x02LIST"
        instead of "DOCUMENTS & DRAWINGS LIST". They can also appear
        doubled up ("\\x02\\x02") or trailing at the end of the string.

        This does NOT fix the separate, unrelated problem of raw_text
        extraction losing whitespace entirely between words with no
        control character to replace (e.g. "AMMONIASTORAGE...") -- that
        would need a different, dictionary/heuristic-based fix.
        """

        import re

        cleaned = re.sub(
            r"[\x02\x03]",
            " ",
            text,
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned,
        )

        return cleaned.strip()

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

            if parsed is not None:

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
                    if self._classify_reference(
                        part
                    ) is None
                ]

                if title_parts:
                    title = " ".join(
                        [title] + title_parts
                    )

                break

            # A table often puts the section number and its title in
            # separate cells (e.g. "5.4" | "MAIN MOTOR TERMINAL BOXES"
            # | "P1-REF-..."), so no single cell ever matches the
            # "number + title" patterns above on its own. Fall back to
            # treating a cell that is JUST a bare section number as the
            # number, and take the title from the next cell(s).
            bare_number = (
                self._parse_bare_section_number(
                    value
                )
            )

            if bare_number is None:
                continue

            remaining = values[
                index + 1 :
            ]

            title_parts = [
                part
                for part in remaining
                if self._classify_reference(
                    part
                ) is None
            ]

            if not title_parts:
                continue

            section_number = bare_number

            level = self._infer_level(
                section_number
            )

            title = " ".join(title_parts)

            break

        if section_number is None:
            title = values[0]

        reference = self._find_reference(
            values
        )

        page_ref = (
            reference[0]
            if reference
            else None
        )

        reference_kind = (
            reference[1]
            if reference
            else None
        )

        if not title:
            return None

        if (
            section_number is None
            and page_ref is None
        ):
            return None

        return TOCEntry(
            text=self._clean_text(title),
            section_number=section_number,
            level=level,
            printed_page_ref=page_ref,
            reference_kind=reference_kind,
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

            page_ref, reference_kind = (
                self._extract_trailing_reference(
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
                text=self._clean_text(title),
                section_number=section_number,
                level=self._infer_level(
                    section_number
                ),
                printed_page_ref=page_ref,
                reference_kind=reference_kind,
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
                reference_kind="page",
                source_page=source_page,
                confidence=0.70,
            )

        match = TRAILING_DOC_CODE_RE.match(
            line
        )

        if match:

            return TOCEntry(
                text=match.group(1).strip(),
                printed_page_ref=match.group(2),
                reference_kind="doc_code",
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
    def _parse_bare_section_number(
        text: str,
    ) -> str | None:
        """
        Match a cell that contains ONLY a section number, with no
        title text alongside it (e.g. "5.4", "6.", "7.10") -- as
        opposed to _parse_section_number, which requires the title to
        be part of the same string. This covers tables where the
        number and title live in separate columns.
        """

        stripped = text.strip()

        match = BARE_SECTION_NUMBER_RE.match(
            stripped
        )

        if not match:
            return None

        return match.group(1).rstrip(".")

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

    @staticmethod
    def _looks_like_doc_code(
        value: str,
    ) -> bool:

        return bool(
            DOC_CODE_RE.fullmatch(
                value.strip()
            )
        )

    @classmethod
    def _classify_reference(
        cls,
        value: str,
    ) -> str | None:
        """
        Classify a trailing table/line value as a reference.

        Returns "page" for a plain printed page number, "doc_code" for
        a document/drawing reference code (e.g. "P1-REF-2012-123-030"),
        or None if it looks like neither.
        """

        stripped = value.strip()

        if cls._looks_like_page_reference(
            stripped
        ):
            return "page"

        if cls._looks_like_doc_code(
            stripped
        ):
            return "doc_code"

        return None

    @classmethod
    def _find_reference(
        cls,
        values: list[str],
    ) -> tuple[str, str] | None:

        for value in reversed(values):

            kind = cls._classify_reference(
                value
            )

            if kind is not None:
                return value, kind

        return None

    @classmethod
    def _find_reference_with_index(
        cls,
        row: list[str],
    ) -> tuple[int | None, str | None, str | None]:
        """
        Same tail-anchored search as `_find_reference`, but also returns
        the index of the matched cell -- needed by
        `_row_has_single_trailing_reference` to know which cell to
        exclude when checking the REST of the row for extra numbers.
        """

        for index in range(len(row) - 1, -1, -1):

            kind = cls._classify_reference(
                row[index]
            )

            if kind is not None:
                return index, row[index], kind

        return None, None, None

    @classmethod
    def _row_has_single_trailing_reference(
        cls,
        row: list[str],
    ) -> bool:
        """
        FALSE-POSITIVE GUARD: a genuine TOC/document-register row carries
        exactly ONE reference value (one page number, or one doc/drawing
        code) next to its label -- e.g. ["3.2", "Technical Specifications",
        "5"]. A spec/dimension table row (bolt torque by size, weight by
        frame size, voltage by model...) is structurally identical --
        label cell(s) followed by a trailing number that
        `_classify_reference` happily matches -- but its OTHER cells are
        also short numbers (they're the whole point of the table), not
        incidental text. Rejecting any row where a second cell (besides
        the label and the matched reference) also looks like a bare page
        number is what tells the two apart, without relying on any
        language-specific vocabulary.

        Known limitation: a real TOC table with an extra all-numeric
        column (e.g. a nesting "level" column) would also be rejected by
        this guard -- not observed in the codebase's test corpus, and a
        rarer format than the spec-table false positive this fixes.
        """

        if len(row) < 2:
            return False

        index, _, kind = cls._find_reference_with_index(row)

        if kind is None:
            return False

        other_cells = [
            cell
            for position, cell in enumerate(row)
            if position not in (0, index)
        ]

        extra_numeric_cells = sum(
            1
            for cell in other_cells
            if cls._looks_like_page_reference(cell)
        )

        return extra_numeric_cells == 0

    @staticmethod
    def _extract_trailing_reference(
        text: str,
    ) -> tuple[str | None, str | None]:

        stripped = text.strip()

        match = TRAILING_PAGE_RE.match(
            stripped
        )

        if match:
            return match.group(2), "page"

        match = TRAILING_DOC_CODE_RE.match(
            stripped
        )

        if match:
            return match.group(2), "doc_code"

        return None, None

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
    # FALSE-POSITIVE GUARDS (language-agnostic)
    # ======================================================================
    #
    # Both guards below exist to fix the same class of false positive:
    # DOT_LEADER_RE / TRAILING_PAGE_RE are deliberately loose (they just
    # look for "some text, then a small number at the end of the line")
    # so they work on a real TOC in ANY language. The price is that they
    # are just as happy to match an ordinary paragraph's incidental
    # numbers (measurements, clause numbers, percentages, article
    # references) -- most noticeable on foreign-language technical or
    # legal text, since that is often where short, numbered lines are
    # most common outside of an actual TOC.

    MIN_TITLE_WORD_LENGTH = 3

    @classmethod
    def _has_plausible_title_text(
        cls,
        text: str,
    ) -> bool:
        """
        True if `text` contains at least one real word (alphabetic,
        length >= MIN_TITLE_WORD_LENGTH). A genuine TOC entry always has
        an actual title next to its page number; a line that "matches"
        only because it ends in a number but has no real title text
        (e.g. a bare measurement, a code, a lone digit sequence) should
        not count as page-reference evidence.
        """

        words = re.findall(
            r"[^\W\d_]+",
            text,
            flags=re.UNICODE,
        )

        return any(
            len(word) >= cls.MIN_TITLE_WORD_LENGTH
            for word in words
        )

    @staticmethod
    def _extract_trailing_number(
        line: str,
    ) -> int | None:
        """
        Extract the trailing reference number from a line already known
        to match DOT_LEADER_RE or TRAILING_PAGE_RE (returns None for a
        TRAILING_DOC_CODE_RE-style match, which is not a plain integer).
        """

        match = (
            DOT_LEADER_RE.match(line)
            or TRAILING_PAGE_RE.match(line)
        )

        if not match:
            return None

        try:
            return int(match.group(2))
        except (IndexError, ValueError):
            return None

    @staticmethod
    def _monotonicity_score(
        numbers: list[int],
    ) -> float:
        """
        Fraction of consecutive pairs that are non-decreasing.

        A real TOC lists entries in reading order with page numbers
        that increase (or occasionally repeat) down the page --
        typically close to 1.0 here. Incidental numbers on an ordinary
        paragraph (measurements, clause numbers...) have no such order
        and typically score well below 0.5.

        Returns 0.0 when there are fewer than 3 numbers -- not enough
        data to judge either way, so this must never be read as
        "evidence against".
        """

        if len(numbers) < 3:
            return 0.0

        increasing_steps = sum(
            1
            for previous, current in zip(numbers, numbers[1:])
            if current >= previous
        )

        return increasing_steps / (len(numbers) - 1)

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