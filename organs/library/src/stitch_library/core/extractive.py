"""LLM-free answers (design 7.5). Deterministic.

From the top 2 hits that passed the evidence gate, score every sentence (reranker on
``(query, sentence)`` when available, else query-term overlap), keep up to 3 sentences that share
at least one content term with the query and score at least half of the best, and make each one a
claim whose text is the sentence itself, cited to itself. Extractive claims pass the same
verification as LLM claims.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from stitch_library.core.answer import DraftClaim, Support
from stitch_library.core.normalize import search_text
from stitch_library.core.scope import query_terms
from stitch_library.core.sentences import BULLETS, split_sentences
from stitch_library.core.tokenize import concept_tokens
from stitch_library.store.base import ChunkRow

N_CHUNKS = 2
MAX_CLAIMS = 3


@dataclass(frozen=True)
class Candidate:
    chunk: ChunkRow
    start: int  # page offsets
    end: int
    text: str
    overlap: float
    rank: int


_LEAD = BULLETS + " \t"
_TERMINAL = ".!?۔؟):"


def is_heading(text: str) -> bool:
    """Short line without terminal punctuation (a section title, not a statement)."""
    return len(text.split()) < 4 and not text.rstrip("\"'”’").endswith(tuple(_TERMINAL))


def sentence_candidates(query: str, chunks: Sequence[ChunkRow]) -> list[Candidate]:
    """Sentences of ``chunks`` with page offsets; leading bullets are excluded from the span."""
    terms = query_terms(query)
    out: list[Candidate] = []
    for ch in chunks:
        for s, e in split_sentences(ch.text):
            while s < e and ch.text[s] in _LEAD:
                s += 1
            text = ch.text[s:e]
            if not text or is_heading(text):
                continue
            toks = concept_tokens(search_text(text))
            overlap = len(terms & toks) / len(terms) if terms else 0.0
            out.append(Candidate(ch, ch.start + s, ch.start + e, text, overlap, len(out)))
    return out


def extractive_claims(
    query: str,
    chunks: Sequence[ChunkRow],
    scorer: Callable[[str, list[str]], list[float]] | None = None,
    prefer: Callable[[str], bool] | None = None,
) -> list[DraftClaim]:
    """``prefer``: when some candidate sentences satisfy it (for a quantity question: the
    sentence states the asked quantity), only those are kept."""
    cands = [c for c in sentence_candidates(query, chunks[:N_CHUNKS]) if c.overlap > 0]
    if prefer is not None:
        preferred = [c for c in cands if prefer(c.text)]
        cands = preferred or cands
    if not cands:
        return []
    scores: list[float]
    if scorer is not None:
        try:
            raw = scorer(query, [c.text for c in cands])
            scores = [1.0 / (1.0 + math.exp(-x)) for x in raw]
        except Exception:
            scores = [c.overlap for c in cands]
    else:
        scores = [c.overlap for c in cands]
    best = max(scores)
    ranked = sorted(zip(scores, cands, strict=True), key=lambda x: (-x[0], x[1].rank))
    kept = [c for s, c in ranked if s >= best / 2][:MAX_CLAIMS]
    kept.sort(key=lambda c: c.rank)
    return [
        DraftClaim(c.text, (Support(c.chunk.doc_id, c.chunk.page, c.start, c.end),)) for c in kept
    ]
