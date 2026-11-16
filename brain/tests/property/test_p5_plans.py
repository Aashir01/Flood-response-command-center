"""BRN-P5: plans are acyclic, dependencies exist, builders are registered; default plans
validate for every shipped scenario."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stitch_brain.config import load_scenarios
from stitch_brain.core.graph import (
    MAX_NODES,
    Dep,
    Node,
    Plan,
    PlanError,
    find_problems,
    topological_levels,
    validate_plan,
)
from stitch_brain.core.plans import BUILDERS, default_plan, with_rerun

BUILDER_NAMES = set(BUILDERS)


@st.composite
def dags(draw: Any) -> tuple[Plan, bool]:
    """A random DAG (edges only to earlier nodes), then optionally one injected fault."""
    n = draw(st.integers(1, 12))
    ids = [f"n{i}" for i in range(n)]
    nodes: list[dict[str, Any]] = []
    for i, nid in enumerate(ids):
        deps = draw(st.lists(st.sampled_from(ids[:i]), unique=True, max_size=3)) if i else []
        nodes.append(
            {
                "id": nid,
                "kind": "analysis",
                "builder": "analysis",
                "deps": [{"id": d, "need": draw(st.sampled_from(["hard", "soft"]))} for d in deps],
            }
        )
    fault = draw(st.sampled_from(["none", "cycle", "self", "missing", "dup", "builder", "many"]))
    valid = fault == "none"
    if fault == "cycle" and n >= 2:
        nodes[0]["deps"].append({"id": ids[-1], "need": "hard"})
        if not any(d["id"] == ids[0] for d in nodes[-1]["deps"]):
            nodes[-1]["deps"].append({"id": ids[0], "need": "hard"})
    elif fault == "self":
        nodes[-1]["deps"].append({"id": ids[-1], "need": "hard"})
    elif fault == "missing":
        nodes[-1]["deps"].append({"id": "ghost", "need": "soft"})
    elif fault == "dup":
        nodes.append(dict(nodes[0]))
    elif fault == "builder":
        nodes[-1]["builder"] = "os.system"
    elif fault == "many":
        nodes += [
            {"id": f"x{i}", "kind": "analysis", "builder": "analysis", "deps": []}
            for i in range(MAX_NODES)
        ]
    else:
        valid = True if fault in ("none", "cycle") and n < 2 else valid
    plan = Plan(plan_id="p", scenario="s", nodes=[Node.model_validate(x) for x in nodes])
    # a short chain can still exceed depth limits only if n > 9; n <= 12 means check depth
    return plan, valid


@given(dags())
def test_brn_p5_validator_accepts_exactly_valid_dags(case: tuple[Plan, bool]) -> None:
    plan, valid = case
    problems = find_problems(plan, BUILDER_NAMES)
    depth_ok = True
    if valid:
        depth_ok = len(topological_levels(plan)) - 1 <= 8
    assert (not problems) == (valid and depth_ok)
    if not problems:
        for level_i, level in enumerate(topological_levels(plan)):
            for nid in level:
                for d in plan.node(nid).deps:
                    assert any(d.id in lv for lv in topological_levels(plan)[:level_i])


@pytest.mark.parametrize("sid", sorted(load_scenarios()))
def test_default_plans_validate(sid: str) -> None:
    plan = default_plan(load_scenarios()[sid])
    validate_plan(plan, BUILDER_NAMES)
    assert plan.revision == 1
    p2 = with_rerun(plan)
    assert p2.revision == 2 and "ledger.rerun" in p2.ids()
    assert with_rerun(p2) is p2


def test_unavailable_organ_tool_is_rejected() -> None:
    plan = default_plan(load_scenarios()["demo-sindh-2022"])
    with pytest.raises(PlanError) as err:
        validate_plan(plan, BUILDER_NAMES, available={("ledger", "optimize_allocation")})
    assert "eyes.segment" in str(err.value)


def test_dep_model_rejects_expressions_in_ids() -> None:
    with pytest.raises(ValueError):
        Node(id="bad id; rm", kind="analysis", builder="analysis")
    assert Dep(id="x").need == "hard"
