"""Recorded organs: matching rules, fixture validation, labels, BRN-P19 first half (task 7)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.paths import recorded_dir, repo_root
from stitch_brain.runtime.organs import CallContext
from stitch_brain.runtime.recorded import (
    RECORDED_PREFIX,
    DirectoryFixtureSource,
    Fixture,
    RecordedOrgan,
    deep_subset,
    label_result,
    select,
)
from stitch_brain.runtime.validate import ContractViolation, validate_tool_result

CTX = CallContext(
    briefing_id="b1", node_id="ledger.optimize", attempt=1, scenario="demo-sindh-2022"
)


def _fx(path: str, args: dict[str, Any], scenario: str | None = None) -> Fixture:
    return Fixture(
        path=path,
        organ="o",
        tool="t",
        match_scenario=scenario,
        match_args=args,
        authoring="hand_authored",
        result={},
    )


def test_deep_subset_semantics() -> None:
    assert deep_subset({"a": {"b": 1}}, {"a": {"b": 1, "c": 2}, "d": 3})
    assert not deep_subset({"a": [1]}, {"a": [1, 2]})
    assert deep_subset({}, {"x": 1})


def test_most_specific_wins_and_ties_break_by_name() -> None:
    fx = [
        _fx("b.json", {}),
        _fx("a.json", {"x": 1}),
        _fx("c.json", {"x": 1}),
        _fx("z.json", {}, scenario="s"),
    ]
    assert select(fx, "other", {"x": 1, "y": 2}).path == "a.json"  # type: ignore[union-attr]
    assert select(fx, "s", {"x": 1}).path == "z.json"  # type: ignore[union-attr]
    assert select([_fx("a.json", {"x": 2})], "s", {"x": 1}) is None


def test_every_committed_fixture_validates_against_stitch_common() -> None:
    src = DirectoryFixtureSource(recorded_dir())
    fixtures = list(src.all_fixtures())
    assert fixtures, "no recorded fixtures committed"
    for f in fixtures:
        assert f.authoring in ("captured", "hand_authored")
        if f.authoring == "hand_authored" and f.result.get("ok"):
            ids = [d["id"] for d in f.result["provenance"]["data_sources"]]
            assert "fixture-hand-authored" in ids, f.path


async def test_recorded_organ_labels_and_rewrites_run_id() -> None:
    organ = RecordedOrgan("ledger", DirectoryFixtureSource(recorded_dir()), ["optimize_allocation"])
    src = DirectoryFixtureSource(recorded_dir())
    fx = next(
        f for f in src.fixtures("ledger", "optimize_allocation") if f.match_scenario == CTX.scenario
    )
    out = await organ.call_tool("optimize_allocation", fx.match_args, timeout_s=1, ctx=CTX)
    assert out.result is not None and out.result["ok"]
    assert out.result["warnings"][-1].startswith(RECORDED_PREFIX)
    assert out.result["provenance"]["run_id"] != fx.result["provenance"]["run_id"]
    assert out.source == fx.path and out.original_sha256
    assert organ.health().served_by == "recorded"
    sens = await organ.call_tool(
        "sensitivity_report", {"run_id": out.result["provenance"]["run_id"]}, timeout_s=1, ctx=CTX
    )
    assert sens.result is not None and sens.result["ok"], sens.result


async def test_no_match_is_not_found_and_invents_nothing() -> None:
    organ = RecordedOrgan("ledger", DirectoryFixtureSource(recorded_dir()), [])
    out = await organ.call_tool(
        "optimize_allocation", {"scenario_id": "nope"}, timeout_s=1, ctx=CTX
    )
    assert out.result is not None and out.result["ok"] is False
    assert out.result["error"]["code"] == "NOT_FOUND"
    validate_tool_result("ledger", "optimize_allocation", out.result)


def test_invalid_fixture_is_rejected(tmp_path: Path) -> None:
    src = DirectoryFixtureSource(recorded_dir())
    bad = copy.deepcopy(src.fixtures("ledger", "optimize_allocation")[0].result)
    bad["data"]["status"] = "maybe"
    with pytest.raises(ContractViolation):
        validate_tool_result("ledger", "optimize_allocation", bad)


@settings(deadline=None)
@given(st.lists(st.text(max_size=20), max_size=4), st.booleans())
def test_brn_p19_fixture_content_cannot_remove_the_label(warnings: list[str], drop: bool) -> None:
    src = DirectoryFixtureSource(recorded_dir(), repo_root())
    base = copy.deepcopy(src.fixtures("ledger", "optimize_allocation")[0].result)
    base["warnings"] = [] if drop else warnings
    out = label_result(base, "data/demo/recorded/x.json", CTX)
    assert out["warnings"][-1].startswith(f"{RECORDED_PREFIX}: served from data/demo/recorded/")
