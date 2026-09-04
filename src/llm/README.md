# `src/llm/` LLM module overview

Thin OpenAI wrappers used by two different stages of the pipeline:
**Stage 2** (`classifier.py` — which sections are worth extracting from)
and **Stage 3** (`extractor.py` — pull structured equipment fields out of
a section's text). Both use the Chat Completions **structured outputs**
API (`client.beta.chat.completions.parse(..., response_format=<pydantic model>)`)
so the response is guaranteed to match a schema instead of being
free-form text that needs manual JSON parsing.

## Files

### `config.py`
Loads `.env` (via `python-dotenv`) and exposes:

- `OPENAI_API_KEY` — from the environment; `None` if not set.
- `LLM_MODEL` — `"gpt-4o-mini"`, used by both `classifier.py` and
  `extractor.py`.
- `ENABLE_LLM` — hardcoded `True`.

**Importing this module raises `ValueError("OPENAI_API_KEY is not
configured.")` if `ENABLE_LLM` is `True` and no key is set** — there's no
soft-disable path. Since `classifier.py` and `extractor.py` both import
from here at module load time, anything that imports either of them
(directly or transitively, e.g. `backend/stage2_section_classification.py`,
`backend/stage3_information_extraction.py`) will fail to import without a
configured `OPENAI_API_KEY`.

### `schemas.py`
Pydantic models used as `response_format` for both stages, plus the
per-field shape everything else is built from:

- `FieldExtraction` — `{value, confidence (0-1), page}`. One extracted
  field, with its own confidence and source page.
- `LLMExtraction` — the **single-machine** extraction result: `family`,
  `asset_name`, `reference`, `power`, `outlier`, `manufacturer`,
  `asset_diagram`, each a `FieldExtraction`. This is what `extractor.py`
  currently uses.
- `MachineFields` — identical fields to `LLMExtraction`; kept as a
  separate name so a machine's field bundle reads clearly inside
  `MachineExtraction`.
- `MachineExtraction` / `MachineExtractionResult` — the **multi-machine**
  shape (`machine_id`, optional `name`, `fields: MachineFields`, wrapped
  in `{"machines": [...]}`). Defined for documents describing several
  pieces of equipment, but **not currently used by `extractor.py`** — see
  `MULTI_MACHINE_EXTRACTION_PROMPT` below.
- `SectionClassification` / `SectionClassificationResult` — Stage 2's
  output: per-section `{section_id, relevance_score (0-100), reason,
  potential_information}`, plus a top-level `selected_sections: List[str]`
  (every `section_id` with `relevance_score >= 50`).

### `prompts.py`
Three prompt templates, all `"""..."""` string constants:

- `LLM_INSTRUCTIONS` — Stage 3's actual prompt (used by `extractor.py`).
  Single-machine, paired with `LLMExtraction`. Deliberately **zero-inference**:
  "Never infer, guess, calculate, or complete missing information", and
  explicitly forbids inferring i-Sense classifications (Family, Class,
  Structure, Group, Entity) — a field not literally stated in the source
  must come back `null`. (Family is later filled in as a *separate*,
  non-LLM step — see `backend/family_matcher.py` — specifically so this
  strict-extraction guarantee isn't compromised.)
- `MULTI_MACHINE_EXTRACTION_PROMPT` — same rules, but paired with
  `MachineExtractionResult`/`MachineFields` to extract several distinct
  machines from one section in a single call. **Defined but not imported
  anywhere** — `extractor.py` still uses `LLM_INSTRUCTIONS`/`LLMExtraction`.
  Swap it in if a document section can describe more than one machine and
  single-machine extraction is merging/dropping data.
- `SECTION_CLASSIFICATION_PROMPT` — Stage 2's prompt (used by
  `classifier.py`). Scores every section 0-100 for "how likely is this to
  contain equipment info" and returns `selected_sections` for
  `relevance_score >= 50`. Ends with a `{{INPUT_JSON}}` placeholder that
  the caller substitutes the real payload into (see `classifier.py` below)
  — never send this prompt to the model unsubstituted.

### `classifier.py`
```python
def classify_sections(document_sections: list[dict]) -> SectionClassificationResult
```
Stage 2. Takes a list of `{section_id, title, section_number, page_start,
level}` dicts (one per candidate section — no page content, just
metadata), substitutes them into `SECTION_CLASSIFICATION_PROMPT` in place
of `{{INPUT_JSON}}`, and sends **one single request scoring every section
at once**. For a document with a very large table of contents this means
one large request — the caller is responsible for capping/batching if
needed (`backend/stage2_section_classification.py` doesn't currently cap
it).

Module-level `client = OpenAI(api_key=OPENAI_API_KEY or "sk-disabled-placeholder")`
— the placeholder string exists purely so importing the module doesn't
crash when `OPENAI_API_KEY` is unset; **the actual call still fails** at
that point (an invalid key), it just fails at call time instead of import
time.

### `extractor.py`
```python
def extract_with_llm(payload: str | dict) -> dict
```
Stage 3. Takes the combined text+tables content for one section
(`get_text()` accepts either a raw string or a `{"text": ...}` dict),
sends it with `LLM_INSTRUCTIONS` as the system prompt and the payload as
the user message, and returns:

```python
{"method": "llm", "called": True,  "result": LLMExtraction.model_dump()}   # success
{"method": "llm", "called": False, "error": "<exception message>"}          # OpenAI call raised
{"method": "llm", "called": False, "message": "LLM disabled"}               # ENABLE_LLM is False
```
The third shape is currently unreachable in practice since `config.py`
hardcodes `ENABLE_LLM = True` and would already have raised at import if
no key were set — kept for when/if `ENABLE_LLM` becomes configurable.

Unlike `classifier.py`, this module does **not** use the disabled-key
placeholder — `client = OpenAI(api_key=OPENAI_API_KEY)` — but by the time
this import runs, `config.py` has already guaranteed `OPENAI_API_KEY` is
set (or raised).

## How to use it

### Stage 2 — classify candidate sections

```python
from src.llm.classifier import classify_sections

sections = [
    {"section_id": "bm_3", "title": "3.02 Compressor Data Sheet",
     "section_number": "3.02", "page_start": "107", "level": 2},
    # ...
]

result = classify_sections(sections)   # SectionClassificationResult

result.selected_sections          # ["bm_3", ...] — relevance_score >= 50
for s in result.sections:
    s.section_id, s.relevance_score, s.reason, s.potential_information
```

### Stage 3 — extract fields from one section's content

```python
from src.llm.extractor import extract_with_llm

content = "--- PAGE 107 ---\n...native text...\n\n===== TABLES =====\n..."

out = extract_with_llm(content)

if out["called"]:
    fields = out["result"]           # dict, shaped like LLMExtraction
    fields["asset_name"]["value"]
    fields["family"]["value"]        # usually null — see family_matcher.py
else:
    out.get("error") or out.get("message")
```

## Notes / gotchas

- **No request timeout or retry policy is set on either `OpenAI(...)`
  client.** A stalled network call hangs indefinitely rather than failing
  fast — add `timeout=` (and optionally `max_retries=`) to the `OpenAI(...)`
  constructor in both files if this bites you.
- **Both clients are instantiated at import time**, not per-call — importing
  `classifier.py` or `extractor.py` immediately requires a working
  `OPENAI_API_KEY` (or, for `classifier.py` only, silently uses the
  disabled placeholder and fails on first real call).
- `family` almost always comes back `null` from `extractor.py` by design
  (rule 3 in `LLM_INSTRUCTIONS`) — that's expected, not a bug. See
  `backend/family_matcher.py` for how it gets filled in afterwards.
- `classify_sections()` sends **all** candidate sections in one request;
  a document with hundreds of sections can produce a very large prompt/response
  (`gpt-4o-mini` caps output at 16,384 tokens) — batch the input yourself
  if you hit truncation or slow responses.
