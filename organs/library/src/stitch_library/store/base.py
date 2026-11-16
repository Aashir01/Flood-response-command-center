"""``Store`` protocol and shared row types (design section 5.1).

Behaviour shared by every implementation (contract suite ``tests/contract/test_store_contract.py``,
LIB-P11):

* ``dense_search`` returns cosine similarity, descending, ties broken by ``chunk_id`` ascending
  (scores rounded to 9 decimals before ordering, so float noise cannot reorder near-equal
  rows), at most ``k``, only chunks of ``status = ok`` pages, only chunks matching ``Filters``.
* Upserts are idempotent. ``delete_documents`` removes pages, chunks and vectors.
* Chunks of an unreadable page are rejected at upsert (LIB-P16).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray

Tier = Literal["committed", "fetched"]
PageStatus = Literal["ok", "unreadable"]
Vectors = NDArray[np.float32]
SCORE_DECIMALS = 9


class StoreError(RuntimeError):
    """The store is unavailable or rejected a write."""


@dataclass(frozen=True)
class DocRow:
    doc_id: str
    title: str
    publisher: str
    doc_type: str
    lang: str
    source_url: str
    license: str
    redistributable: bool
    tier: Tier
    sha256: str
    as_of: date | None


@dataclass(frozen=True)
class PageRow:
    doc_id: str
    page: int
    lang: str
    status: PageStatus
    reason: str | None
    text: str


@dataclass(frozen=True)
class ChunkRow:
    chunk_id: str
    doc_id: str
    page: int
    start: int
    end: int
    lang: str
    text: str
    search_text: str
    text_sha: str


@dataclass(frozen=True)
class SearchRow:
    chunk_id: str
    lang: str
    doc_id: str
    publisher: str
    doc_type: str
    search_text: str
    text_sha: str


@dataclass(frozen=True)
class Filters:
    """Restrictions on retrieval. ``None`` means unrestricted for that field."""

    publisher: frozenset[str] | None = None
    doc_type: frozenset[str] | None = None
    lang: frozenset[str] | None = None
    doc_id: frozenset[str] | None = None

    def matches(self, *, publisher: str, doc_type: str, lang: str, doc_id: str) -> bool:
        return (
            (self.publisher is None or publisher in self.publisher)
            and (self.doc_type is None or doc_type in self.doc_type)
            and (self.lang is None or lang in self.lang)
            and (self.doc_id is None or doc_id in self.doc_id)
        )

    def matches_row(self, row: SearchRow) -> bool:
        return self.matches(
            publisher=row.publisher, doc_type=row.doc_type, lang=row.lang, doc_id=row.doc_id
        )

    def narrowed(self, *, lang: frozenset[str] | None) -> Filters:
        if lang is None:
            return self
        merged = lang if self.lang is None else self.lang & lang
        return Filters(self.publisher, self.doc_type, merged, self.doc_id)


@dataclass(frozen=True)
class StoreStats:
    docs: int
    pages: int
    unreadable_pages: int
    chunks: int
    vectors: dict[str, int] = field(default_factory=dict)
    docs_by_tier: dict[str, int] = field(default_factory=dict)

    @property
    def readable_page_ratio(self) -> float:
        return 1.0 if self.pages == 0 else (self.pages - self.unreadable_pages) / self.pages


def order_dense(scored: Sequence[tuple[str, float]], k: int) -> list[tuple[str, float]]:
    """Shared ordering rule for dense results."""
    rows = sorted(scored, key=lambda x: (-round(x[1], SCORE_DECIMALS), x[0]))
    return [(cid, float(s)) for cid, s in rows[:k]]


class Store(Protocol):
    kind: str

    def upsert_documents(self, docs: Sequence[DocRow]) -> None: ...
    def upsert_pages(self, pages: Sequence[PageRow]) -> None: ...
    def upsert_chunks(
        self, chunks: Sequence[ChunkRow], model_id: str, vectors: Vectors
    ) -> None: ...
    def delete_documents(self, doc_ids: Sequence[str]) -> None: ...
    def dense_search(
        self, qvec: Vectors, k: int, model_id: str, flt: Filters
    ) -> list[tuple[str, float]]: ...
    def get_vectors(self, chunk_ids: Sequence[str], model_id: str) -> Vectors: ...
    def get_chunks(self, chunk_ids: Sequence[str]) -> list[ChunkRow]: ...
    def get_page(self, doc_id: str, page: int) -> PageRow | None: ...
    def get_documents(self, doc_ids: Sequence[str] | None = None) -> list[DocRow]: ...
    def iter_search_rows(self) -> Iterator[SearchRow]: ...
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str) -> None: ...
    def stats(self) -> StoreStats: ...
    def ping(self) -> bool: ...
