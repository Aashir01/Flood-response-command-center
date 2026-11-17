"""BRN-P23 (RFC 6901 resolver) and BRN-P8 (store JSON round-trip)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from brain_testkit import json_docs
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore, ResolvedRef, sha256_json
from stitch_brain.core.pointer import Resolved, Unresolved, pointer_for, resolve


def _paths(doc: Any, prefix: tuple[str | int, ...] = ()) -> list[tuple[tuple[str | int, ...], Any]]:
    out: list[tuple[tuple[str | int, ...], Any]] = [(prefix, doc)]
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.extend(_paths(v, (*prefix, k)))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out.extend(_paths(v, (*prefix, i)))
    return out


@settings(deadline=None)
@given(json_docs())
def test_brn_p23_every_path_resolves_to_its_value(doc: Any) -> None:
    for path, value in _paths(doc):
        assert resolve(doc, pointer_for(path)) == Resolved(value)


@settings(deadline=None)
@given(json_docs(), st.text(max_size=12))
def test_brn_p23_arbitrary_pointers_never_raise(doc: Any, ptr: str) -> None:
    res = resolve(doc, ptr)
    assert isinstance(res, Resolved | Unresolved)


@settings(deadline=None)
@given(st.lists(json_docs(8), min_size=1, max_size=5))
def test_brn_p8_store_round_trip_resolves_identically(docs: list[Any]) -> None:
    store = EvidenceStore("b")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    refs = []
    for i, d in enumerate(docs):
        result = {"ok": True, "data": d, "error": None, "provenance": {}, "warnings": []}
        e = EvidenceEntry(
            call_run_id=f"r{i}",
            briefing_id="b",
            node_id=f"n{i}",
            organ="eyes",
            tool="segment_flood",
            served_by="recorded",
            started_at=now,
            ended_at=now,
            result=result,
            original_sha256=sha256_json(result),
        )
        store.put(e)
        refs += [e.ref(pointer_for(("data", *p))) for p, _ in _paths(d)]
    again = EvidenceStore.loads(store.dumps())
    for ref in refs:
        a, b = store.resolve(ref), again.resolve(ref)
        assert isinstance(a, ResolvedRef) and isinstance(b, ResolvedRef)
        assert a.value == b.value
