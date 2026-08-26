from __future__ import annotations

import re
from dataclasses import dataclass

from .models import PageRepresentation, TextBlock


@dataclass
class TitleCandidate:
    """
    A possible section/document title found on a page.
    """

    text: str
    page_number: int
    confidence: float

    font_size: float | None = None
    is_bold: bool = False
    bbox: tuple[float, float, float, float] | None = None

    reasons: list[str] | None = None


class TitleDetector:
    """
    Detect likely titles/headings from page layout.

    This class does NOT:
        - detect TOCs
        - segment the document
        - decide document boundaries

    It only produces title candidates.
    """

    def __init__(
        self,
        min_title_length: int = 2,
        max_title_length: int = 200,
    ) -> None:
        self.min_title_length = min_title_length
        self.max_title_length = max_title_length

    def detect(
        self,
        page: PageRepresentation,
    ) -> list[TitleCandidate]:
        """
        Detect title candidates on a page.
        """

        candidates: list[TitleCandidate] = []

        for block in page.text_blocks:

            candidate = self._analyze_block(
                block,
                page,
            )

            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(
            key=lambda candidate: (
                candidate.confidence,
                candidate.font_size or 0,
            ),
            reverse=True,
        )

        return candidates

    def _analyze_block(
        self,
        block: TextBlock,
        page: PageRepresentation,
    ) -> TitleCandidate | None:

        text = self._clean_text(block.text)

        if not self._is_valid_text(text):
            return None

        score = 0.0
        reasons: list[str] = []

        # Typography

        if block.is_bold:
            score += 0.25
            reasons.append("bold")

        if block.font_size is not None:

            if page.height > 0:
                # We use relative page geometry only as a weak
                # signal. Absolute font size is not universally
                # comparable across PDFs.
                if block.font_size >= 16:
                    score += 0.20
                    reasons.append("large_font")

        # Position

        if block.bbox is not None:

            x0, y0, x1, y1 = block.bbox

            page_top_ratio = (
                y0 / page.height
                if page.height
                else 1.0
            )

            if page_top_ratio < 0.30:
                score += 0.10
                reasons.append("near_top")

        # Text characteristics

        if self._looks_like_heading(text):
            score += 0.20
            reasons.append("heading_like_text")

        if self._has_section_number(text):
            score += 0.15
            reasons.append("section_number")

        # Penalize obvious non-headings

        if self._looks_like_sentence(text):
            score -= 0.15
            reasons.append("sentence_like")

        if self._looks_like_false_heading(text):
            score -= 0.40
            reasons.append("false_heading")

        score = max(
            0.0,
            min(score, 1.0),
        )

        # We do not want every text block to become a title.
        if score < 0.40:
            return None

        return TitleCandidate(
            text=text,
            page_number=page.page_number,
            confidence=score,
            font_size=block.font_size,
            is_bold=block.is_bold,
            bbox=block.bbox,
            reasons=reasons,
        )

    # TEXT FILTERS

    def _is_valid_text(
        self,
        text: str,
    ) -> bool:

        if not text:
            return False

        if len(text) < self.min_title_length:
            return False

        if len(text) > self.max_title_length:
            return False

        return True

    @staticmethod
    def _clean_text(
        text: str,
    ) -> str:

        return " ".join(
            text.replace("\n", " ").split()
        )

    @staticmethod
    def _looks_like_heading(
        text: str,
    ) -> bool:

        words = text.split()

        if not words:
            return False

        # Headings tend to be relatively compact.
        if len(words) <= 15:
            return True

        return False

    @staticmethod
    def _has_section_number(
        text: str,
    ) -> bool:

        return bool(
            re.match(
                r"^\s*"
                r"(?:"
                r"\d+(?:\.\d+)*"
                r"|[A-Z]\.\d+(?:\.\d+)*"
                r")"
                r"(?:[.)-])?"
                r"\s+",
                text,
            )
        )

    @staticmethod
    def _looks_like_sentence(
        text: str,
    ) -> bool:

        words = text.split()

        if len(words) < 8:
            return False

        if text.endswith(
            (".", ",", ";", ":")
        ):
            return True

        return False

    @staticmethod
    def _looks_like_false_heading(
        text: str,
    ) -> bool:

        lowered = text.lower().strip()

        false_prefixes = (
            "warning",
            "caution",
            "danger",
            "notice",
            "note",
            "important",
            "attention",
            "figure",
            "fig.",
            "table",
            "tab.",
            "photo",
            "drawing",
        )

        return lowered.startswith(
            false_prefixes
        )

