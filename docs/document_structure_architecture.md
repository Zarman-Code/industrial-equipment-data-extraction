4# Document Structure Analysis Architecture

## 1. Purpose

The document-structure pipeline is an **upstream structural analysis and routing layer** for heterogeneous PDFs.

Its purpose is not only to understand how a PDF is organized. It is also to use that understanding to determine **which pages and sections are likely to contain useful information**, so that expensive downstream techniques such as:

- LLM-based information extraction;
- Named Entity Recognition (NER);
- specialized information extraction;
- OCR enhancement;
- domain-specific extraction;

can be applied **selectively rather than indiscriminately to every page**.

The overall objective is:

```text
PDF
 │
 ├──────────────────────────────┐
 ▼                              ▼
PDF metadata / outline      Page content
(bookmarks)                      │
 │                         ┌─────┴─────┐
 │                         ▼           ▼
 │                      raw text     tables
 │                         │           │
 │                         └─────┬─────┘
 │                               ▼
 │                        page analysis
 │                               │
 └───────────────┬───────────────┘
                 ▼
        Document Architecture
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
    bookmarks   TOCs    headings
        │        │         │
        └────────┼─────────┘
                 ▼
      useful pages / sections
                 │
                 ▼
      targeted expensive extraction
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
       LLM      NER       OCR
                 │
                 ▼
       Structured information
```

The architecture layer should therefore be viewed as both:

1. a **document understanding layer**; and
2. a **computation-allocation / information-routing layer**.

---

# 2. Problem Context

The PDFs targeted by this system are heterogeneous.

They may have:

- different layouts;
- a useful PDF outline/bookmark tree;
- no PDF outline at all;
- incomplete or incorrect bookmarks;
- no global printed TOC;
- printed TOCs that are incomplete;
- nested TOCs;
- TOCs spanning several pages;
- TOCs stored as actual tables;
- TOCs with missing page references;
- page references referring to printed page numbers rather than PDF indices;
- scanned pages;
- OCR errors;
- inconsistent typography;
- headings that are visually obvious but difficult to detect from raw text alone;
- pages called "Index" that are not useful for section discovery;
- meaningful TOCs hidden under titles that do not explicitly contain "TOC" or "Contents".

Because of this variability, the system must combine multiple structural sources.

---

# 3. Core Design Principle

The central architecture is:

```text
PDF
 │
 ├── PDF metadata / outline
 │
 └── page content
       │
       ▼
    extraction
       │
       ▼
   observations
       │
       ▼
page-level structural analysis
       │
       ▼
sequence/document-level reasoning
       │
       ▼
document architecture
       │
       ▼
page / section selection
       │
       ▼
targeted downstream extraction
```

The important principle is:

> **Use every reliable structural signal that is available, but never assume that one source is complete or correct.**

In particular:

- bookmarks can provide structure without page-content analysis;
- TOCs can provide explicit section relationships;
- headings can provide structure when bookmarks/TOCs are absent or incomplete;
- tables can preserve information that raw text extraction destroys;
- layout and typography provide additional evidence.

---

# 4. Two Main Structural Sources

The architecture should explicitly distinguish between:

## Source A: PDF metadata / outline

Many PDFs contain an internal document outline, commonly exposed to users as:

```text
Bookmarks
```

or:

```text
PDF outline
```

For example:

```text
1 Introduction
2 Safety
3 Installation
    3.1 Mechanical Installation
    3.2 Electrical Installation
4 Maintenance
```

This can provide:

- section titles;
- hierarchy;
- bookmark depth;
- destination pages;
- structural relationships.

When present and reliable, this is extremely valuable because the structure can be obtained without discovering every section from page content.

---

## Source B: Page content

When the PDF outline is absent, incomplete, or unreliable, the system must infer structure from the actual pages.

Page content includes:

```text
raw text
+
tables
+
text blocks
+
text spans
+
layout
+
typography
```

From this, the system can discover:

- printed TOCs;
- TOC continuation pages;
- headings;
- section numbering;
- document boundaries;
- tables;
- other structural signals.

The two sources should therefore complement one another.

---

# 5. Bookmarks / PDF Outline

Bookmarks should be treated as a **first-class structural input**.

A PDF outline can contain a hierarchical tree:

```text
Document
├── Introduction
├── Safety
├── Installation
│   ├── Mechanical Installation
│   └── Electrical Installation
└── Maintenance
```

Each bookmark may also have a destination pointing to a PDF page.

A conceptual representation is:

