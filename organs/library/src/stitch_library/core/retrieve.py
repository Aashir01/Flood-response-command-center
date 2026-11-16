"""Hybrid retrieval over the ``Store``, ``Embedder`` and ``Reranker`` protocols (design 6.1).

1. Normalize the query, detect its language ``qlang``.
2. Embed it. ``lang = en|ur`` restricts retrieval to chunks of that language; ``auto`` (or None)
   searches all languages (dense retrieval is cross-lingual).
3. BM25 (top 50) on the index of the requested language (``qlang`` for ``auto``) and dense
   search (top 50). Filters apply to both.
4. Reciprocal rank fusion (k = 60).
5. Top ``W = max(20, top_k)`` fused candidates; mirrored text (same ``text_sha``) collapses to
   the lowest ``chunk_id``.
6. Exact ``bm25`` and ``dense`` scores for every candidate.
7. Cross-encoder rerank when the reranker is active for ``qlang``; on any reranker error the
   result carries ``RERANKER_FAILED`` and ``rerank = null``.
8. Sort by rerank desc (if any), then RRF desc, then ``chunk_id``; truncate to ``top_k``.

All hits of one response use the same scorer, so ``score`` ordering is consistent (LIB-P3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from stitch_library.core.bm25 import BM25Index
from stitch_library.core.fusion import rrf
from stitch_library.core.lang import detect_query_lang
from stitch_library.core.normalize import clean_query, search_text
from stitch_library.core.tokenize import tokenize
from stitch_library.ml.embedder import Embedder
from stitch_library.ml.reranker import Reranker
from stitch_library.store.base import ChunkRow, DocRow, Filters, SearchRow, Store, Vectors

BM25_K = 50
DENSE_K = 50
# Measured on the dev laptop (task 21): the int8 mMARCO cross-encoder takes about 0.1 s per
# (query, passage) pair on 2 threads, so the design window of 20 is cut to 10.
MIN_WINDOW = 10
MAX_CHUNKS = 50_000
Scorer = Literal["rerank", "rrf"]


@dataclass(frozen=True)
class ScoredHit:
    chunk: ChunkRow
    doc: DocRow
    bm25: float
    dense: float
    rerank: float | None
    rrf: float
    score: float


@dataclass
class RetrievalResult:
    query: str
    qlang: Literal["en", "ur"]
    hits: list[ScoredHit]
    scorer: Scorer
    evidence_score: float | None
    qvec: Vectors
    warnings: list[str] = field(default_factory=list)


class Retriever:
    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        reranker: Reranker,
        *,
        rerank_langs: Sequence[str] = ("en", "ur"),
        stem: bool = True,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.reranker = reranker
        self.rerank_langs = frozenset(rerank_langs)
        self.stem = stem
        self.refresh()

    def refresh(self) -> None:
        """(Re)build the BM25 indexes from the store."""
        rows = list(self.store.iter_search_rows())
        if len(rows) > MAX_CHUNKS:
            raise RuntimeError(f"corpus has {len(rows)} chunks; the in-memory cap is {MAX_CHUNKS}")
        self.rows: dict[str, SearchRow] = {r.chunk_id: r for r in rows}
        by_lang: dict[str, list[tuple[str, list[str]]]] = {}
        for r in rows:
            by_lang.setdefault(r.lang, []).append((r.chunk_id, self._tok(r.search_text, r.lang)))
        self.indexes: dict[str, BM25Index] = {lang: BM25Index(d) for lang, d in by_lang.items()}
        self._docs = {d.doc_id: d for d in self.store.get_documents()}

    def _tok(self, stext: str, lang: str) -> list[str]:
        return tokenize(stext, lang, stem=self.stem)

    @property
    def fingerprint(self) -> str:
        return ",".join(f"{k}:{v.fingerprint[:12]}" for k, v in sorted(self.indexes.items()))

    def reranks(self, qlang: str) -> bool:
        return self.reranker.active and qlang in self.rerank_langs

    def search(
        self,
        query: str,
        *,
        lang: str | None = None,
        top_k: int = 8,
        flt: Filters | None = None,
        qvec: Vectors | None = None,
    ) -> RetrievalResult:
        q = clean_query(query)
        stext = search_text(q)
        qlang = detect_query_lang(q)
        restrict = lang if lang in ("en", "ur") else None
        flt = (flt or Filters()).narrowed(lang=frozenset({restrict}) if restrict else None)
        if qvec is None:
            qvec = self.embedder.embed_queries([q])[0]
        warnings: list[str] = []

        allowed = {cid for cid, r in self.rows.items() if flt.matches_row(r)}
        bm25_lang = restrict or qlang
        index = self.indexes.get(bm25_lang)
        bm25_list = index.top(self._tok(stext, bm25_lang), BM25_K, allowed) if index else []
        dense_list = [
            (cid, s)
            for cid, s in self.store.dense_search(qvec, DENSE_K, self.embedder.model_id, flt)
            if cid in allowed
        ]
        fused = rrf([bm25_list, dense_list])

        window = max(MIN_WINDOW, top_k)
        best_by_sha: dict[str, tuple[str, float]] = {}
        for cid, score in fused[: window * 2]:
            sha = self.rows[cid].text_sha
            prev = best_by_sha.get(sha)
            if prev is None:
                best_by_sha[sha] = (cid, score)
            else:
                best_by_sha[sha] = (min(prev[0], cid), max(prev[1], score))
        cands = sorted(best_by_sha.values(), key=lambda x: (-x[1], x[0]))[:window]
        if not cands:
            return RetrievalResult(q, qlang, [], "rrf", None, qvec, warnings)

        ids = [cid for cid, _ in cands]
        chunks = {c.chunk_id: c for c in self.store.get_chunks(ids)}
        ids = [cid for cid in ids if cid in chunks]
        vecs = self.store.get_vectors(ids, self.embedder.model_id).astype(np.float64)
        qv = np.asarray(qvec, dtype=np.float64)
        qn = float(np.linalg.norm(qv)) or 1.0
        norms = np.linalg.norm(vecs, axis=1) * qn
        dense = (vecs @ qv) / np.where(norms == 0, 1.0, norms)
        rrf_of = dict(cands)

        reranked: list[float] | None = None
        if self.reranks(qlang):
            try:
                reranked = self.reranker.score(q, [chunks[c].text for c in ids])
                if len(reranked) != len(ids):
                    raise ValueError("reranker returned the wrong number of scores")
            except Exception:
                reranked = None
                warnings.append("RERANKER_FAILED")

        hits: list[ScoredHit] = []
        for i, cid in enumerate(ids):
            ch = chunks[cid]
            idx = self.indexes.get(ch.lang)
            bm = idx.score_one(cid, self._tok(stext, ch.lang)) if idx else 0.0
            rr = float(reranked[i]) if reranked is not None else None
            hits.append(
                ScoredHit(
                    chunk=ch,
                    doc=self._docs[ch.doc_id],
                    bm25=float(bm),
                    dense=float(dense[i]),
                    rerank=rr,
                    rrf=rrf_of[cid],
                    score=rr if rr is not None else rrf_of[cid],
                )
            )
        hits.sort(key=lambda h: (-h.score, -h.rrf, h.chunk.chunk_id))
        scorer: Scorer = "rerank" if reranked is not None else "rrf"
        evidence = (
            max(h.rerank for h in hits if h.rerank is not None)
            if reranked is not None
            else max(h.dense for h in hits)
        )
        return RetrievalResult(q, qlang, hits[:top_k], scorer, float(evidence), qvec, warnings)
