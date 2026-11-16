"""``PgVectorStore``: Postgres 16 + pgvector via psycopg 3 (design section 5.3).

Every statement is a constant string with bound parameters; filter lists use ``= ANY(%s)``.
Dense search is an exact scan (``ORDER BY embedding <=> %s``); the vector column has no fixed
dimension, so a model swap needs no schema change. Results are re-ordered with the shared
``order_dense`` rule so both stores agree (LIB-P11). The migrator applies ``schema.sql`` and
records ``meta.schema_version``. ``CREATE EXTENSION vector`` belongs to the init script.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import psycopg

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

SCHEMA_VERSION = "1"
SCHEMA_SQL = Path(__file__).with_name("schema.sql")

SQL_UPSERT_DOC = """
INSERT INTO documents (doc_id, title, publisher, doc_type, lang, source_url, license,
                       redistributable, tier, sha256, as_of)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (doc_id) DO UPDATE SET title = EXCLUDED.title, publisher = EXCLUDED.publisher,
  doc_type = EXCLUDED.doc_type, lang = EXCLUDED.lang, source_url = EXCLUDED.source_url,
  license = EXCLUDED.license, redistributable = EXCLUDED.redistributable, tier = EXCLUDED.tier,
  sha256 = EXCLUDED.sha256, as_of = EXCLUDED.as_of
"""
SQL_UPSERT_PAGE = """
INSERT INTO pages (doc_id, page, lang, status, reason, text) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (doc_id, page) DO UPDATE SET lang = EXCLUDED.lang, status = EXCLUDED.status,
  reason = EXCLUDED.reason, text = EXCLUDED.text
"""
SQL_PAGE_STATUS = "SELECT status FROM pages WHERE doc_id = %s AND page = %s"
SQL_UPSERT_CHUNK = """
INSERT INTO chunks (chunk_id, doc_id, page, start_char, end_char, lang, text, search_text,
                    text_sha)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET doc_id = EXCLUDED.doc_id, page = EXCLUDED.page,
  start_char = EXCLUDED.start_char, end_char = EXCLUDED.end_char, lang = EXCLUDED.lang,
  text = EXCLUDED.text, search_text = EXCLUDED.search_text, text_sha = EXCLUDED.text_sha
