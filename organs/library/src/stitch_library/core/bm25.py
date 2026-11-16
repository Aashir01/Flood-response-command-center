"""In-process Okapi BM25, one index per language (design section 6.2). Pure.

``k1 = 1.2``, ``b = 0.75``, ``idf = ln(1 + (N - n + 0.5) / (n + 0.5))``. Postings are
``array('I')`` pairs per interned term. Ties are broken by ``chunk_id`` ascending. The
fingerprint is the sha256 of the sorted chunk ids, so a rebuilt index is detectably the same.
"""

from __future__ import annotations

import hashlib
import math
from array import array
from collections import Counter
from collections.abc import Iterable, Sequence

K1 = 1.2
B = 0.75


class BM25Index:
    def __init__(self, docs: Iterable[tuple[str, Sequence[str]]], k1: float = K1, b: float = B):
        self.k1, self.b = k1, b
        self.ids: list[str] = []
        self._pos: dict[str, int] = {}
        self._lens: list[int] = []
        self._terms: dict[str, int] = {}
        self._postings: list[array[int]] = []  # term id -> [doc, tf, doc, tf, ...]
        self._tf: list[dict[int, int]] = []  # doc -> {term id: tf}
        for cid, toks in sorted(docs, key=lambda d: d[0]):
            if cid in self._pos:
                continue
            d = len(self.ids)
            self.ids.append(cid)
            self._pos[cid] = d
            self._lens.append(len(toks))
            counts: dict[int, int] = {}
            for tok, tf in Counter(toks).items():
                tid = self._terms.setdefault(tok, len(self._terms))
                if tid == len(self._postings):
                    self._postings.append(array("I"))
                self._postings[tid].extend((d, tf))
                counts[tid] = tf
            self._tf.append(counts)
        self.n = len(self.ids)
        self.avgdl = (sum(self._lens) / self.n) if self.n else 0.0
        self.fingerprint = hashlib.sha256("\n".join(self.ids).encode("utf-8")).hexdigest()

    def __len__(self) -> int:
        return self.n

    def __contains__(self, cid: object) -> bool:
        return cid in self._pos

    def idf(self, term: str) -> float:
        tid = self._terms.get(term)
        df = len(self._postings[tid]) // 2 if tid is not None else 0
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def _norm(self, d: int) -> float:
        if self.avgdl == 0:
            return self.k1
        return self.k1 * (1.0 - self.b + self.b * self._lens[d] / self.avgdl)

    def scores(self, query: Sequence[str]) -> dict[str, float]:
        """Score of every document with at least one query term (query terms counted once)."""
        acc: dict[int, float] = {}
        for term in dict.fromkeys(query):
            tid = self._terms.get(term)
            if tid is None:
                continue
            post = self._postings[tid]
            idf = self.idf(term)
            for i in range(0, len(post), 2):
                d, tf = post[i], post[i + 1]
                acc[d] = acc.get(d, 0.0) + idf * tf * (self.k1 + 1.0) / (tf + self._norm(d))
        return {self.ids[d]: s for d, s in acc.items()}

    def score_one(self, cid: str, query: Sequence[str]) -> float:
        d = self._pos.get(cid)
        if d is None:
            return 0.0
        tfs = self._tf[d]
        total = 0.0
        for term in dict.fromkeys(query):
            tid = self._terms.get(term)
            if tid is None or tid not in tfs:
                continue
            tf = tfs[tid]
            total += self.idf(term) * tf * (self.k1 + 1.0) / (tf + self._norm(d))
        return total

    def top(
        self, query: Sequence[str], k: int, allowed: set[str] | None = None
    ) -> list[tuple[str, float]]:
        items = [
            (cid, s)
            for cid, s in self.scores(query).items()
            if s > 0 and (allowed is None or cid in allowed)
        ]
        items.sort(key=lambda x: (-x[1], x[0]))
        return items[:k]