```python
BookmarkEntry(
    title="Electrical Installation",
    level=2,
    page_number=47,
    children=[...],
)
```

The exact representation may differ, but the following information is important:

```text
title
level / hierarchy
destination
source
children
```

---

# 6. Why Bookmarks Are Valuable

Bookmarks can provide structure much more cheaply than reconstructing it from page content.

For example:

```text
Bookmark:
3 Installation
    3.1 Mechanical
    3.2 Electrical
```

may immediately provide candidate section boundaries.

This can be used to route downstream extraction:

```text
Bookmark structure
      ↓
candidate section
      ↓
page range
      ↓
LLM / NER
```

without first having to infer the section solely from page typography.

Bookmarks are therefore an important **high-value structural signal**.

---

# 7. Raw Text + Tables

A PDF page can encode the same visual information in very different ways.

A TOC may appear as:

```text
1 Introduction ............... 3
1.1 Scope .................... 4
1.2 Safety ................... 5
```

or as a table:

```text
+------+----------------+------+
| 1    | Introduction   | 3    |
| 1.1  | Scope          | 4    |
| 1.2  | Safety         | 5    |
+------+----------------+------+
```

Raw text extraction may flatten the second representation into:

```text
1 Introduction 3 1.1 Scope 4 1.2 Safety 5
```

which loses useful column information.

Therefore the page representation must retain both:

```text
raw_text
+
tables
```

The table representation is not a replacement for raw text.

Both are independent evidence sources.

---

# 8. Page-Level Representation

Each PDF page should be represented by a structured object containing the observations needed by later stages.

Conceptually:

```python
PageRepresentation(
    page_number=...,
    raw_text=...,
    text_blocks=...,
    text_spans=...,
    tables=...,
    images=...,
    layout=...,
)
```

The exact model can evolve.

The important requirement is that downstream analysis should not need to reopen the PDF or repeat extraction.

This makes the pipeline:

- faster;
- easier to test;
- easier to debug;
- easier to benchmark;
- easier to explain.

---

# 9. PyMuPDF as the Extraction Layer

PyMuPDF is used as the primary PDF inspection/extraction library.

The extraction layer should collect, where available:

- raw page text;
- text blocks;
- text spans;
- font size;
- font flags/style information;
- bounding boxes;
- tables;
- page dimensions;
- basic layout information;
- PDF outline/bookmarks.

The extraction layer should not decide:

```text
"This is a TOC."
```

It should report observations.

Interpretation belongs to the structural-analysis layer.

---

# 10. TOC Detection Is an Evidence Problem

TOC detection should not be based on one keyword.

For example:

```text
TABLE OF CONTENTS
```

is useful evidence.

But:

```text
INDEX
```

does not necessarily mean that the page contains a useful section TOC.

Conversely:

```text
FINAL DOCUMENTATION
```

does not sound like a TOC title, but the page may contain a very clear TOC table.

Therefore semantic labels are only one evidence family.

The page's actual structure must also be analyzed.

---

# 11. Positive TOC Evidence

The detector should collect multiple categories of positive evidence.

## 11.1 Explicit TOC terminology

Examples:

```text
Table of Contents
Contents
Sommaire
Inhaltsverzeichnis
```

These are useful supporting signals.

They should not automatically classify a page as a TOC.

## 11.2 TOC-like table structure

A table such as:

```text
Section | Title          | Page
1       | Introduction   | 3
1.1     | Scope          | 4
1.2     | Safety         | 5
2       | Installation   | 8
```

is strong evidence.

The detector should inspect:

- row count;
- column count;
- section-like cells;
- page-reference cells;
- repeated row structure;
- title-like cells;
- consistency across rows.

## 11.3 Section hierarchy

Repeated patterns such as:

```text
1
1.1
1.2
2
2.1
2.2
```

are strong evidence of a TOC-like structure.

A single section heading is not sufficient.

## 11.4 Printed page references

Repeated page references are strong evidence.

A single:

```text
See page 45
```

is not.

## 11.5 Dot leaders and alignment

Patterns such as:

```text
Introduction ............ 3
Installation ............ 8
```

are useful evidence.

## 11.6 Entry-like density

TOCs tend to contain many short, similarly structured entries rather than long prose paragraphs.

---

# 12. Negative Evidence

The detector must explicitly model evidence against the TOC hypothesis.

The detector should ask both:

> Why could this be a TOC?

and:

> Why might this NOT be a TOC?

Negative evidence includes:

