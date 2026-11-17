"""Ingestion properties (design 11): LIB-P7 (idempotent ids and Store contents) and LIB-P16
(unreadable pages are never indexed)."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from library_strategies import build_store, ingest, page_texts

from stitch_library.core.retrieve import Retriever
from stitch_library.ml.reranker import NullReranker

SLOW = settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])

# Pages that classify_page marks unreadable: empty, too few letters, garbled (private-use and
# replacement characters), Arabic without Urdu markers.
UNREADABLE = st.sampled_from(
    [
        "",
        "   \n  ",
        "12 34 56 -- 7",
        "\ue000\ue001\ue002 water \ufffd\ufffd store gallons per person per day \ue003\ue004",
        "\ufffd" * 40 + " some letters here to pass the empty rule easily",
        "هذا نص عربي فقط بدون علامات أردية خاصة وهو طويل بما يكفي للاختبار",
    ]
)


def _store_snapshot(corpus: object) -> tuple[object, ...]:
    store = corpus.store  # type: ignore[attr-defined]
    rows = sorted(store.iter_search_rows(), key=lambda r: r.chunk_id)
    docs = store.get_documents()
    pages = [store.get_page(p.doc_id, p.page) for d in corpus.docs for p in d.pages]  # type: ignore[attr-defined]
    ids = [r.chunk_id for r in rows]
    vecs = store.get_vectors(ids, corpus.embedder.model_id).tolist() if ids else []  # type: ignore[attr-defined]
    return (store.stats(), rows, docs, pages, vecs)


@SLOW
@given(st.lists(page_texts(min_words=5), min_size=1, max_size=4))
def test_p7_ingesting_twice_gives_identical_ids_and_store(pages: list[str]) -> None:
    a = ingest("doc-idem", pages)
    b = ingest("doc-idem", pages)
    assert [c.chunk_id for c in a.chunks] == [c.chunk_id for c in b.chunks]
    assert a.chunks == b.chunks and a.pages == b.pages and a.doc == b.doc
    sa, sb = build_store([a]), build_store([b])
    assert _store_snapshot(sa) == _store_snapshot(sb)
    # Re-upserting the same rows into one store changes nothing (idempotent upsert).
    before = _store_snapshot(sa)
    from stitch_library.pack import embed_chunks

    sa.store.upsert_documents([a.doc])
    sa.store.upsert_pages(a.pages)
    sa.store.upsert_chunks(a.chunks, sa.embedder.model_id, embed_chunks(sa.embedder, a.chunks))
    assert _store_snapshot(sa) == before


@SLOW
@given(
    st.lists(st.one_of(page_texts(min_words=8), UNREADABLE), min_size=1, max_size=6),
)
def test_p16_unreadable_pages_produce_no_chunk_vector_or_posting(pages: list[str]) -> None:
    doc = ingest("doc-mixed", pages)
    bad = {p.page for p in doc.pages if p.status != "ok"}
    assert all(c.page not in bad for c in doc.chunks)
    assert set(doc.report.unreadable) == bad
    for p in doc.pages:
        if p.status != "ok":
            assert p.reason in ("empty", "garbled", "other_script")
    corpus = build_store([doc])
    rows = list(corpus.store.iter_search_rows())
    chunks = corpus.store.get_chunks([r.chunk_id for r in rows])
    assert all(c.page not in bad for c in chunks)
    ret = Retriever(corpus.store, corpus.embedder, NullReranker())
    for index in ret.indexes.values():
        for cid in index.ids:
            assert corpus.store.get_chunks([cid])[0].page not in bad
