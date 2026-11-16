"""Reciprocal rank fusion with deterministic tie-breaks (design section 6.1 step 4). Pure.

Each input is a list of ``(id, score)``. It is ranked by score descending, then id ascending, so
the order in which equal scores arrive does not matter (LIB-P8). Ranks start at 1.
``rrf(d) = sum_r 1 / (k + rank_r(d))``. Output ties are broken by id ascending.
"""

from __future__ import annotations

from collections.abc import Sequence

RRF_K = 60


def rank(scored: Sequence[tuple[str, float]]) -> list[str]:
    best: dict[str, float] = {}
    for cid, s in scored:
        if cid not in best or s > best[cid]:
            best[cid] = s
    return [cid for cid, _ in sorted(best.items(), key=lambda x: (-x[1], x[0]))]


def rrf(lists: Sequence[Sequence[tuple[str, float]]], k: int = RRF_K) -> list[tuple[str, float]]:
    acc: dict[str, float] = {}
    for scored in lists:
        for r, cid in enumerate(rank(scored), start=1):
            acc[cid] = acc.get(cid, 0.0) + 1.0 / (k + r)
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))