- index-like structure;
- ordinary data-table structure;
- prose dominance;
- insufficient structural repetition;
- figure/drawing-like structure;
- other false-positive patterns discovered during evaluation.

---

# 13. Index-vs-TOC Distinction

An important false-positive class is a page titled:

```text
INDEX
```

An index can contain:

```text
pump, 45, 47, 52
valve, 18, 31
```

This is structurally different from:

```text
1 Introduction
1.1 Scope
1.2 Safety
2 Installation
```

Therefore:

```text
INDEX
```

should be treated as an **ambiguous semantic hint**, not strong TOC evidence.

Index-like evidence should reduce TOC confidence.

This distinction is especially important because an index may contain many page references but still be of little or no value for document segmentation.

---

# 14. Data-Table Negative Evidence

Not every table is a TOC.

For example:

```text
Part No. | Description | Quantity | Material
1234     | Valve       | 4        | Steel
```

is a data table.

A page can therefore have:

```text
table detected = True
```

without:

```text
TOC = True
```

The detector should distinguish:

```text
TOC-like table
```

from:

```text
ordinary data table
```

using structural evidence.

---

# 15. Explainable TOC Analysis

The detector should preserve evidence rather than returning only:

```python
is_toc = True
confidence = 0.91
```

Conceptually:

```python
TOCAnalysis(
    is_toc=True,
    confidence=0.91,

    evidence={
        "positive": {
            "strong_toc_keywords": [...],
            "section_structure": {...},
            "page_references": {...},
            "dot_leaders": {...},
            "toc_tables": [...],
            "layout_consistency": {...},
        },

        "negative": {
            "ambiguous_keywords": [...],
            "index_like_structure": {...},
            "data_table_structure": {...},
            "prose_dominance": {...},
            "insufficient_structure": {...},
        },
    },
)
```

This is required for:

- debugging;
- notebook analysis;
- threshold tuning;
- evaluation;
- error analysis.

---

# 16. Page-Level Scoring

The detector may use a confidence score, but it should be derived from evidence families.

```text
Positive evidence
    ├── semantic
    ├── table structure
    ├── section hierarchy
    ├── page references
    ├── layout consistency
    └── entry density

Negative evidence
    ├── index-like structure
    ├── data-table structure
    ├── prose dominance
    └── insufficient structure

                    ↓

             TOC likelihood
```

The exact numerical weights should be validated against real PDFs.

---

# 17. Table-First TOC Parsing

Once a page is considered a TOC candidate, entry extraction should prefer the structured table representation when a TOC-like table exists.

```text
TOC candidate
   │
   ├── TOC-like table exists
   │        ↓
   │     parse table
   │
   └── no usable table
            ↓
         parse raw text
```

This avoids the problem where table columns are destroyed by text extraction.

Text Parsing Remains Necessary because:

- some TOCs are not actual tables;
- some PDFs have poor table extraction;
- scanned pages may contain OCR text;
- some layouts use dot leaders;
- some documents use unusual formatting.

Therefore:

```text
table-first
+
text fallback
```

---

# 18. TOC Entries

A TOC entry should preserve at least:

```text
text
section_number
level
printed_page_ref
source_page
confidence
```

For example:

```python
TOCEntry(
    text="Safety Requirements",
    section_number="2.1",
    level=2,
    printed_page_ref="14",
    source_page=7,
)
```

The `printed_page_ref` is explicitly not assumed to equal the PDF page index.

---

# 19. Printed Page Numbers vs PDF Page Numbers

A TOC may say:

```text
Installation ........ 25
```

while the actual PDF page index is:

```text
PDF page 31
```

because of covers, front matter, inserts, or different numbering systems.

Therefore TOC extraction should preserve:

```text
printed_page_ref
```

rather than silently converting it into a PDF page index.

Mapping printed references to PDF pages should be a later validation/resolution step.

---

# 20. TOC Containers and Continuation Pages

A TOC should not necessarily be considered a single page.

Example:

```text
Page 6 → TOC
Page 7 → TOC continuation
Page 8 → normal content
```

Page 7 may not contain:

```text
Table of Contents
```

but may still have:

- the same table structure;
- the same columns;
- repeated entry patterns;
- section hierarchy;
- page references.

Therefore sequence-level reasoning should group adjacent TOC-like pages into a **TOC container**.

---

# 21. Nested TOCs

Large documents may contain:

```text
Main TOC
    ├── Section 1
    ├── Section 2
    └── Section 3

Section 3 detailed TOC
    ├── 3.1
    ├── 3.2
    └── 3.3
```

