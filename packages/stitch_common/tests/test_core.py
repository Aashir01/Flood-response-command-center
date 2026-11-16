"""BOOT-P1, P2, P3 and the core helpers (BOOT-R2.1 to R2.3, R2.5)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from stitch_common import CONTRACT_VERSION
from stitch_common.envelope import ErrorInfo, ToolResult, fail, ok
from stitch_common.logging import JsonFormatter, redact
from stitch_common.provenance import Provenance, build_provenance, canonical_json, inputs_hash
from stitch_common.types import BBox, Citation, Interval

REPO = Path(__file__).resolve().parents[3]


def _prov(inputs: Any = None) -> Provenance:
    return build_provenance(
        organ="ledger", tool="t", tool_version="0.1.0", inputs=inputs or {}, mode="demo"
    )


# --- BOOT-P3 ----------------------------------------------------------------
finite = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9)


@given(finite, finite, finite)
def test_p3_interval_validates_iff_ordered(a: float, b: float, c: float) -> None:
    ordered = a <= b <= c
    if ordered:
        iv = Interval(p10=a, p50=b, p90=c)
        assert iv.p10 <= iv.p50 <= iv.p90
    else:
        with pytest.raises(ValidationError):
            Interval(p10=a, p50=b, p90=c)


@given(st.lists(finite, min_size=3, max_size=3))
def test_p3_sorted_triple_always_valid(xs: list[float]) -> None:
    lo, mid, hi = sorted(xs)
    assert Interval(p10=lo, p50=mid, p90=hi).p50 == mid


# --- BOOT-P1 ----------------------------------------------------------------
@given(
    ok_flag=st.booleans(),
    has_data=st.booleans(),
    has_error=st.booleans(),
)
def test_p1_envelope_invariant(ok_flag: bool, has_data: bool, has_error: bool) -> None:
    kwargs: dict[str, Any] = {
        "ok": ok_flag,
        "data": {"x": 1} if has_data else None,
        "error": ErrorInfo(code="INTERNAL", message="m", retryable=False) if has_error else None,
        "provenance": _prov(),
    }
    expected_valid = (ok_flag and has_data and not has_error) or (
        not ok_flag and has_error and not has_data
    )
    if expected_valid:
        ToolResult[Any](**kwargs)
    else:
        with pytest.raises(ValidationError):
            ToolResult[Any](**kwargs)


def test_ok_and_fail_constructors() -> None:
    good = ok({"a": 1}, _prov(), warnings=["w"])
    assert good.ok and good.error is None and good.warnings == ["w"]
    bad = fail("NOT_FOUND", "nope", False, _prov())
    assert not bad.ok and bad.data is None and bad.error is not None
    assert bad.error.code == "NOT_FOUND"


def test_envelope_round_trips_through_json() -> None:
    res = ok({"a": 1}, _prov())
    again = ToolResult[dict[str, int]].model_validate_json(res.model_dump_json())
    assert again == res


# --- BOOT-P2 ----------------------------------------------------------------
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(), c, max_size=4),
    max_leaves=12,
)


@given(st.dictionaries(st.text(), json_values, min_size=1, max_size=6), st.randoms())
def test_p2_hash_invariant_to_key_order(obj: dict[str, Any], rnd: Any) -> None:
    keys = list(obj)
    rnd.shuffle(keys)
    shuffled = {k: obj[k] for k in keys}
    assert inputs_hash(obj) == inputs_hash(shuffled)
    assert canonical_json(obj) == canonical_json(shuffled)


@given(json_values, json_values)
def test_p2_hash_differs_for_different_inputs(a: Any, b: Any) -> None:
    if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
        assert inputs_hash({"v": a}) != inputs_hash({"v": b})


def test_inputs_hash_accepts_models_and_is_hex64() -> None:
    iv = Interval(p10=1, p50=2, p90=3)
    h = inputs_hash(iv)
    assert len(h) == 64 and h == inputs_hash({"p10": 1.0, "p50": 2.0, "p90": 3.0})


def test_provenance_defaults() -> None:
    p = _prov({"a": 1})
    assert p.contract_version == CONTRACT_VERSION
    assert p.generated_at.tzinfo is not None
    p2 = build_provenance(
        organ="eyes",
        tool="t",
        tool_version="1",
        inputs={},
        mode="live",
        run_id="2f5e2b0e-6b36-4b3c-8a55-5d7a1f2f9c11",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert p2.run_id.startswith("2f5e")
    with pytest.raises(ValidationError):
        Provenance(**{**p.model_dump(), "run_id": "not-a-uuid"})
    with pytest.raises(ValidationError):
        Provenance(**{**p.model_dump(), "generated_at": datetime(2026, 1, 1)})


# --- types ------------------------------------------------------------------
def _citation(**over: Any) -> dict[str, Any]:
    base = {
        "doc_id": "d1",
        "title": "t",
        "publisher": "p",
        "page": 1,
        "span": [0, 5],
        "quote": "q",
        "lang": "en",
        "url": None,
    }
    return {**base, **over}


@pytest.mark.parametrize(
    "over",
    [
        {"page": 0},
        {"span": [5, 1]},
        {"span": [-1, 2]},
        {"quote": "x" * 401},
        {"lang": "fr"},
        {"extra": 1},
    ],
)
def test_citation_rejects_bad_values(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Citation(**_citation(**over))


def test_citation_accepts_valid() -> None:
    assert Citation(**_citation(quote="x" * 400)).page == 1


def test_bbox_validation() -> None:
    ta = TypeAdapter(BBox)
    assert ta.validate_python([60, 20, 70, 30]) == (60, 20, 70, 30)
    for bad in ([70, 20, 60, 30], [60, 30, 70, 20], [60, 20, 70, 95], [60, 20, 70]):
        with pytest.raises(ValidationError):
            ta.validate_python(bad)


def test_models_are_frozen_and_forbid_extra() -> None:
    iv = Interval(p10=1, p50=2, p90=3)
    with pytest.raises(ValidationError):
        iv.p10 = 0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Interval(p10=1, p50=2, p90=3, p99=4)  # type: ignore[call-arg]


# --- logging ----------------------------------------------------------------
def test_redact_by_key_and_value() -> None:
    out = redact(
        {
            "api_key": "abc",
            "note": "token is ghp_" + "a" * 30,
            "nested": {"password": "x"},
            "ok": "fine",
        }
    )
    assert out["api_key"] == "[REDACTED]"
    assert "ghp_" not in out["note"]
    assert out["nested"]["password"] == "[REDACTED]"
    assert out["ok"] == "fine"


def test_json_formatter_redacts_extra_fields() -> None:
    rec = logging.LogRecord("n", logging.INFO, "f", 1, "hello", (), None)
    rec.__dict__["secret_value"] = "s3cr3t"
    rec.__dict__["run"] = "r1"
    data = json.loads(JsonFormatter().format(rec))
    assert data["secret_value"] == "[REDACTED]" and data["run"] == "r1" and data["msg"] == "hello"


def test_contract_version_matches_markdown_heading() -> None:
    text = (REPO / ".kiro" / "steering" / "mcp-contracts.md").read_text(encoding="utf-8")
    assert f"# MCP contracts (v{CONTRACT_VERSION})" in text
