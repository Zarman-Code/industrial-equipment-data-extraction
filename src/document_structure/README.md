# `src/document_structure/` overview

Stage 1's building blocks: everything needed to turn a PDF into an ordered
list of document sections, either from its **native bookmarks** or, when
none exist, from **structural analysis** (per-page extraction → title
detection → table-of-contents detection → segmentation). Consumed
entirely by `backend/stage1_document_structure.py`, which picks one path
or the other and converts the result into `CandidateSection` objects for
Stage 2.

```
                        extract_raw_toc()
                               │
                 ┌─────────────┴─────────────┐
        native bookmarks found          no usable bookmarks
                 │                             │
         BookmarkProcessor                PageAnalyzer
                 │                             │
                 │                        TitleDetector
                 │                             │
                 │                        TOCDetector
                 │                             │
                 │                     DocumentSegmenter
                 │                             │
                 └──────────► CandidateSection[] ◄──────────┘
```

## Files

### `models.py`
The shared dataclasses everything else builds on: `TextBlock`,
`TableRepresentation`, `PageRepresentation` (one page's full extracted
content), `TOCEntry` (one parsed TOC line/row), `TOCAnalysis` (one page's
TOC-or-not verdict + evidence), `TOCRegion` (a merged run of consecutive
TOC pages — `TOC` is a backwards-compat alias for it), `PageReference` /
`PageReferenceMatch` (TOC-reference resolution, used by
`src/ocr/pages_from_sections.py`, not by the live Stage 1 path). Every
dataclass has a `to_dict()`.

> **Dead code:** `TitleCandidate` and `DocumentStructure` are defined here
> too, but as triple-quoted **string literals**, not real classes —
> harmless, but don't import them from `models.py`. The real, live
> `TitleCandidate` lives in `titles.py`.

### `extract_raw_pdf_toc.py`
```python
extract_raw_toc(pdf_path) -> {"filename", "total_pages", "sections": [{"index","level","title","page"}, ...]}
```
The very first thing Stage 1 tries: `fitz.open(pdf_path).get_toc(simple=True)`,
no interpretation. `FileNotFoundError` / `PermissionError` (encrypted) /
`RuntimeError` (any other PyMuPDF failure) on trouble. **This is the
`raw_toc` that flows through the rest of Stage 1** — `backend/stage1_document_structure.py`
checks `raw_toc.get("sections", [])` to decide which path to take.

> Its docstring describes a nested `{"document": {...}, "sections": [...]}`
> shape; the real return value is **flat** (`filename`/`total_pages` at the
> top level). Every caller already assumes the flat shape — only the
> docstring is stale.

Also has `process_and_save_pdf(...)`, a dump-to-JSON convenience wrapper —
not used anywhere outside itself.

### `bookmark_processor.py`
Cleans a raw bookmark tree (drops numeric-only duplicate titles and
English-only bilingual subsection titles), rebuilds a 2-level hierarchy
with page ranges, flattens it back down, and converts it to `TOCEntry`
objects. `BookmarkProcessor` (no constructor args) — the methods
`backend/stage1_document_structure.py::build_from_bookmarks` actually
calls, **in this order**:

1. `build_clean_structure(raw_data) -> {"document": total_pages, "sections": [...]}`
   — computes each Level-2 entry's page range by scanning to the next
   Level-1/Level-2 boundary, drops English-only Level-2 titles and
   numeric-duplicate titles, recomputes each Level-1's page list as the
   union of its surviving children.
2. `clean_structure_to_bookmark_sections(clean_data) -> list[dict]` —
   flattens the tree back to `{index, level, title, page}`, one page per
   entry (a subsection's page list's **first** page).
3. `bookmark_sections_to_entries(sections) -> list[TOCEntry]` — wraps each
   flat dict as a `TOCEntry` with `confidence=0.95`.

Static helpers used inside `build_clean_structure`: `is_numeric_only_title`,
`remove_duplicate_numeric_titles`, `is_english_only_title`,
`extract_section_number`, `clean_title`.

> **`region_entries_to_payload()` and `.process()` are a separate,
> LLM-classification-oriented flow — not part of Stage 1's live path.**
> `region_entries_to_payload` builds the `{"section_id","title",
> "section_number","page_start","level"}` payload shape `src/llm/classifier.py::classify_sections`
> expects; only notebooks call it. `.process()`'s own docstring promises
> `clean_sections, clean_data = processor.process(raw_toc)` but the method
> actually `return`s a single list (`payloads`) — unpacking it into two
> values raises `ValueError`. `backend/stage1_document_structure.py`
> avoids this entirely by calling the three numbered methods above
> directly instead of `.process()`.