The system should not automatically treat every detected TOC as a document boundary.

Instead:

```text
TOC detection
      ↓
TOC entries
      ↓
hierarchy
      ↓
candidate section boundaries
      ↓
validation
      ↓
segmentation
```

---

# 22. Heading / Title Detection

TOC and bookmark analysis are only part of the structural picture.

The system also needs to identify likely section titles in actual content.

Useful signals include:

- relative font size;
- font weight/style;
- text position;
- whitespace;
- numbering pattern;
- short text blocks;
- repeated heading formatting;
- proximity to page boundaries;
- relationship to TOC entries;
- relationship to bookmarks.

Typography should be treated relatively rather than using one global font-size threshold.

---

# 23. Cross-Validation of Bookmarks, TOCs, and Headings

The strongest structure often occurs when independent sources agree.

Example:

```text
Bookmark:
2.1 Safety Requirements → page 18

TOC:
2.1 Safety Requirements → printed page 14

Actual heading:
2.1 Safety Requirements → PDF page 18
```

This provides strong structural evidence.

Another example:

```text
Bookmark:
3 Installation

TOC:
3 Installation

Actual pages:
heading "3 Installation"
```

Again, independent agreement increases confidence.

The system should therefore preserve the provenance of structural claims:

```text
source = bookmark
source = printed_toc
source = detected_heading
source = inferred
```

---

# 24. Document Segmentation

The final segmentation stage should combine:

```text
bookmarks / PDF outline
+
TOC evidence
+
TOC entries
+
actual content headings
+
page-level layout signals
+
sequence continuity
+
validation
```

A TOC or bookmark should therefore be treated as **evidence for segmentation**, not segmentation truth by itself.

---

# 25. Document Architecture as a Routing Layer

Once the document structure is known, the system can identify useful pages or sections for downstream tasks.

For example:

```text
PDF
 │
 ▼
Bookmarks / TOC / headings / page analysis
 │
 ▼
Document architecture
 │
 ├── Section A
 ├── Section B
 ├── Section C
 └── Section D
 │
 ▼
Task-specific relevance
 │
 ▼
Candidate pages / sections
 │
 ▼
LLM / NER / specialized extraction
```

This is the key computational purpose of the architecture.

---

# 26. Why This Matters Computationally

Suppose a PDF contains 500 pages.

Applying an expensive LLM or NER pipeline to every page means:

```text
500 pages
   ↓
expensive extraction
```

Instead:

```text
500 pages
   ↓
cheap structural analysis
   ↓
document architecture
   ↓
87 candidate pages
   ↓
expensive extraction
```

The structural layer can reduce:

- computation;
- latency;
- API calls;
- model usage;
- cost;
- irrelevant results.

This is a **cheap-first, expensive-later** strategy.

---

# 27. Bookmarks Can Make Routing Even Cheaper

If a PDF already contains a reliable outline:

```text
Equipment A
    ├── Specifications
    ├── Installation
    └── Maintenance

Equipment B
    ├── Specifications
    └── Maintenance
```

the system can immediately obtain candidate section ranges.

There is no reason to rediscover all of this structure from page content if the bookmark information is reliable.

Therefore:

> **Use bookmarks first when available, then validate/enrich them with page-content analysis as needed.**

This does not mean skipping page analysis globally, because page content may still be needed for:

- validating bookmarks;
- detecting missing sections;
- finding TOCs;
- identifying useful tables;
- identifying actual headings;
- supporting downstream relevance decisions.

---

# 28. Target-Aware Selection

The architecture should remain generic.

It should not hard-code one downstream task.

A downstream task may request:

- equipment specifications;
- maintenance intervals;
- part numbers;
- safety requirements;
- procedures;
- dates;
- standards;
- warnings;
- personnel roles;
- technical entities.

The architecture should therefore produce reusable structural units:

```text
documents
sections
subsections
pages
tables
headings
bookmarks
TOC entries
```

A downstream component can then determine which units are relevant.

---

# 29. Downstream Extraction Granularity

Once architecture is available, downstream extraction can operate at different levels.

## Page-level

```text
candidate page
    ↓
LLM / NER
```

## Section-level

```text
candidate section
    ↓
section pages
    ↓
LLM / NER
```

## Section + context

```text
target section
+
neighboring/context pages
    ↓
LLM / NER
```

The architecture should support all three.

---

# 30. Do Not Permanently Discard Pages

