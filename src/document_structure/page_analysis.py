"""
Extract everything useful from each PDF page and build PageRepresentation objects for downstream analysis.
"""


from __future__ import annotations

import logging
from statistics import median

import fitz  # PyMuPDF

from .models import PageRepresentation, TableRepresentation, TextBlock


logger = logging.getLogger("document_structure.page_analysis")
#from typing import Sequence
#from .titles import normalize_string


class PageAnalyzer:
    """
    Extract information from PDF pages using PyMuPDF.

    This class is responsible ONLY for extraction.

    It does not decide whether a page is:
    - a TOC,
    - a title page,
    - a section,
    - a document boundary,
    - or anything else.

    It produces PageRepresentation objects that are later
    interpreted by the structural analyzers.
    """

    def extract_document(
        self,
        doc: fitz.Document,
    ) -> list[PageRepresentation]:
        """
        Extract all pages from a PDF document.
        """

        pages: list[PageRepresentation] = []

        for page_index, page in enumerate(doc):

            page_representation = self.extract_page(
                page=page,
                page_number=page_index + 1,
            )

            pages.append(page_representation)

        return pages

    def extract_page(
        self,
        page: fitz.Page,
        page_number: int,
    ) -> PageRepresentation:
        """
        Extract all available structural information from one page.
        """

        raw_text = self._extract_raw_text(page)
        text_blocks = self._extract_text_blocks(page)
        tables = self._extract_tables(page)
        image_count = self._count_images(page)
        is_scanned = self._estimate_scanned(
            raw_text=raw_text,
            text_blocks=text_blocks,
            image_count=image_count,
        )

        return PageRepresentation(
            page_number=page_number,
            raw_text=raw_text,
            text_blocks=text_blocks,
            tables=tables,
            image_count=image_count,
            is_scanned=is_scanned,
            width=page.rect.width,
            height=page.rect.height,
        )

    # RAW TEXT

    def _extract_raw_text(
        self,
        page: fitz.Page,
    ) -> str:
        """
        Extract the page's plain text.

        We deliberately preserve the raw representation because
        structural analyzers may want to compare it against
        tables and layout information.
        """

        try:
            return page.get_text("text") or ""

        except Exception:
            logger.exception(
                "Failed to extract raw text from page %s",
                page.number + 1,
            )

            return ""

    # TEXT BLOCKS

    def _extract_text_blocks(
        self,
        page: fitz.Page,
    ) -> list[TextBlock]:
        """
        Extract text blocks with their layout information.
        """

        blocks: list[TextBlock] = []

        try:
            page_dict = page.get_text("dict")

        except Exception:
            logger.exception(
                "Failed to extract text blocks from page %s",
                page.number + 1,
            )

            return blocks

        for raw_block in page_dict.get("blocks", []):

            # type == 0 means text block.
            # Images and other block types are ignored here.
            if raw_block.get("type") != 0:
                continue

            block_text_parts: list[str] = []
            font_sizes: list[float] = []
            font_names: list[str] = []
            bold_flags: list[bool] = []

            for line in raw_block.get("lines", []):

                for span in line.get("spans", []):

                    text = span.get("text", "")

                    if text:
                        block_text_parts.append(text)

                    size = span.get("size")

                    if isinstance(size, (int, float)):
                        font_sizes.append(float(size))

                    font_name = span.get("font")

                    if font_name:
                        font_names.append(
                            str(font_name)
                        )

                    flags = span.get("flags", 0)

                    # PyMuPDF's bold flag is bit 4.
                    bold_flags.append(
                        bool(flags & 16)
                    )

            text = "".join(
                block_text_parts
            ).strip()

            if not text:
                continue

            bbox = raw_block.get("bbox")

            normalized_bbox = None

            if bbox and len(bbox) == 4:
                normalized_bbox = tuple(
                    float(value)
                    for value in bbox
                )

            blocks.append(
                TextBlock(
                    text=text,
                    bbox=normalized_bbox,
                    font_size=(
                        median(font_sizes)
                        if font_sizes
                        else None
                    ),
                    font_name=(
                        font_names[0]
                        if font_names
                        else None
                    ),
                    is_bold=(
                        any(bold_flags)
                        if bold_flags
                        else False
                    ),
                )
            )

        return blocks

    # TABLES

    def _extract_tables(
        self,
        page: fitz.Page,
    ) -> list[TableRepresentation]:
        """
        Extract tables using PyMuPDF's native table detection.

        IMPORTANT:

        This method does NOT decide whether a table is a TOC.

        It simply extracts the table structure and stores it in the
        PageRepresentation.

        The TOC analyzer will later determine whether a table
        represents a table of contents.
        """

        tables: list[TableRepresentation] = []

        try:
            table_finder = page.find_tables()

        except Exception:
            logger.exception(
                "Table detection failed on page %s",
                page.number + 1,
            )

            return tables

        for table in table_finder.tables:

            try:
                extracted = table.extract()

            except Exception:
                logger.exception(
                    "Failed to extract table on page %s",
                    page.number + 1,
                )

                continue

            if not extracted:
                continue

            rows = [
                list(row)
                for row in extracted
            ]

            columns = self._infer_table_columns(
                rows
            )

            bbox = None

            if getattr(table, "bbox", None):
                bbox = tuple(
                    float(value)
                    for value in table.bbox
                )

            tables.append(
                TableRepresentation(
                    rows=rows,
                    columns=columns,
                    bbox=bbox,
                    extraction_method="pymupdf",
                )
            )

        return tables

    @staticmethod
    def _infer_table_columns(
        rows: list[list],
    ) -> list[str]:
        """
        Infer column names when the PDF table extractor does not
        provide explicit column names.

        We do NOT assume that the first row is a header.

        This is important because a TOC may have no explicit header.
        """

        if not rows:
            return []

        column_count = max(
            len(row)
            for row in rows
        )

        return [
            f"column_{index}"
            for index in range(column_count)
        ]

    # IMAGES

    def _count_images(
        self,
        page: fitz.Page,
    ) -> int:
        """
        Count embedded raster images on the page.
        """

        try:
            return len(
                page.get_images(full=True)
            )

        except Exception:
            logger.exception(
                "Failed to count images on page %s",
                page.number + 1,
            )

            return 0

    # SCANNED-PAGE ESTIMATION

    @staticmethod
    def _estimate_scanned(
        raw_text: str,
        text_blocks: list[TextBlock],
        image_count: int,
    ) -> bool:
        """
        Estimate whether the page is likely scanned.
        """

        has_text = bool(raw_text.strip() or text_blocks)

        return (image_count > 0 and not has_text)