### `page_analysis.py`
Pure extraction, no interpretation — turns a `fitz.Page` into a
`PageRepresentation`. `PageAnalyzer` (no constructor args):

- `extract_document(doc) -> list[PageRepresentation]` — one call, all
  pages. **What Stage 1 calls.**
- `extract_page(page, page_number) -> PageRepresentation` — raw text
  (`page.get_text("text")`), text blocks (typography via `page.get_text("dict")`,
  bold = PyMuPDF span flag bit `16`), tables (PyMuPDF's native
  `page.find_tables()`), image count, size, and `is_scanned`.
- **`is_scanned` heuristic:** `image_count > 0 and not (raw_text.strip() or text_blocks)`
  — only true when there's at least one image *and* zero extractable text.
  A blank page (no image, no text) is *not* flagged scanned; a page with
  both a logo image and real text never is either.

> **Dead code:** roughly the last 40% of the file is a second class,
> `PDFInspector`, wrapped in a triple-quoted string. It calls
> `normalize_string()`, imported via a commented-out line from `titles.py`
> — a function `titles.py` doesn't actually define — so it wouldn't even
> run if un-commented. Not reachable from any live import.

### `titles.py`
Per-page **title candidates**, scored from typography/position/text
shape — not TOC detection, not segmentation, just "does this text block
look like a heading." `TitleCandidate` (real dataclass: `text`,
`page_number`, `confidence`, `font_size`, `is_bold`, `bbox`, `reasons`).

`TitleDetector(min_title_length=2, max_title_length=200)`:

- `detect(page) -> list[TitleCandidate]` — scores every text block, drops
  rejects, sorts by `(confidence, font_size)` descending. **What Stage 1
  calls**, once per page.
- Scoring (additive, rejected below `0.40`, clamped to `[0, 1]`):

  | signal | weight |
  |---|---|
  | bold | `+0.25` |
  | font size ≥ 16 | `+0.20` |
  | in top 30% of the page | `+0.10` |
  | ≤ 15 words | `+0.20` |
  | starts with a section number (`"3.02 "`, `"A.1 "`) | `+0.15` |
  | looks like a sentence (≥8 words, ends `. , ; :`) | `-0.15` |
  | starts with `warning/caution/danger/note/figure/table/...` | `-0.40` |

### `toc.py` (2000+ lines — the biggest module)
Decides whether a page is a printed/structural **Table of Contents**
(vs. an index, a spec/data table, or ordinary prose) and, if so, parses
its entries. This is what drives the *structural* (non-bookmark) path.

`TOCDetector(toc_score_threshold=0.50)`:

- **`analyze_page(page) -> TOCAnalysis`** — the method Stage 1 actually
  calls, once per page. Collects evidence, scores it, and if `is_toc`,
  tries parsing a structured table first (`extraction_source="table"`)
  and only falls back to line-by-line text parsing
  (`extraction_source="text"`) if the table attempt found nothing.
- `detect_printed_tocs(pages) -> list[TOCRegion]` — groups consecutive
  TOC pages into regions. **Not called from `backend/`** — notebook-only.
  The live path never groups multi-page TOCs; each TOC page's entries are
  used independently by `analyzer.py`.
- `explain_page(page) -> dict` — debugging helper (evidence dump). Not
  called from `backend/` either.

