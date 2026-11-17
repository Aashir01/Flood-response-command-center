"""Store contract suite (design 5.1 and 5.5): one parametrized suite over ``MemoryStore`` and
``PgVectorStore``. The Postgres parameter is marked ``pg`` and ``integration`` and runs against a
throwaway ``pgvector/pgvector:pg16`` container (or ``STITCH_TEST_PG_DSN``); it skips cleanly
without Docker. LIB-P11 (both stores agree on random data) is at the bottom."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from library_strategies import ingest

from stitch_library.ml.embedder import FakeEmbedder
from stitch_library.pack import embed_chunks
from stitch_library.store.base import ChunkRow, Filters, PageRow, Store, StoreError
from stitch_library.store.memory import MemoryStore

PG_MARKS = [pytest.mark.pg, pytest.mark.integration, pytest.mark.allow_loopback]
EMB = FakeEmbedder()
MODEL = EMB.model_id

DOC_A = ingest(
    "doc-alpha",
    [
        "Store at least one gallon of water per person per day. Boil water for one minute.",
        "",
    ],
    publisher="FEMA",
    doc_type="guideline",
)
DOC_B = ingest(
    "doc-beta",
    ["Evacuate early when officials say so. Keep a radio and spare batteries ready."],
    publisher="EPA",
    doc_type="plan",
)
DOC_U = ingest(
    "doc-urdu",
    ["سیلاب کے دوران ہر شخص کے لیے روزانہ ایک گیلن پانی ذخیرہ کریں اور اسے صاف رکھیں۔"],
    lang="ur",
    publisher="Stitch",
    doc_type="translation",
)


def _open(kind: str, request: pytest.FixtureRequest) -> Store:
    if kind == "memory":
        return MemoryStore()
    from stitch_library.store.pgvector import PgVectorStore

    return PgVectorStore(request.getfixturevalue("pg_dsn"))


@pytest.fixture(params=["memory", pytest.param("pgvector", marks=PG_MARKS)])
def store(request: pytest.FixtureRequest) -> Iterator[Store]:
    s = _open(request.param, request)
    yield s
    close = getattr(s, "close", None)
    if close is not None:
        close()


def _load(s: Store, *docs: Any) -> None:
    for d in docs:
        s.upsert_documents([d.doc])
        s.upsert_pages(d.pages)
        s.upsert_chunks(d.chunks, MODEL, embed_chunks(EMB, d.chunks))


def _snapshot(s: Store) -> tuple[Any, ...]:
    rows = list(s.iter_search_rows())
    ids = [r.chunk_id for r in rows]
    return (
        s.stats(),
        rows,
        s.get_documents(),
        s.get_chunks(ids),
        np.round(s.get_vectors(ids, MODEL), 5).tolist() if ids else [],
    )


def test_upsert_is_idempotent(store: Store) -> None:
    _load(store, DOC_A, DOC_B)
    first = _snapshot(store)
    _load(store, DOC_A, DOC_B)
    assert _snapshot(store) == first
    assert store.stats().docs == 2


def test_delete_cascades_to_pages_chunks_and_vectors(store: Store) -> None:
    _load(store, DOC_A, DOC_B)
    ids_a = [c.chunk_id for c in DOC_A.chunks]
    store.delete_documents(["doc-alpha"])
    assert store.get_documents(["doc-alpha"]) == []
    assert store.get_page("doc-alpha", 1) is None
    assert store.get_chunks(ids_a) == []
    with pytest.raises(StoreError):
        store.get_vectors(ids_a, MODEL)
    assert {r.doc_id for r in store.iter_search_rows()} == {"doc-beta"}
    q = EMB.embed_queries(["water per person"])[0]
    assert all(cid not in ids_a for cid, _ in store.dense_search(q, 10, MODEL, Filters()))


def test_filters_restrict_dense_search(store: Store) -> None:
    _load(store, DOC_A, DOC_B, DOC_U)
    q = EMB.embed_queries(["water"])[0]
    by_id = {c.chunk_id: c for d in (DOC_A, DOC_B, DOC_U) for c in d.chunks}
    cases = [
        (Filters(publisher=frozenset({"EPA"})), {"doc-beta"}),
        (Filters(doc_type=frozenset({"guideline"})), {"doc-alpha"}),
        (Filters(lang=frozenset({"ur"})), {"doc-urdu"}),
        (Filters(doc_id=frozenset({"doc-alpha", "doc-urdu"})), {"doc-alpha", "doc-urdu"}),
    ]
    for flt, docs in cases:
        hits = store.dense_search(q, 10, MODEL, flt)
        assert hits and {by_id[c].doc_id for c, _ in hits} <= docs
    assert store.dense_search(q, 10, MODEL, Filters(publisher=frozenset({"nobody"}))) == []


def test_dense_search_orders_by_cosine_then_chunk_id(store: Store) -> None:
    _load(store, DOC_A)
    page = DOC_A.pages[0]
    twins = [
        ChunkRow(f"c_twin{i}", "doc-alpha", 1, 0, 10, "en", page.text[:10], "x", "t")
        for i in (3, 1, 2)
    ]
    vec = np.tile(EMB.embed_passages(["identical text"]), (3, 1)).astype(np.float32)
    store.upsert_chunks(twins, MODEL, vec)
    hits = store.dense_search(EMB.embed_queries(["identical text"])[0], 3, MODEL, Filters())
    assert [c for c, _ in hits] == ["c_twin1", "c_twin2", "c_twin3"]
    scores = [s for _, s in store.dense_search(vec[0], 10, MODEL, Filters())]
    assert scores == sorted(scores, reverse=True)
    assert len(store.dense_search(vec[0], 2, MODEL, Filters())) == 2


def test_unreadable_pages_are_stored_but_never_indexed(store: Store) -> None:
    _load(store, DOC_A)
    blank = store.get_page("doc-alpha", 2)
    assert blank is not None and blank.status == "unreadable" and blank.reason == "empty"
    bad = ChunkRow("c_bad", "doc-alpha", 2, 0, 1, "en", "x", "x", "t")
    with pytest.raises(StoreError):
        store.upsert_chunks([bad], MODEL, EMB.embed_passages(["x"]))
    assert all(r.chunk_id != "c_bad" for r in store.iter_search_rows())
    assert store.stats().unreadable_pages == 1


def test_meta_and_ping(store: Store) -> None:
    assert store.get_meta("missing") is None
    store.set_meta("k", "v1")
    store.set_meta("k", "v2")
    assert store.get_meta("k") == "v2"
    assert store.ping()


def test_page_text_round_trips_exactly(store: Store) -> None:
    _load(store, DOC_U)
    page = store.get_page("doc-urdu", 1)
    assert page == DOC_U.pages[0]
    assert isinstance(page, PageRow)


# LIB-P11 ------------------------------------------------------------------------------------
WORDS = ["water", "boil", "radio", "flood", "shelter", "gallon", "evacuate", "map", "food"]


@pytest.mark.pg
@pytest.mark.integration
@pytest.mark.allow_loopback
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    st.lists(
        st.lists(st.sampled_from(WORDS), min_size=3, max_size=10).map(lambda w: " ".join(w) + "."),
        min_size=1,
        max_size=5,
    ),
    st.lists(st.sampled_from(WORDS), min_size=1, max_size=4).map(" ".join),
    st.integers(1, 8),
    st.sampled_from([None, frozenset({"PubA"}), frozenset({"PubB"})]),
)
def test_p11_memory_and_pgvector_agree(
    pg_dsn: str, pages: list[str], query: str, k: int, pubs: frozenset[str] | None
) -> None:
    from stitch_library.store.pgvector import PgVectorStore

    docs = [
        ingest(f"doc-p{i}", [p], publisher="PubA" if i % 2 else "PubB") for i, p in enumerate(pages)
    ]
    mem = MemoryStore()
    pg = PgVectorStore(pg_dsn)
    try:
        pg.delete_documents([d.doc.doc_id for d in pg.get_documents()])
        _load(mem, *docs)
        _load(pg, *docs)
        q = EMB.embed_queries([query])[0]
        flt = Filters(publisher=pubs)
        a = mem.dense_search(q, k, MODEL, flt)
        b = pg.dense_search(q, k, MODEL, flt)
        assert [c for c, _ in a] == [c for c, _ in b]
        assert np.allclose([s for _, s in a], [s for _, s in b], atol=1e-5)
        assert list(mem.iter_search_rows()) == list(pg.iter_search_rows())
        assert mem.stats().chunks == pg.stats().chunks
        # Idempotent re-upsert and delete agree too.
        _load(pg, *docs)
        assert pg.stats().chunks == mem.stats().chunks
        mem.delete_documents([docs[0].doc.doc_id])
        pg.delete_documents([docs[0].doc.doc_id])
        assert list(mem.iter_search_rows()) == list(pg.iter_search_rows())
    finally:
        pg.close()