'''
class PDFInspector:
    """Lightweight, non-LLM page-level inspection layer using PyMuPDF."""

    def __init__(
        self,
        min_text_chars_for_scanned: int = 25,
        header_footer_margin_ratio: float = 0.08,
    ) -> None:
        self.min_text_chars_for_scanned = min_text_chars_for_scanned
        self.header_footer_margin_ratio = header_footer_margin_ratio

    def inspect_document(self, doc: fitz.Document) -> tuple[list[PageMetadata], float]:
        """Inspect all pages in the PDF document and compute global typography metrics."""
        pages: list[PageMetadata] = []
        all_font_sizes: list[float] = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_meta = self.inspect_page(page, page_idx + 1)
            pages.append(page_meta)
            for block in page_meta.blocks:
                if block.font_size > 0:
                    all_font_sizes.append(block.font_size)

        global_median = self._calculate_median(all_font_sizes) if all_font_sizes else 10.0
        self._detect_repeated_headers_footers(pages)
        return pages, global_median

    def inspect_page(self, page: fitz.Page, page_number: int) -> PageMetadata:
        """Inspect a single page and extract text blocks, font sizes, and layout."""
        rect = page.rect
        width = float(rect.width) or 595.0
        height = float(rect.height) or 842.0

        blocks: list[TextBlock] = []
        page_font_sizes: list[float] = []
        images = page.get_images()
        image_count = len(images) if images else 0

        try:
            raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        except Exception as exc:
            logger.warning("Page %d: PyMuPDF get_text('dict') failed: %s", page_number, exc)
            raw = {}

        raw_blocks = raw.get("blocks", [])
        for rb in raw_blocks:
            if rb.get("type") != 0:  # 0 is text
                continue

            lines = rb.get("lines", [])
            block_text_parts: list[str] = []
            weighted_size_sum = 0.0
            bold_char_count = 0
            total_char_count = 0
            dominant_font_name = ""

            for line in lines:
                line_parts: list[str] = []
                for span in line.get("spans", []):
                    span_text: str = span.get("text", "")
                    if not span_text:
                        continue
                    line_parts.append(span_text)
                    c_len = len(span_text)
                    total_char_count += c_len

                    sz = float(span.get("size", 0.0))
                    weighted_size_sum += sz * c_len
                    if sz > 0:
                        page_font_sizes.append(sz)

                    font_name = str(span.get("font", ""))
                    flags = int(span.get("flags", 0))
                    is_span_bold = bool(flags & (1 << 4)) or ("bold" in font_name.lower()) or ("black" in font_name.lower()) or ("heavy" in font_name.lower())
                    if is_span_bold:
                        bold_char_count += c_len
                    if not dominant_font_name and font_name:
                        dominant_font_name = font_name

                if line_parts:
                    block_text_parts.append("".join(line_parts))

            block_text = "\n".join(block_text_parts).strip()
            if not block_text:
                continue

            avg_font_size = (weighted_size_sum / total_char_count) if total_char_count > 0 else 10.0
            is_block_bold = (bold_char_count / total_char_count > 0.4) if total_char_count > 0 else False

            bbox = [float(x) for x in rb.get("bbox", [0.0, 0.0, 0.0, 0.0])]
            top_y = bbox[1] if len(bbox) >= 2 else 0.0
            top_ratio = top_y / height if height > 0 else 0.0

            blocks.append(
                TextBlock(
                    text=block_text,
                    bbox=bbox,
                    font_size=avg_font_size,
                    font_name=dominant_font_name,
                    is_bold=is_block_bold,
                    line_count=len(lines),
                    char_count=total_char_count,
                    top_ratio=top_ratio,
                    is_standalone=(len(lines) <= 3),
                )
            )

        full_text = "\n".join(b.text for b in blocks)
        char_count = len(full_text.strip())
        word_count = len(full_text.split())
        line_count = sum(b.line_count for b in blocks)

        is_scanned = char_count < self.min_text_chars_for_scanned
        text_density = (char_count / (width * height)) * 1000.0 if (width * height) > 0 else 0.0

        p_median = self._calculate_median(page_font_sizes) if page_font_sizes else 10.0
        p_max = max(page_font_sizes) if page_font_sizes else 10.0

        font_stats = {
            "median_font_size": p_median,
            "max_font_size": p_max,
        }
        layout_stats = {
            "block_count": len(blocks),
            "image_count": image_count,
            "text_density": text_density,
        }

        return PageMetadata(
            page_number=page_number,
            width=width,
            height=height,
            text=full_text,
            char_count=char_count,
            word_count=word_count,
            line_count=line_count,
            block_count=len(blocks),
            image_count=image_count,
            text_density=text_density,
            is_likely_scanned=is_scanned,
            font_statistics=font_stats,
            layout_statistics=layout_stats,
            blocks=blocks,
        )

    def _detect_repeated_headers_footers(self, pages: list[PageMetadata]) -> None:
        """Find recurring strings in the top 10% and bottom 10% of pages to filter running headers/footers."""
        if len(pages) < 3:
            return

        header_counts: dict[str, int] = {}
        footer_counts: dict[str, int] = {}

        for p in pages:
            if not p.blocks:
                continue
            for b in p.blocks:
                norm = normalize_string(b.text)
                if not norm or len(norm) < 3:
                    continue
                if b.top_ratio <= self.header_footer_margin_ratio:
                    header_counts[norm] = header_counts.get(norm, 0) + 1
                elif b.top_ratio >= (1.0 - self.header_footer_margin_ratio):
                    footer_counts[norm] = footer_counts.get(norm, 0) + 1

        threshold = max(3, int(len(pages) * 0.08))
        common_headers = {k for k, v in header_counts.items() if v >= threshold}
        common_footers = {k for k, v in footer_counts.items() if v >= threshold}

        for p in pages:
            for b in p.blocks:
                norm = normalize_string(b.text)
                if norm in common_headers and b.top_ratio <= self.header_footer_margin_ratio:
                    p.header_text = b.text
                if norm in common_footers and b.top_ratio >= (1.0 - self.header_footer_margin_ratio):
                    p.footer_text = b.text

    @staticmethod
    def _calculate_median(values: Sequence[float]) -> float:
        if not values:
            return 10.0
        s = sorted(values)
        mid = len(s) // 2
        return (s[mid - 1] + s[mid]) / 2.0 if len(s) % 2 == 0 else s[mid]'''