Structural analysis should help select useful content, but it should not become an irreversible filter.

A page that initially appears irrelevant may become useful when:

- the downstream task changes;
- an entity is referenced elsewhere;
- context from neighboring pages is required;
- a table continues onto another page;
- a section depends on introductory material.

Therefore the system should preserve the complete page-level representation.

The routing layer should produce candidates and relevance information rather than deleting pages.

---

# 31. Validation

Structural decisions should be validated rather than blindly trusted.

Useful checks include:

- Does a bookmark destination contain a compatible heading?
- Does a TOC entry correspond to an actual heading?
- Does the section numbering make sense?
- Does hierarchy remain consistent?
- Are page references plausible?
- Are duplicate/conflicting boundaries present?
- Does the detected section span a plausible number of pages?
- Do neighboring pages exhibit compatible structure?

Validation can:

- increase confidence;
- decrease confidence;
- flag a result;
- trigger a broader search.

---

# 32. Source Architecture

## `page_analysis.py`

Responsible for:

- PyMuPDF page inspection;
- raw text extraction;
- text blocks/spans;
- table extraction;
- page geometry;
- layout metadata;
- creation of `PageRepresentation`.

It should not decide document structure.

---

## `metadata.py`

Responsible for PDF-level structural metadata, especially:

- PDF outline;
- bookmarks;
- bookmark hierarchy;
- bookmark destinations;
- bookmark-to-page relationships;
- normalized bookmark entries.

It should not perform final segmentation.

---

## `toc.py`

Responsible for:

- TOC evidence;
- positive/negative signals;
- TOC-vs-index reasoning;
- TOC-like table analysis;
- TOC entry parsing;
- printed page references;
- explainable confidence;
- TOC continuation evidence.

---

## `headings.py`

Responsible for:

- candidate heading detection;
- typography/layout signals;
- section-number extraction;
- title normalization;
- heading confidence;
- relationships between heading candidates and structural sources.

---

## `segmentation.py`

Responsible for:

- combining bookmarks, TOCs, and headings;
- sequence reasoning;
- grouping TOC continuation pages;
- resolving candidate boundaries;
- handling nested structures;
- constructing document/section segments;
- exposing candidate page/section units for downstream extraction.

---

## `models.py`

Responsible for shared data structures such as:

```text
PageRepresentation
TextBlock
TextSpan
TableRepresentation
BookmarkEntry
TOCEntry
TOCAnalysis
TOCContainer
HeadingCandidate
Section
DocumentSegment
```

The models should remain primarily data-oriented.

---

# 33. Evaluation Strategy

The architecture should be evaluated at several levels.

## Level 1 — PDF metadata extraction

Are bookmarks correctly extracted?

## Level 2 — Page extraction

Are raw text and tables extracted correctly?

## Level 3 — TOC detection

Are TOC pages detected?

Are index pages rejected?

Are ordinary data tables rejected?

## Level 4 — TOC parsing

Are entries, hierarchy, and printed page references extracted correctly?

## Level 5 — Heading detection

Are actual section headings detected?

## Level 6 — Cross-source validation

Do bookmarks, TOCs, and headings agree where they should?

## Level 7 — Segmentation

Are section boundaries correctly inferred?

## Level 8 — Routing

Does the architecture select useful pages for downstream extraction?

## Level 9 — Downstream efficiency

Does selective extraction reduce:

- pages processed;
- LLM calls;
- runtime;
- cost;

without significantly reducing information-retrieval quality?

---

# 34. Important Metrics

Useful metrics include:

### Bookmark extraction

```text
bookmark tree accuracy
destination accuracy
hierarchy accuracy
```

### TOC detection

```text
precision
recall
F1
```

### TOC entry extraction

```text
entry precision
entry recall
section-number accuracy
printed-page-reference accuracy
```

### Segmentation

```text
boundary precision
boundary recall
boundary distance error
```

### Downstream routing

```text
candidate-page recall
irrelevant-page reduction
LLM-call reduction
cost reduction
runtime reduction
```

The final group is especially important because the architecture exists partly to make downstream extraction more efficient.

------

# 35. Central Idea

The complete strategy can be summarized as:

> **Use PDF-native structure such as bookmarks when available, enrich and validate it using page-level text, tables, layout, TOCs, and headings, reason across pages to construct a document architecture, and use that architecture to selectively route useful pages or sections to expensive downstream extraction such as LLMs or NER.**

This makes document-structure analysis both a **document understanding mechanism** and an **efficient information-extraction strategy**.
