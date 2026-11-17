"""Retrieval properties (design 11): LIB-P3, P4, P8, P17, and P10 for the decision function."""

from __future__ import annotations

import random

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from library_strategies import build_store, ingest, mini_corpora, queries, rerankers

from stitch_library.core.decide import Signals, Thresholds, decide
from stitch_library.core.fusion import rrf
from stitch_library.core.retrieve import Retriever
from stitch_library.ml.reranker import Reranker
from stitch_library.store.base import Filters

SETTINGS = settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(st.data(), rerankers(), st.integers(1, 20))
def test_p3_at_most_top_k_unique_sorted(data: st.DataObject, rr: Reranker, top_k: int) -> None:
    corpus = data.draw(mini_corpora())
    q = data.draw(queries(corpus))
    assume(q.strip())
    ret = Retriever(corpus.store, corpus.embedder, rr, rerank_langs=("en", "ur"))
    res = ret.search(q, top_k=top_k)
    ids = [h.chunk.chunk_id for h in res.hits]
    assert len(ids) <= top_k and len(ids) == len(set(ids))
    scores = [h.score for h in res.hits]
    assert scores == sorted(scores, reverse=True)
    assert all(h.rerank is None for h in res.hits) or all(h.rerank is not None for h in res.hits)


@SETTINGS
@given(st.data(), st.sampled_from([None, "en", "ur"]))
def test_p17_filters_are_respected(data: st.DataObject, lang: str | None) -> None:
    corpus = data.draw(mini_corpora())
    q = data.draw(queries(corpus))
    assume(q.strip())
    pubs = data.draw(st.none() | st.sets(st.sampled_from(["PubA", "PubB"]), min_size=1))
    types = data.draw(st.none() | st.sets(st.sampled_from(["guideline", "plan"]), min_size=1))
    flt = Filters(
        publisher=frozenset(pubs) if pubs else None,
        doc_type=frozenset(types) if types else None,
    )
    ret = Retriever(corpus.store, corpus.embedder, rerankers().example())
    res = ret.search(q, top_k=20, flt=flt, lang=lang)
    for h in res.hits:
        assert pubs is None or h.doc.publisher in pubs
        assert types is None or h.doc.doc_type in types
        assert lang is None or h.chunk.lang == lang


ranked = st.lists(st.sampled_from([f"c{i:02d}" for i in range(15)]), unique=True, max_size=12)


@given(ranked, ranked, st.randoms())
def test_p8_rrf_is_deterministic_and_dominance_respecting(
    a: list[str], b: list[str], rnd: random.Random
) -> None:
    la = [(c, 1.0) for c in a]
    lb = [(c, 1.0) for c in b]
    out = rrf([la, lb])
    assert out == rrf([la, lb])
    assert {c for c, _ in out} == set(a) | set(b)
    pos = {c: i for i, (c, _) in enumerate(out)}
    ra = {c: i for i, c in enumerate(a)}
    rb = {c: i for i, c in enumerate(b)}
    big = 10**6
    for x in pos:
        for y in pos:
            if ra.get(x, big) < ra.get(y, big) and rb.get(x, big) < rb.get(y, big):
                assert pos[x] < pos[y]
    # Input order of the lists does not matter.
    assert rrf([lb, la]) == out


@SETTINGS
@given(st.data())
def test_p8_full_retrieval_is_repeatable(data: st.DataObject) -> None:
    corpus = data.draw(mini_corpora())
    q = data.draw(queries(corpus))
    assume(q.strip())
    r1 = Retriever(corpus.store, corpus.embedder, rerankers().example()).search(q, top_k=8)
    r2 = Retriever(corpus.store, corpus.embedder, rerankers().example()).search(q, top_k=8)
    assert [h.chunk.chunk_id for h in r1.hits] == [h.chunk.chunk_id for h in r2.hits]


TARGET = (
    "Boil drinking water for one full minute before use. "
    "Let boiled water cool in a clean covered container."
)
NOISE_WORDS = ["generator", "outdoors", "windows", "gasoline", "machinery", "roof", "attic"]


@SETTINGS
@given(st.data())
def test_p4_irrelevant_document_does_not_change_top1(data: st.DataObject) -> None:
    """Constrained generator (design 11): the query is a verbatim window of one target chunk,
    the added document shares no query term and has a length close to the corpus mean. Not a
    theorem for BM25 in general; outside these constraints the test does not assert."""
    base = [ingest("doc-target", [TARGET])]
    others = data.draw(
        st.lists(
            st.lists(st.sampled_from(NOISE_WORDS), min_size=6, max_size=14).map(
                lambda ws: " ".join(ws) + "."
            ),
            min_size=0,
            max_size=3,
        )
    )
    base += [ingest(f"doc-o{i}", [t]) for i, t in enumerate(others)]
    q = "boil drinking water one minute"
    before = build_store(base)
    top_before = Retriever(before.store, before.embedder, rerankers().example()).search(q).hits
    added = " ".join(data.draw(st.lists(st.sampled_from(NOISE_WORDS), min_size=8, max_size=16)))
    after = build_store([*base, ingest("doc-added", [added + "."])])
    rr = rerankers().example()
    top_after = Retriever(after.store, after.embedder, rr).search(q).hits
    assert top_before and top_after
    assert top_after[0].chunk.chunk_id == top_before[0].chunk.chunk_id


scores = st.floats(-10, 10, allow_nan=False)


@given(scores, scores | st.none(), scores, scores, st.floats(0, 5), st.booleans(), st.booleans())
def test_p10_raising_thresholds_never_turns_a_refusal_into_an_answer(
    scope: float,
    evidence: float | None,
    tau_s: float,
    tau_e: float,
    bump: float,
    qty_unsupported: bool,
    conflict: bool,
) -> None:
    sig = Signals(scope, evidence, qty_unsupported, not qty_unsupported, conflict)
    low = decide(sig, Thresholds(tau_s, tau_e))
    high = decide(sig, Thresholds(tau_s + bump, tau_e + bump))
    if not low.proceed:
        assert not high.proceed
