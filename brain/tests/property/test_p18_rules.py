"""Facts and the rule engine (task 15; BRN-P18, BRN-R4.1, R4.4)."""

from __future__ import annotations

import contextlib
import json
import random
import re
from pathlib import Path
from typing import Any

import pytest
from brain_testkit import DEFAULT_WORLD, fixture_result, json_docs, world_store
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.brain.scenarios import (
    R1,
    R2,
    R3,
    control_all_flooded,
    control_need_within_tolerance,
    control_oracle_high,
    dry_district,
    need_mismatch,
    oracle_low,
)
from stitch_brain.config import config_dir, load_rules, load_scenarios
from stitch_brain.core import facts as facts_mod
from stitch_brain.core import rules as rules_mod
from stitch_brain.core.facts import FactCtx, Unavailable
from stitch_brain.core.rules import (
    RuleConfigError,
    evaluate,
    load_ruleset_text,
    parse_ruleset,
    rules_json_schema,
)

SC = load_scenarios()["demo-sindh-2022"]


def _base_world() -> dict[str, Any]:
    return {k: fixture_result(*v) for k, v in DEFAULT_WORLD.items()}


def _fired(world: dict[str, Any]) -> set[str]:
    store = world_store(world)
    return {o.rule.id for o in evaluate(load_rules(), FactCtx(store, SC)) if o.fired}


def test_shipped_rules_load_and_schema_is_current() -> None:
    rs = load_rules()
    assert [r.id for r in rs.rules] == [R1, R2, R3]
    committed = json.loads((config_dir() / "conflict_rules.schema.json").read_text("utf-8"))
    assert committed == rules_json_schema()


@pytest.mark.parametrize("sid", sorted(load_scenarios()))
def test_eyes_dry_frac_equals_severity_noise_floor(sid: str) -> None:
    assert load_rules().params["eyes_dry_frac"] == load_scenarios()[sid].severity.f_noise


def test_static_scan_forbids_dynamic_code() -> None:
    for mod in (rules_mod, facts_mod):
        src = Path(mod.__file__ or "").read_text(encoding="utf-8")
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        for name in ("eval", "exec", "compile", "getattr", "__import__"):
            # builtins only: re.compile is a regex constructor, not code compilation
            assert not re.search(rf"(?<![\w.]){name}\s*\(", code), (mod.__name__, name)


@settings(deadline=None)
@given(json_docs(30))
def test_brn_p18_fuzz_loads_or_raises_rule_config_error(raw: Any) -> None:
    with contextlib.suppress(RuleConfigError):
        parse_ruleset(raw)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["rules"][0]["facts"].update(p="nope.fact"),
        lambda r: r["rules"][0]["when"]["all"][0]["lt"].__setitem__(1, {"param": "missing"}),
        lambda r: r["rules"][1].update(
            reconcile={"action": "rerun_ledger", "severity_source": "eyes_only", "max_times": 2}
        ),
        lambda r: r["rules"][1].pop("foreach"),
        lambda r: r["rules"][0]["when"].update(any=[]),
        lambda r: r["rules"][2]["when"].update(rel_diff_gt=["lib", "led"]),
    ],
)
def test_bad_rule_files_raise(mutate: Any) -> None:
    import yaml

    raw = yaml.safe_load((config_dir() / "conflict_rules.yaml").read_text(encoding="utf-8"))
    mutate(raw)
    with pytest.raises(RuleConfigError):
        parse_ruleset(raw)
    with pytest.raises(RuleConfigError):
        load_ruleset_text("rules: [unterminated")


def test_headline_world_is_conflict_free() -> None:
    assert _fired(_base_world()) == set()


@pytest.mark.parametrize(
    ("mutator", "rule"), [(oracle_low, R1), (dry_district, R2), (need_mismatch, R3)]
)
def test_each_rule_fires_on_a_hand_built_world(mutator: Any, rule: str) -> None:
    w = _base_world()
    mutator(w, random.Random(1))
    assert _fired(w) == {rule}


@settings(deadline=None)
@given(
    st.integers(0, 10_000),
    st.sampled_from([control_oracle_high, control_all_flooded, control_need_within_tolerance]),
)
def test_brn_p18_controls_never_fire(seed: int, control: Any) -> None:
    w = _base_world()
    control(w, random.Random(seed))
    assert _fired(w) == set()


def test_unavailable_fact_skips_the_rule_with_a_reason() -> None:
    store = world_store({"oracle.forecast": None})
    out = evaluate(load_rules(), FactCtx(store, SC))
    r1 = next(o for o in out if o.rule.id == R1)
    assert not r1.fired and r1.skipped and "oracle" in r1.skipped
    assert isinstance(facts_mod.oracle_max_exceedance(FactCtx(store, SC)), Unavailable)


def test_basin_flooded_fraction_and_keyed_facts() -> None:
    store = world_store()
    ctx = FactCtx(store, SC)
    fl = facts_mod.eyes_basin_flooded_fraction(ctx)
    assert not isinstance(fl, Unavailable | dict) and 0 < fl.value < 1
    lib = facts_mod.library_guidance_per_person_per_day(ctx)
    led = facts_mod.ledger_need_per_person_per_day(ctx)
    assert isinstance(lib, dict) and isinstance(led, dict)
    assert lib["water"].value == led["water"].value == 15
    for f in (fl, lib["water"], led["water"]):
        assert all(store.resolves(r) for r in f.refs)  # type: ignore[union-attr]


def test_ambiguous_library_quantity_is_omitted() -> None:
    lib = fixture_result("library", "answer_with_citations", "water-en")
    lib["data"]["quantities"].append(
        {"value": 20.0, "unit": "litre", "per": "person_day", "claim_idx": 0}
    )
    ctx = FactCtx(world_store({"library.water": lib}), SC)
    out = facts_mod.library_guidance_per_person_per_day(ctx)
    assert isinstance(out, dict) and "water" not in out
    assert any("distinct" in t for t in ctx.trace)


def test_regex_fallback_reads_the_claim_text() -> None:
    lib = fixture_result("library", "answer_with_citations", "water-en")
    lib["data"]["quantities"] = []
    out = facts_mod.library_guidance_per_person_per_day(
        FactCtx(world_store({"library.water": lib}), SC)
    )
    assert isinstance(out, dict) and out["water"].value == 15
