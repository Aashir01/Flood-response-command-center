"""RFC 6901 resolver and evidence store (task 3; BRN-R5.1, R5.4, R3.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stitch_brain.core.evidence import (
    EvidenceEntry,
    EvidenceError,
    EvidenceStore,
    ResolvedRef,
    brain_entry,
    det_uuid,
    sha256_json,
)
from stitch_brain.core.pointer import (
    PointerError,
    Resolved,
    Unresolved,
    escape,
    parse,
    pointer_for,
    resolve,
)
from stitch_common.types import EvidenceRef

RFC_DOC = {
    "foo": ["bar", "baz"],
    "": 0,
    "a/b": 1,
    "c%d": 2,
    "e^f": 3,
    "g|h": 4,
    "i\\j": 5,
    'k"l': 6,
    " ": 7,
    "m~n": 8,
}


@pytest.mark.parametrize(
    ("ptr", "expected"),
    [
        ("", RFC_DOC),
        ("/foo", ["bar", "baz"]),
        ("/foo/0", "bar"),
        ("/", 0),
        ("/a~1b", 1),
        ("/c%d", 2),
        ("/e^f", 3),
        ("/g|h", 4),
        ("/i\\j", 5),
        ('/k"l', 6),
        ("/ ", 7),
        ("/m~0n", 8),
    ],
)
def test_rfc6901_section5_examples(ptr: str, expected: object) -> None:
    assert resolve(RFC_DOC, ptr) == Resolved(expected)


@pytest.mark.parametrize("ptr", ["foo", "/foo/01", "/foo/-", "/foo/2", "/nope", "/foo/0/x", "/~2"])
def test_bad_pointers_are_unresolved(ptr: str) -> None:
    assert isinstance(resolve(RFC_DOC, ptr), Unresolved)


def test_unescape_order_and_escape_inverse() -> None:
    assert parse("/~01") == ["~1"]  # ~01 is "~1", not "/"
    assert escape("a/b~c") == "a~1b~0c"
    assert pointer_for(["a/b", 0, "~"]) == "/a~1b/0/~0"
    with pytest.raises(PointerError):
        parse("x")


def _entry(rid: str, result: dict[str, object], node: str = "n", ok: bool = True) -> EvidenceEntry:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return EvidenceEntry(
        call_run_id=rid,
        briefing_id="b",
        node_id=node,
        organ="ledger",
        tool="optimize_allocation",
        served_by="recorded",
        started_at=now,
        ended_at=now,
        result=result,
        original_sha256=sha256_json(result),
    )


def test_store_resolve_checks_organ_tool_and_failed_roots() -> None:
    store = EvidenceStore("b")
    ok = _entry("r1", {"ok": True, "data": {"x": [1, 2]}, "provenance": {}, "warnings": []})
    bad = _entry(
        "r2",
        {"ok": False, "data": None, "error": {"code": "TIMEOUT"}, "provenance": {}, "warnings": []},
        node="m",
    )
    store.put(ok)
    store.put(bad)
    ref = ok.ref("/data/x/1")
    assert isinstance(store.resolve(ref), ResolvedRef)
    assert store.value(ref) == 2
    wrong = EvidenceRef(run_id="r1", organ="eyes", tool="optimize_allocation", json_pointer="")
    assert isinstance(store.resolve(wrong), Unresolved)
    assert store.resolves(bad.ref("/error/code"))
    assert not store.resolves(bad.ref("/data"))
    assert not store.resolves(EvidenceRef(run_id="zz", organ="a", tool="b", json_pointer=""))


def test_store_rejects_nan_and_conflicting_duplicates() -> None:
    store = EvidenceStore("b")
    with pytest.raises(EvidenceError):
        store.put(_entry("r", {"ok": True, "data": {"x": float("nan")}}))
    store.put(_entry("r", {"ok": True, "data": {"x": 1}}))
    with pytest.raises(EvidenceError):
        store.put(_entry("r", {"ok": True, "data": {"x": 2}}))


def test_by_node_returns_latest_attempt_and_alias() -> None:
    store = EvidenceStore("b")
    a1 = _entry("a1", {"ok": False, "error": {}}, node="n").model_copy(update={"attempt": 1})
    a2 = _entry("a2", {"ok": True, "data": {}}, node="n").model_copy(update={"attempt": 2})
    store.put(a1)
    store.put(a2)
    assert store.by_node("n") is a2
    store.alias("final", "a1")
    assert store.by_node("final") is a1


def test_brain_entry_is_deterministic_and_uuid4_shaped() -> None:
    e1 = brain_entry(briefing_id="b", node_id="run_meta", tool="run_meta", data={"k": 1})
    e2 = brain_entry(briefing_id="b", node_id="run_meta", tool="run_meta", data={"k": 1})
    assert e1.call_run_id == e2.call_run_id
    assert e1.organ == "brain" and e1.served_by == "brain"
    rid = det_uuid("x")
    assert rid[14] == "4" and rid[19] in "89ab"
