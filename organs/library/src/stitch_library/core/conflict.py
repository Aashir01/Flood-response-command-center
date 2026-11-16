"""Conflicting-evidence detector (design 8.6). Pure, heuristic, with known false negatives.

For the top hits that passed the evidence gate: take sentences sharing at least two content
terms with the query and extract ``(value, unit, per)`` quantities. For two different documents
and a ``(dimension, per)`` group both of them state, the documents conflict when even their
closest pair of values differs by more than 20 %. Comparing the closest pair (not the first value)
keeps caveats such as "three minutes above 5,000 feet" next to "one minute" from being reported as
a conflict. Unit variants, tables and spelled-out ranges are missed; the eval's two
CONFLICTING_EVIDENCE items measure it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from stitch_library.core.normalize import search_text
from stitch_library.core.quantities import QuantityMatch, extract_quantities
from stitch_library.core.scope import query_terms
from stitch_library.core.tokenize import concept_tokens

REL_DIFF = 0.20


@dataclass(frozen=True)
class SentenceRef:
    doc_id: str
    chunk_id: str
    page: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Conflict:
    a: SentenceRef
    b: SentenceRef
    qa: QuantityMatch
    qb: QuantityMatch


def _rel(a: float, b: float) -> float:
    hi = max(abs(a), abs(b))
    return 0.0 if hi == 0 else abs(a - b) / hi


def detect_conflict(query: str, sentences: Sequence[SentenceRef]) -> Conflict | None:
    terms = query_terms(query)
    if len(terms) < 2:
        return None
    found: dict[str, list[tuple[SentenceRef, QuantityMatch]]] = {}
    for s in sentences:
        if len(terms & concept_tokens(search_text(s.text))) < 2:
            continue
        for q in extract_quantities(s.text):
            found.setdefault(s.doc_id, []).append((s, q))
    docs = sorted(found)
    for i, da in enumerate(docs):
        for db in docs[i + 1 :]:
            groups = {(q.dimension, q.per) for _, q in found[da]} & {
                (q.dimension, q.per) for _, q in found[db]
            }
            for g in sorted(groups, key=str):
                pa = [x for x in found[da] if (x[1].dimension, x[1].per) == g]
                pb = [x for x in found[db] if (x[1].dimension, x[1].per) == g]
                best = min(
                    ((_rel(a[1].base_value, b[1].base_value), a, b) for a in pa for b in pb),
                    key=lambda t: t[0],
                )
                if best[0] > REL_DIFF:
                    return Conflict(best[1][0], best[2][0], best[1][1], best[2][1])
    return None
