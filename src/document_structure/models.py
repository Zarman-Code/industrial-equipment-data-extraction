from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence


@dataclass
class TextBlock:
    """Extracted text block with visual formatting and spatial layout metadata."""
    text: str
    bbox: list[float]
    font_size: float
    font_name: str
    is_bold: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class TableRepresentation:
    """Structured representation of a table extracted from a page."""
    rows: list[list[Any]]
    columns: list[str] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    extraction_method: str | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox"] = list(self.bbox) if self.bbox else None
        return d


@dataclass
class PageRepresentation:
    """
    Complete extracted representation of one PDF page.
    """
    page_number: int
    raw_text: str = ""
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[TableRepresentation] = field(default_factory=list)
    image_count: int = 0
    is_scanned: bool = False
    width: float | None = None
    height: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "raw_text": self.raw_text,
            "text_blocks": [tb.to_dict() for tb in self.text_blocks],
            "tables": [tbl.to_dict() for tbl in self.tables],
            "image_count": self.image_count,
            "is_scanned": self.is_scanned,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class TOCEntry:
    """
    One entry extracted from a table of contents.

    What kind of trailing reference `printed_page_ref` actually is:
       "page"     - a plain printed page number (safe to resolve to a
                     PDF page via DocumentSegmenter._resolve_printed_page)
       "doc_code" - a document/drawing reference code (e.g.
                     "P1-REF-2012-123-030"), common in vendor
                     documentation registers. NOT a page number and
                     must never be fed into page-number resolution.
       None       - unknown / not set
    """
    text: str
    section_number: str | None = None
    level: int = 1
    printed_page_ref: str | None = None
    reference_kind: str | None = None
    source_page: int | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TOCAnalysis:
    """Structural analysis result for one page."""
    page_number: int
    is_toc: bool
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    entries: list[TOCEntry] = field(default_factory=list)
    extraction_source: str | None = None

    @property
    def positive_evidence(self) -> dict[str, Any]:
        return self.evidence.get("positive", {})

    @property
    def negative_evidence(self) -> dict[str, Any]:
        return self.evidence.get("negative", {})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entries"] = [e.to_dict() for e in self.entries]
        return d


@dataclass
class TOCRegion:
    """Detected Table of Contents container representing a TOC page or range of pages."""
    pages: list[int]
    entries: list[TOCEntry] = field(default_factory=list)
    confidence: float = 0.8
    evidence: dict[str, Any] = field(default_factory=dict)
    toc_type: str = "printed"  # 'native', 'printed', 'local', 'unknown'
    has_page_references: bool = False
    scope_title: str | None = None

    @property
    def page_numbers(self) -> list[int]:
        return self.pages

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entries"] = [e.to_dict() for e in self.entries]
        return d


# Alias for backwards compatibility
TOC = TOCRegion

@dataclass(frozen=True)
class PageReference:
    """
    One reference extracted from a TOC row.
    """

    page_ref: str
    section_number: str | int | float | None = None
    text: str | None = None
    region_index: int | None = None
    region_pages: Sequence[int] | None = None
    level: int | None = None
    reference_kind: str | None = None
    source_page: int | None = None
    confidence: float | None = None


@dataclass
class PageReferenceMatch:
    """
    Resolution result for one TOC reference.
    """

    page_ref: str
    pdf_page: int | None
    source: str
    matched_text: str | None = None

    # Original TOC metadata, preserved when available.
    section_number: str | int | float | None = None
    text: str | None = None
    region_index: int | None = None
    region_pages: Sequence[int] | None = None
    level: int | None = None
    reference_kind: str | None = None
    source_page: int | None = None
    confidence: float | None = None

    @property
    def resolved(self) -> bool:
        return self.pdf_page is not None
    
'''@dataclass
class TitleCandidate:
    """Candidate heading identified on a page with multi-signal evidence."""
    page_number: int
    text: str
    normalized_text: str
    level_candidate: int = 1
    confidence: float = 0.5
    score: float = 0.5
    is_rejected: bool = False
    rejection_reason: str | None = None
    bbox: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    font_size: float = 10.0
    font_size_ratio: float = 1.0
    is_bold: bool = False
    is_uppercase: bool = False
    section_number: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = self.evidence.to_dict()
        return d'''


'''@dataclass
class DocumentStructure:
    """Complete structured output for the entire PDF file."""
    pdf: str
    page_count: int
    documents: list[DocumentNode] = field(default_factory=list)
    tocs: list[TOCRegion] = field(default_factory=list)
    title_candidates: list[TitleCandidate] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def validation_issues(self) -> list[str]:
        return self.diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdf": self.pdf,
            "page_count": self.page_count,
            "documents": [doc.to_dict() for doc in self.documents],
            "tocs": [toc.to_dict() for toc in self.tocs],
            "title_candidates_count": len(self.title_candidates),
            "diagnostics": self.diagnostics,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)'''


