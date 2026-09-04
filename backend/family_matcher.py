"""
Family normalization for Stage 3.

`src.llm.extractor` only returns `family` when it is EXPLICITLY stated in
the document (its rules forbid inference). This module fills the gap: it
maps an asset's raw family text / name / reference onto the canonical
i-Sense family catalog in ``data/reference/families.json``.

Matching ladder (cheapest first):

    1. exact / normalized string match          (offline)
    2. fuzzy string match                        (stdlib difflib + token overlap, offline)
    3. semantic match                            (text-embedding-3-small, ONE batched call per document)

Anything below threshold stays unmatched (``family_source == "unmatched"``)
so it can be reviewed by a human.

Nothing here calls a chat LLM. The only network call is a single batched
embeddings request, and only for the queries that steps 1-2 could not
resolve. Family-list embeddings are cached on disk
(``backend/_family_embeddings.json``) and only recomputed when the list
changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
PROJECT_ROOT = _HERE.parent
FAMILIES_PATH = PROJECT_ROOT / "data" / "reference" / "families.json"
EMBED_CACHE_PATH = _HERE / "_family_embeddings.json"

EMBED_MODEL = "text-embedding-3-small"

# Tunables
FUZZY_THRESHOLD = 0.72
SEMANTIC_THRESHOLD = 0.42

_NOISE_WORDS = {
    "data", "sheet", "datasheet", "schedule", "technical", "unit",
    "assembly", "type", "spec", "specification", "list", "of",
    "the", "and", "for", "no", "nr", "ref", "model",
}


# --------------------------------------------------------------------------
# family list
# --------------------------------------------------------------------------
_families_cache: list[str] | None = None


def load_families() -> list[str]:
    """Load the canonical family names from families.json (cached)."""

    global _families_cache

    if _families_cache is not None:
        return _families_cache

    try:
        data = json.loads(FAMILIES_PATH.read_text(encoding="utf-8"))
        families = [str(x).strip() for x in data.get("families", []) if str(x).strip()]
    except Exception as exc:
        logger.warning("Could not read %s: %s", FAMILIES_PATH, exc)
        families = []

    _families_cache = families
    return families


# --------------------------------------------------------------------------
# normalization + offline scoring
# --------------------------------------------------------------------------
def _normalize(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)        # drop "(new)" etc.
    text = re.sub(r"[^a-z0-9\s]", " ", text)       # drop punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(text: str) -> set[str]:
    out = set()
    for tok in _normalize(text).split():
        if tok in _NOISE_WORDS:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]                          # crude singularization
        out.add(tok)
    return out


def _fuzzy_score(query: str, family: str) -> float:
    """Offline similarity in [0, 1] between a query string and a family name."""

    nq, nf = _normalize(query), _normalize(family)
    if not nq or not nf:
        return 0.0
    if nq == nf:
        return 1.0

    seq = SequenceMatcher(None, nq, nf).ratio()

    qt, ft = _tokens(query), _tokens(family)
    if not qt or not ft:
        return seq

    jaccard = len(qt & ft) / len(qt | ft)

    # how much of the family name is contained in the query
    # ("screw compressor" fully present inside "screw compressor 101").
    # Trust this less for one-word families ("Pump", "Compressor"),
    # which are too easy to spuriously find inside a longer asset name.
    contain = len(qt & ft) / len(ft)
    contain_weight = 0.9 if len(ft) >= 2 else 0.6

    return max(seq, jaccard, contain * contain_weight)


def _best_fuzzy(query: str, families: list[str]) -> tuple[str | None, float]:
    best, best_score = None, 0.0
    for fam in families:
        s = _fuzzy_score(query, fam)
        if s > best_score:
            best, best_score = fam, s
    return best, best_score


# --------------------------------------------------------------------------
# semantic (embeddings) fallback
# --------------------------------------------------------------------------
def _embed(texts: list[str]) -> list[list[float]] | None:
    """Batched embeddings call. Returns None if unavailable."""

    try:
        from src.llm.config import OPENAI_API_KEY

        if not OPENAI_API_KEY:
            logger.warning("Family semantic match skipped: no OPENAI_API_KEY.")
            return None

        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]
    except Exception as exc:
        logger.warning("Family semantic match skipped: %s", exc)
        return None


def _family_vectors(families: list[str]) -> list[list[float]] | None:
    """Embeddings for the family list, cached on disk keyed by list hash."""

    key = hashlib.sha1(
        (EMBED_MODEL + "|" + "|".join(families)).encode("utf-8")
    ).hexdigest()

    try:
        cached = json.loads(EMBED_CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return cached["vectors"]
    except Exception:
        pass

    vectors = _embed(families)
    if vectors is None:
        return None

    try:
        EMBED_CACHE_PATH.write_text(
            json.dumps({"key": key, "model": EMBED_MODEL, "vectors": vectors}),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not write %s: %s", EMBED_CACHE_PATH, exc)

    return vectors


def _cosine_matrix(queries: list[list[float]], targets: list[list[float]]):
    import numpy as np

    q = np.asarray(queries, dtype="float32")
    t = np.asarray(targets, dtype="float32")
    q /= (np.linalg.norm(q, axis=1, keepdims=True) + 1e-9)
    t /= (np.linalg.norm(t, axis=1, keepdims=True) + 1e-9)
    return q @ t.T


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def _query_text(q: dict[str, Any]) -> str:
    parts = [
        q.get("family_raw"),
        q.get("asset_name"),
        q.get("reference"),
        q.get("section_title"),
    ]
    return " ".join(str(p) for p in parts if p).strip()


def match_batch(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Map each query onto a canonical family.

    Each query is a dict with any of:
        asset_name, reference, family_raw, section_title

    Returns, positionally, a dict per query:
        {"family": <canonical or None>,
         "family_source": "stated" | "fuzzy" | "semantic" | "unmatched",
         "family_score": float}
    """

    families = load_families()
    results: list[dict[str, Any]] = [
        {"family": None, "family_source": "unmatched", "family_score": 0.0}
        for _ in queries
    ]

    if not families or not queries:
        return results

    fam_norm = {_normalize(f): f for f in families}

    pending: list[int] = []

    # steps 1 + 2: exact / normalized / fuzzy
    for i, q in enumerate(queries):
        raw = (q.get("family_raw") or "").strip()
        name = (q.get("asset_name") or "").strip()

        if raw and _normalize(raw) in fam_norm:
            results[i] = {
                "family": fam_norm[_normalize(raw)],
                "family_source": "stated",
                "family_score": 1.0,
            }
            continue

        probe = raw or name
        best, score = _best_fuzzy(probe, families)
        if best and score >= FUZZY_THRESHOLD:
            results[i] = {
                "family": best,
                "family_source": "fuzzy",
                "family_score": round(score, 3),
            }
        else:
            pending.append(i)

    # step 3: semantic, one batched embeddings call for everything left
    if pending:
        fam_vecs = _family_vectors(families)
        if fam_vecs is not None:
            q_vecs = _embed([_query_text(queries[i]) for i in pending])
            if q_vecs is not None:
                sims = _cosine_matrix(q_vecs, fam_vecs)
                for row, i in enumerate(pending):
                    j = int(sims[row].argmax())
                    score = float(sims[row][j])
                    if score >= SEMANTIC_THRESHOLD:
                        results[i] = {
                            "family": families[j],
                            "family_source": "semantic",
                            "family_score": round(score, 3),
                        }

    return results


def match_one(
    asset_name: str | None = None,
    reference: str | None = None,
    family_raw: str | None = None,
    section_title: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper around match_batch for a single asset."""

    return match_batch([{
        "asset_name": asset_name,
        "reference": reference,
        "family_raw": family_raw,
        "section_title": section_title,
    }])[0]
