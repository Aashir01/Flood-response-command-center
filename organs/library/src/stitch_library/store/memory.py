"""``MemoryStore``: dicts for rows, a float32 matrix per model for vectors (design section 5.2).

Used by unit, property and eval tests and by ``STITCH_LIBRARY_STORE=memory`` (loads the committed
pack with no Postgres; also the Windows development path without Docker).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import numpy as np

from stitch_library.store.base import (
    ChunkRow,
    DocRow,
    Filters,
    PageRow,
    SearchRow,
    StoreError,
    StoreStats,
    Vectors,
    order_dense,
)


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._docs: dict[str, DocRow] = {}
        self._pages: dict[tuple[str, int], PageRow] = {}
        self._chunks: dict[str, ChunkRow] = {}
        self._vectors: dict[str, dict[str, Vectors]] = {}
        self._meta: dict[str, str] = {}
        self._matrix: dict[str, tuple[list[str], Vectors]] = {}

    # writes -------------------------------------------------------------------------------
    def upsert_documents(self, docs: Sequence[DocRow]) -> None:
        for d in docs:
            self._docs[d.doc_id] = d

    def upsert_pages(self, pages: Sequence[PageRow]) -> None:
        for p in pages:
            if p.doc_id not in self._docs:
                raise StoreError(f"page of unknown document {p.doc_id!r}")
            self._pages[(p.doc_id, p.page)] = p

    def upsert_chunks(self, chunks: Sequence[ChunkRow], model_id: str, vectors: Vectors) -> None:
        if len(chunks) != len(vectors):
            raise StoreError("chunks and vectors differ in length")
        for c in chunks:
            page = self._pages.get((c.doc_id, c.page))
            if page is None:
                raise StoreError(f"chunk {c.chunk_id} of unknown page")
            if page.status != "ok":
                raise StoreError(f"chunk {c.chunk_id} belongs to an unreadable page")
        per_model = self._vectors.setdefault(model_id, {})
        for c, v in zip(chunks, vectors, strict=True):
            self._chunks[c.chunk_id] = c
            per_model[c.chunk_id] = np.asarray(v, dtype=np.float32)
        self._matrix.pop(model_id, None)

    def delete_documents(self, doc_ids: Sequence[str]) -> None:
        gone = set(doc_ids)
        for key in [k for k in self._pages if k[0] in gone]:
            del self._pages[key]
        dead = [cid for cid, c in self._chunks.items() if c.doc_id in gone]
        for cid in dead:
            del self._chunks[cid]
            for per_model in self._vectors.values():
                per_model.pop(cid, None)
        for d in gone:
            self._docs.pop(d, None)
        self._matrix.clear()

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value

    # reads --------------------------------------------------------------------------------
    def _searchable(self, c: ChunkRow, flt: Filters) -> bool:
        page = self._pages.get((c.doc_id, c.page))
        doc = self._docs.get(c.doc_id)
        if page is None or doc is None or page.status != "ok":
            return False
        return flt.matches(
            publisher=doc.publisher, doc_type=doc.doc_type, lang=c.lang, doc_id=c.doc_id
        )

    def _model_matrix(self, model_id: str) -> tuple[list[str], Vectors]:
        cached = self._matrix.get(model_id)
        if cached is None:
            per_model = self._vectors.get(model_id, {})
            ids = sorted(per_model)
            mat = (
                np.stack([per_model[i] for i in ids]).astype(np.float32)
                if ids
                else np.zeros((0, 0), dtype=np.float32)
            )
            cached = (ids, mat)
            self._matrix[model_id] = cached
        return cached

    def dense_search(
        self, qvec: Vectors, k: int, model_id: str, flt: Filters
    ) -> list[tuple[str, float]]:
        ids, mat = self._model_matrix(model_id)
        if not ids or k <= 0:
            return []
        q = np.asarray(qvec, dtype=np.float64)
        m = mat.astype(np.float64)
        norms = np.linalg.norm(m, axis=1) * (np.linalg.norm(q) or 1.0)
        sims = (m @ q) / np.where(norms == 0, 1.0, norms)
        scored = [
            (cid, float(s))
            for cid, s in zip(ids, sims, strict=True)
            if self._searchable(self._chunks[cid], flt)
        ]
        return order_dense(scored, k)

    def get_vectors(self, chunk_ids: Sequence[str], model_id: str) -> Vectors:
        per_model = self._vectors.get(model_id, {})
        missing = [c for c in chunk_ids if c not in per_model]
        if missing:
            raise StoreError(f"no {model_id} vectors for {len(missing)} chunk(s)")
        if not chunk_ids:
            return np.zeros((0, 0), dtype=np.float32)
        return np.stack([per_model[c] for c in chunk_ids]).astype(np.float32)

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[ChunkRow]:
        return [self._chunks[c] for c in chunk_ids if c in self._chunks]

    def get_page(self, doc_id: str, page: int) -> PageRow | None:
        return self._pages.get((doc_id, page))

    def get_documents(self, doc_ids: Sequence[str] | None = None) -> list[DocRow]:
        if doc_ids is None:
            return [self._docs[d] for d in sorted(self._docs)]
        return [self._docs[d] for d in doc_ids if d in self._docs]

    def iter_search_rows(self) -> Iterator[SearchRow]:
        for cid in sorted(self._chunks):
            c = self._chunks[cid]
            page = self._pages.get((c.doc_id, c.page))
            doc = self._docs.get(c.doc_id)
            if page is None or doc is None or page.status != "ok":
                continue
            yield SearchRow(
                cid, c.lang, c.doc_id, doc.publisher, doc.doc_type, c.search_text, c.text_sha
            )

    def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def stats(self) -> StoreStats:
        tiers: dict[str, int] = {}
        for d in self._docs.values():
            tiers[d.tier] = tiers.get(d.tier, 0) + 1
        return StoreStats(
            docs=len(self._docs),
            pages=len(self._pages),
            unreadable_pages=sum(1 for p in self._pages.values() if p.status != "ok"),
            chunks=len(self._chunks),
            vectors={m: len(v) for m, v in sorted(self._vectors.items())},
            docs_by_tier=dict(sorted(tiers.items())),
        )

    def ping(self) -> bool:
        return True