"""
SQL_UPSERT_VECTOR = """
INSERT INTO chunk_vectors (model_id, chunk_id, embedding) VALUES (%s, %s, %s::vector)
ON CONFLICT (model_id, chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding
"""
SQL_DELETE_DOCS = "DELETE FROM documents WHERE doc_id = ANY(%s)"
SQL_DENSE = """
SELECT v.chunk_id, 1 - (v.embedding <=> %s::vector) AS cos
FROM chunk_vectors v
JOIN chunks c ON c.chunk_id = v.chunk_id
JOIN pages p ON p.doc_id = c.doc_id AND p.page = c.page
JOIN documents d ON d.doc_id = c.doc_id
WHERE v.model_id = %s AND p.status = 'ok'
  AND (%s::text[] IS NULL OR d.publisher = ANY(%s::text[]))
  AND (%s::text[] IS NULL OR d.doc_type = ANY(%s::text[]))
  AND (%s::text[] IS NULL OR c.lang = ANY(%s::text[]))
  AND (%s::text[] IS NULL OR c.doc_id = ANY(%s::text[]))
ORDER BY v.embedding <=> %s::vector, v.chunk_id
LIMIT %s
"""
SQL_GET_VECTORS = """
SELECT chunk_id, embedding::text FROM chunk_vectors WHERE model_id = %s AND chunk_id = ANY(%s)
"""
SQL_GET_CHUNKS = """
SELECT chunk_id, doc_id, page, start_char, end_char, lang, text, search_text, text_sha
FROM chunks WHERE chunk_id = ANY(%s)
"""
SQL_GET_PAGE = (
    "SELECT doc_id, page, lang, status, reason, text FROM pages WHERE doc_id = %s AND page = %s"
)
SQL_GET_DOCS_ALL = """
SELECT doc_id, title, publisher, doc_type, lang, source_url, license, redistributable, tier,
       sha256, as_of FROM documents ORDER BY doc_id
"""
SQL_GET_DOCS = """
SELECT doc_id, title, publisher, doc_type, lang, source_url, license, redistributable, tier,
       sha256, as_of FROM documents WHERE doc_id = ANY(%s) ORDER BY doc_id
"""
SQL_SEARCH_ROWS = """
SELECT c.chunk_id, c.lang, c.doc_id, d.publisher, d.doc_type, c.search_text, c.text_sha
FROM chunks c
JOIN pages p ON p.doc_id = c.doc_id AND p.page = c.page
JOIN documents d ON d.doc_id = c.doc_id
WHERE p.status = 'ok' ORDER BY c.chunk_id
"""
SQL_GET_META = "SELECT value FROM meta WHERE key = %s"
SQL_SET_META = """
INSERT INTO meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
"""
SQL_STATS_DOCS = "SELECT tier, count(*) FROM documents GROUP BY tier ORDER BY tier"
SQL_STATS_PAGES = "SELECT count(*), count(*) FILTER (WHERE status <> 'ok') FROM pages"
SQL_STATS_CHUNKS = "SELECT count(*) FROM chunks"
SQL_STATS_VECTORS = "SELECT model_id, count(*) FROM chunk_vectors GROUP BY model_id ORDER BY 1"
SQL_SCHEMA_EXISTS = "SELECT to_regclass('public.meta') IS NOT NULL"


def _vec_literal(v: Any) -> str:
    return "[" + ",".join(repr(float(x)) for x in np.asarray(v, dtype=np.float32)) + "]"


def _parse_vec(s: str) -> Vectors:
    out: Vectors = np.array([float(x) for x in s.strip("[]").split(",")], dtype=np.float32)
    return out


def _arr(values: frozenset[str] | None) -> list[str] | None:
    return sorted(values) if values is not None else None


class PgVectorStore:
    kind = "pgvector"

    def __init__(self, dsn: str, *, migrate: bool = True) -> None:
        try:
            self.conn = psycopg.connect(dsn, autocommit=False, connect_timeout=10)
        except psycopg.Error as exc:
            raise StoreError(f"cannot connect to Postgres: {type(exc).__name__}") from exc
        if migrate:
            self.migrate()

    def close(self) -> None:
        self.conn.close()

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)  # constant SQL, bound params
                rows = cur.fetchall() if cur.description else []
            if self.conn.autocommit is False and not getattr(self, "_in_tx", False):
                self.conn.commit()
            return rows
        except psycopg.Error as exc:
            if not getattr(self, "_in_tx", False):
                self.conn.rollback()
            raise StoreError(f"postgres error: {type(exc).__name__}") from exc

    def migrate(self) -> None:
        exists = self._exec(SQL_SCHEMA_EXISTS)[0][0]
        if exists and self.get_meta("schema_version") == SCHEMA_VERSION:
            return
        ddl = SCHEMA_SQL.read_text(encoding="utf-8")
        for stmt in (s.strip() for s in ddl.split(";")):
            body = "\n".join(line for line in stmt.splitlines() if not line.startswith("--"))
            if body.strip():
                self._exec(body)
        self.set_meta("schema_version", SCHEMA_VERSION)

    # transactions (used by the seeder) ---------------------------------------------------
    def begin(self) -> None:
        self._in_tx = True

    def commit(self) -> None:
        self._in_tx = False
        self.conn.commit()

    def rollback(self) -> None:
        self._in_tx = False
        self.conn.rollback()

    # writes -------------------------------------------------------------------------------
    def upsert_documents(self, docs: Sequence[DocRow]) -> None:
        for d in docs:
            self._exec(
                SQL_UPSERT_DOC,
                (
                    d.doc_id, d.title, d.publisher, d.doc_type, d.lang, d.source_url, d.license,
                    d.redistributable, d.tier, d.sha256, d.as_of,
                ),
            )  # fmt: skip

    def upsert_pages(self, pages: Sequence[PageRow]) -> None:
        for p in pages:
            self._exec(SQL_UPSERT_PAGE, (p.doc_id, p.page, p.lang, p.status, p.reason, p.text))

    def upsert_chunks(self, chunks: Sequence[ChunkRow], model_id: str, vectors: Vectors) -> None:
        if len(chunks) != len(vectors):
            raise StoreError("chunks and vectors differ in length")
        for c in chunks:
            rows = self._exec(SQL_PAGE_STATUS, (c.doc_id, c.page))
            if not rows:
                raise StoreError(f"chunk {c.chunk_id} of unknown page")
            if rows[0][0] != "ok":
                raise StoreError(f"chunk {c.chunk_id} belongs to an unreadable page")
        for c, v in zip(chunks, vectors, strict=True):
            self._exec(
                SQL_UPSERT_CHUNK,
                (
                    c.chunk_id,
                    c.doc_id,
                    c.page,
                    c.start,
                    c.end,
                    c.lang,
                    c.text,
                    c.search_text,
                    c.text_sha,
                ),
            )
            self._exec(SQL_UPSERT_VECTOR, (model_id, c.chunk_id, _vec_literal(v)))

    def delete_documents(self, doc_ids: Sequence[str]) -> None:
        self._exec(SQL_DELETE_DOCS, (list(doc_ids),))

    def set_meta(self, key: str, value: str) -> None:
        self._exec(SQL_SET_META, (key, value))

    # reads --------------------------------------------------------------------------------
    def dense_search(
        self, qvec: Vectors, k: int, model_id: str, flt: Filters
    ) -> list[tuple[str, float]]:
        if k <= 0:
            return []
        q = _vec_literal(qvec)
        pub, typ, lang, ids = (
            _arr(flt.publisher),
            _arr(flt.doc_type),
            _arr(flt.lang),
            _arr(flt.doc_id),
        )
        rows = self._exec(
            SQL_DENSE, (q, model_id, pub, pub, typ, typ, lang, lang, ids, ids, q, k * 2 + 10)
        )
        return order_dense([(str(r[0]), float(r[1])) for r in rows], k)

    def get_vectors(self, chunk_ids: Sequence[str], model_id: str) -> Vectors:
        if not chunk_ids:
            return np.zeros((0, 0), dtype=np.float32)
        rows = {
            str(r[0]): _parse_vec(str(r[1]))
            for r in self._exec(SQL_GET_VECTORS, (model_id, list(chunk_ids)))
        }
        missing = [c for c in chunk_ids if c not in rows]
        if missing:
            raise StoreError(f"no {model_id} vectors for {len(missing)} chunk(s)")
        return np.stack([rows[c] for c in chunk_ids]).astype(np.float32)

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[ChunkRow]:
        rows = {str(r[0]): r for r in self._exec(SQL_GET_CHUNKS, (list(chunk_ids),))}
        return [ChunkRow(*rows[c]) for c in chunk_ids if c in rows]

    def get_page(self, doc_id: str, page: int) -> PageRow | None:
        rows = self._exec(SQL_GET_PAGE, (doc_id, page))
        return PageRow(*rows[0]) if rows else None

    def get_documents(self, doc_ids: Sequence[str] | None = None) -> list[DocRow]:
        rows = (
            self._exec(SQL_GET_DOCS_ALL)
            if doc_ids is None
            else self._exec(SQL_GET_DOCS, (list(doc_ids),))
        )
        by_id = {r[0]: DocRow(*r) for r in rows}
        order = sorted(by_id) if doc_ids is None else [d for d in doc_ids if d in by_id]
        return [by_id[d] for d in order]

    def iter_search_rows(self) -> Iterator[SearchRow]:
        for r in self._exec(SQL_SEARCH_ROWS):
            yield SearchRow(*r)

    def get_meta(self, key: str) -> str | None:
        rows = self._exec(SQL_GET_META, (key,))
        return str(rows[0][0]) if rows else None

    def stats(self) -> StoreStats:
        tiers = {str(t): int(n) for t, n in self._exec(SQL_STATS_DOCS)}
        pages, unreadable = self._exec(SQL_STATS_PAGES)[0]
        chunks = self._exec(SQL_STATS_CHUNKS)[0][0]
        vectors = {str(m): int(n) for m, n in self._exec(SQL_STATS_VECTORS)}
        return StoreStats(
            docs=sum(tiers.values()),
            pages=int(pages),
            unreadable_pages=int(unreadable),
            chunks=int(chunks),
            vectors=vectors,
            docs_by_tier=tiers,
        )

    def ping(self) -> bool:
        try:
            self._exec("SELECT 1")
            return True
        except StoreError:
            return False
