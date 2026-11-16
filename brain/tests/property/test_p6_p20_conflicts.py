"""Conflict stage, one-shot reconciliation, seeded scenarios (task 16; BRN-P6, BRN-P20,
BRN-R4.1 to R4.4)."""

from __future__ import annotations

import random
import shutil
from pathlib import Path
from typing import Any

from brain_testkit import DEFAULT_WORLD, all_claims, fixture_result, render_world, world_store
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.brain.scenarios import R2, R3, default_scenarios
from stitch_brain.config import load_i18n, load_rules, load_scenarios
from stitch_brain.core.conflicts import apply_disputed, records_from
from stitch_brain.core.facts import FactCtx
from stitch_brain.core.rules import evaluate, parse_ruleset
from stitch_brain.paths import recorded_dir
from stitch_brain.runtime.recorded import DirectoryFixtureSource
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.settings import Settings

SC = load_scenarios()["demo-sindh-2022"]


async def _conflict_run(**kw: Any) -> Any:
    from brain_testkit import run_briefing

    return await run_briefing("demo-sindh-2022-conflicts", **kw)


async def test_seeded_scenario_reconciles_r2_and_flags_r3() -> None:
    res = await _conflict_run()
    b = res.briefing
    by_rule = {c.rule_id: c for c in b.conflicts}
    assert set(by_rule) == {R2, R3}
    r2, r3 = by_rule[R2], by_rule[R3]
    assert r2.resolution == "reconciled" and r3.resolution == "flagged"
    ledger_runs = {e.run_id for e in r2.evidence if e.tool == "optimize_allocation"}
    assert len(ledger_runs) == 2  # both Ledger runs are cited
    assert any(e.organ == "eyes" for e in r2.evidence)
    claims = {c.id: c for c in all_claims(b)}
    assert f"caveat.conflict.{r2.id.lower()}" in claims
    assert f"caveat.conflict.{r3.id.lower()}" in claims
    summary = claims["allocation.summary"]
    assert f"(disputed, see conflict {r3.id})" in summary.text and "disputed" in summary.labels
    assert f"conflict {r2.id})" not in summary.text  # reconciled adds no marker
    plans = [e for e in res.events if e.event == "plan"]
    assert [p.payload["revision"] for p in plans] == [1, 2]
    assert plans[1].payload["added"] == ["ledger.rerun"]
    events = [e for e in res.events if e.event == "conflict"]
    assert [e.payload["status"] for e in events if e.payload["id"] == r2.id] == [
        "reconciling",
        "final",
    ]
    # final allocation is the re-run
    assert res.store.by_node("ledger.final").node_id == "ledger.rerun"


async def test_brn_p20_at_most_one_rerun_and_terminates_when_rules_always_fire() -> None:
    import yaml

    from stitch_brain.config import config_dir

    raw = yaml.safe_load((config_dir() / "conflict_rules.yaml").read_text(encoding="utf-8"))
    for r in raw["rules"]:
        r["when"] = {"gte": [next(iter(r["facts"])), {"const": -1}]}  # always true
        r["reconcile"] = {"action": "rerun_ledger", "severity_source": "eyes_only"}
    rules = parse_ruleset(raw)
    res = await _conflict_run(rules=rules)
    calls = [e for e in res.events if e.event == "organ_call" and e.task_id == "ledger.rerun"]
    results = [e for e in res.events if e.event == "organ_result" and e.task_id == "ledger.rerun"]
    assert len(results) == 1 and len(calls) <= 3
    resolutions = sorted(c.resolution for c in res.briefing.conflicts)
    assert resolutions.count("escalated") == 1  # the one reconcile attempt still fires
    assert resolutions.count("reconciled") == 0
    assert res.briefing is not None


async def test_rerun_failure_escalates_and_keeps_the_original_allocation(tmp_path: Path) -> None:
    dst = tmp_path / "recorded"
    shutil.copytree(recorded_dir(), dst)
    (dst / "ledger" / "optimize_allocation" / "demo-sindh-2022-conflicts-eyes_only.json").unlink()
    reg = OrganRegistry.build(
        Settings(recorded_organs=("all",)), None, fixtures=DirectoryFixtureSource(dst)
    )
    res = await _conflict_run(registry=reg)
    r2 = next(c for c in res.briefing.conflicts if c.rule_id == R2)
    assert r2.resolution == "escalated"
    assert res.store.by_node("ledger.final").node_id == "ledger.optimize"
    summary = next(c for c in all_claims(res.briefing) if c.id == "allocation.summary")
    assert f"conflict {r2.id})" in summary.text


@settings(max_examples=25, deadline=None)
@given(st.integers(0, 2**20))
def test_brn_p6_seeded_conflicts_are_always_flagged(seed: int) -> None:
    base = {k: fixture_result(*v) for k, v in DEFAULT_WORLD.items()}
    for sc in default_scenarios(seed, per_family=1):
        store = world_store(sc.apply(base))
        outcomes = evaluate(load_rules(), FactCtx(store, SC))
        fired = {o.rule.id for o in outcomes if o.fired}
        if sc.control:
            assert fired == set(), sc.name
            continue
        assert sc.expects <= fired, (sc.name, fired)
        recs = records_from(outcomes, load_rules().params, load_i18n(), SC)
        drafts = render_world(store)
        apply_disputed(drafts, recs, load_i18n().pack("en").disputed_suffix, "en")
        for rec in recs:
            marked = [d for d in drafts if rec.cid in d.disputed_by]
            present = [a for a in rec.outcome.rule.affects if any(d.id == a for d in drafts)]
            assert len(marked) == len(present) >= 1, (sc.name, rec.cid)


def test_thirty_default_scenarios() -> None:
    scs = default_scenarios(0)
    assert len(scs) == 30 and sum(s.control for s in scs) == 9
    assert {R2, R3} <= {r for s in scs for r in s.expects}
    random.Random(0)