**Evidence collected per page** — multilingual keywords (`"table of
contents"`, `"sommaire"`, `"inhaltsverzeichnis"`, ...; `"index"` is
treated as *ambiguous*, not positive), section-number-pattern line ratio,
dot-leader (`title.....123`) and trailing-page-number line ratios (with a
false-positive guard requiring a real ≥3-letter word so
`"Diametre 25"` isn't mistaken for a TOC line), reference-number
monotonicity, TOC-like vs. data-like table detection, index-style line
ratio, prose-style line ratio, and a position-list pattern
(`"<code> Pos. N"`) that's **computed but never actually used in
scoring** — a hook with no effect yet.

**Scoring** (additive/subtractive, clamped `[0, 1]`, threshold `0.50`):
strong keywords or a document-register header (`+0.15`, mutually
exclusive), a TOC-shaped table (`+0.35`), section-pattern density
(`+0.08` to `+0.15`), page-reference density (`+0.08` to `+0.15`),
reference-number monotonicity (`+0.08` if consistent, `-0.20` if
scrambled), dot leaders (`+0.08`), consistent line structure (`+0.10`),
index-style content (`-0.30 × score`), a data table with no TOC table
(`-0.15`), prose dominance (`-0.10` to `-0.20`), too little structure
overall (`-0.15`).

**PyMuPDF quirk worth knowing:** `_clean_text()` explicitly works around
PyMuPDF inserting raw control characters (`\x02`, `\x03`) where spaces
belong (observed: `"DOCUMENTS\x02&\x02DRAWINGS\x02LIST"`) — replaced with
real spaces. It does *not* fix the separate, unrelated case of missing
whitespace with no control character present at all.

### `analyzer.py`
Turns per-page `TOCAnalysis` + `TitleCandidate` evidence into ordered,
non-overlapping `DocumentSegment`s — the final structural-path output.
`DocumentSegment`: `start_page`, `end_page`, `title`, `section_number`,
`source` (`"toc"` / `"title"` / `"unknown"` / `"fallback"` /
`"preceding_material"`), `confidence`, `evidence`.

`DocumentSegmenter().segment(pages, toc_analyses, title_candidates) -> list[DocumentSegment]`
— what Stage 1 calls on the structural path:

1. **TOC-driven boundaries** — one per `TOCEntry` with a resolvable
   `printed_page_ref`, confidence `0.90`. Entries with
   `reference_kind == "doc_code"` (a drawing/document reference number,
   not a page number) are explicitly skipped, so a code like
   `"P1-REF-2012-123-030"` never gets its first digit run mistaken for a
   PDF page number.
2. **Title-driven boundaries** — the best title candidate per page
   (`max` by confidence, then font size).
3. Same-page boundaries merge; the merged title is simply **the longer of
   the two strings** — a crude tie-break that can occasionally prefer a
   longer-but-worse title over a short, correct one.
4. Segments fill the gaps between boundaries; a document with zero
   boundaries becomes one `source="fallback"` segment (confidence
   `0.10`) spanning everything; content before the first boundary becomes
   a `source="preceding_material"` segment (confidence `0.30`).

`_resolve_printed_page()` is intentionally simple — just the first 1–4
digit run in the reference string — and its own docstring says so: it
does **not** handle "PDF page 15 = printed page 3," roman-numeral front
matter, or real PDF page-label mappings.

> **Known gap:** `DocumentSegment.section_number` is declared but **never
> assigned** anywhere it's constructed — a boundary's section number gets
> mentioned in the evidence text but is never carried into the segment.
> `backend/stage1_document_structure.py::build_from_structure` then does
> `section_number=segment.section_number` when building each
> `CandidateSection` — so **every structurally-derived `CandidateSection`
> has `section_number = None`**, even when the source TOC entry had a
> real one. (Bookmark-path candidates are unaffected — they get their
> section number from `BookmarkProcessor.extract_section_number` instead.)

## How Stage 1 actually uses all of this

```
backend/stage1_document_structure.py :: build_candidate_sections(pdf_path)
 │
 ├─ extract_raw_toc(pdf_path)
 │
 ├─ native bookmarks found?
 │     ├─ yes → BookmarkProcessor().build_clean_structure()
 │     │           .clean_structure_to_bookmark_sections()
 │     │           .bookmark_sections_to_entries()  → list[TOCEntry]
 │     │        → _resolve_bookmark_ranges() → list[CandidateSection]
 │     │
 │     └─ no  → PageAnalyzer().extract_document(doc)   → list[PageRepresentation]
 │              TitleDetector().detect(page) per page   → title candidates
 │              TOCDetector().analyze_page(page) per page → TOCAnalysis list
 │              DocumentSegmenter().segment(...)         → list[DocumentSegment]
 │              → mapped to list[CandidateSection] (source = f"structural:{segment.source}")
 │
 └─ returns (candidates, raw_toc, path_used)
```

`BookmarkProcessor.region_entries_to_payload()` / `.process()` and
`TOCDetector.detect_printed_tocs()` / `.explain_page()` all exist and
work in isolation but **aren't called anywhere on this path** — they
belong to the separate LLM-classification/notebook flow
(`src/llm/classifier.py::classify_sections`) or are debugging helpers.

## Gotchas summary

- `extract_raw_toc`'s docstring describes a shape it doesn't return (flat
  vs. nested) — code is fine, docstring is stale.
- `BookmarkProcessor.process()`'s documented 2-tuple return doesn't match
  its actual single-list return — don't call it expecting
  `clean_sections, clean_data = processor.process(...)`.
- `PDFInspector` (in `page_analysis.py`) and the `TitleCandidate` /
  `DocumentStructure` string literals (in `models.py`) are inert dead
  code left over from the notebook migration — don't import them.
- `TOCDetector`'s position-list evidence is computed but not scored (yet).
- `DocumentSegment.section_number` is always `None` on the structural
  path — a real gap if you need section numbers from title-driven
  segments, not just TOC-driven ones.
- `analyzer.py::_resolve_printed_page` only understands plain printed
  page numbers, not printed-vs-PDF page offsets or roman numerals.
