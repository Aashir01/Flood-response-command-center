"""Default task graphs per scenario and the argument-builder registry (design 7.1, 7.2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from stitch_brain.config import ScenarioCfg
from stitch_brain.core.evidence import EvidenceStore
from stitch_brain.core.graph import Dep, Node, Plan, PlanError, validate_plan

#: Optional nodes an LLM plan variation may add or drop (design 7.2).
OPTIONAL_WHITELIST = ("oracle.explain", "ledger.sensitivity")
ORGAN_NODE_KINDS = ("organ", "resource", "derive")
ANALYSIS_STAGES = ("conflicts", "synth", "phrase", "translate", "critic", "assemble")


@dataclass
class BuildContext:
    scenario: ScenarioCfg
    store: EvidenceStore
    lang: str = "en"
    mode: str = "demo"
    #: ``derive.ledger_input`` results by severity mode ("full", "eyes_only"); the value is the
    #: ``optimize_allocation`` argument dict.
    ledger_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


Builder = Callable[[BuildContext, Node], dict[str, Any]]


def _eyes(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return {
        "region_id": ctx.scenario.region,
        "date": ctx.scenario.eyes.date.isoformat(),
        "mode": ctx.mode,
    }


def _oracle_forecast(ctx: BuildContext, node: Node) -> dict[str, Any]:
    o = ctx.scenario.oracle
    args: dict[str, Any] = {
        "station_id": o.station_id,
        "horizon_days": o.horizon_days,
        "coverage": o.coverage,
        "mode": ctx.mode,
    }
    if o.as_of is not None:
        args["as_of"] = o.as_of.isoformat()
    return args


def _run_id_of(ctx: BuildContext, node_id: str) -> dict[str, Any]:
    entry = ctx.store.ok_node(node_id)
    run_id = (entry.result.get("provenance") or {}).get("run_id") if entry else None
    return {"run_id": str(run_id or "missing")}


def _oracle_explain(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return _run_id_of(ctx, "oracle.forecast")


def _library(ctx: BuildContext, node: Node) -> dict[str, Any]:
    qid = node.params.get("qid", "")
    q = next(q for q in ctx.scenario.guidance_questions if q.id == qid)
    return {"query": q.query.get(ctx.lang), "lang": ctx.lang, "answer_lang": ctx.lang}


def _districts(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return {"uri": f"ledger://scenario/{ctx.scenario.ledger_scenario_id}/districts"}


def ledger_fallback_args(scenario: ScenarioCfg, mode: str) -> dict[str, Any]:
    """Ledger call without a ``districts`` override: the Ledger uses its dataset defaults."""
    args: dict[str, Any] = {
        "scenario_id": scenario.ledger_scenario_id,
        "commodities": [
            {
                "id": c.id,
                "name": c.name.en,
                "unit": c.unit,
                "unit_cost": c.unit_cost,
                "per_person_need": c.need(scenario.period_days),
            }
            for c in scenario.commodities
        ],
        "supply": dict(scenario.supply),
        "integer": scenario.integer,
        "mode": mode,
    }
    if scenario.budget is not None:
        args["budget"] = scenario.budget
    if scenario.equity_floor is not None:
        args["equity_floor"] = scenario.equity_floor
    return args


def _ledger_optimize(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return dict(ctx.ledger_inputs.get("full") or ledger_fallback_args(ctx.scenario, ctx.mode))


def _ledger_rerun(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return dict(ctx.ledger_inputs.get("eyes_only") or ledger_fallback_args(ctx.scenario, ctx.mode))


def _ledger_sensitivity(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return _run_id_of(ctx, "ledger.optimize")


def _none(ctx: BuildContext, node: Node) -> dict[str, Any]:
    return {}


BUILDERS: dict[str, Builder] = {
    "eyes.args": _eyes,
    "oracle.forecast_args": _oracle_forecast,
    "oracle.explain_args": _oracle_explain,
    "library.question_args": _library,
    "ledger.districts_uri": _districts,
    "derive.ledger_input": _none,
    "ledger.optimize_args": _ledger_optimize,
    "ledger.rerun_args": _ledger_rerun,
    "ledger.sensitivity_args": _ledger_sensitivity,
    "analysis": _none,
}


def default_plan(scenario: ScenarioCfg, plan_id: str = "plan") -> Plan:
    s = Dep.model_validate
    organ_ids: list[str] = []

    def organ(node: Node) -> Node:
        organ_ids.append(node.id)
        return node

    nodes: list[Node] = [
        organ(
            Node(
                id="eyes.segment",
                kind="organ",
                organ="eyes",
                tool="segment_flood",
                builder="eyes.args",
                timeout_s=30,
            )
        ),
        organ(
            Node(
                id="eyes.compare",
                kind="organ",
                organ="eyes",
                tool="compare_with_permanent_water",
                builder="eyes.args",
                timeout_s=30,
            )
        ),
        organ(
            Node(
                id="oracle.forecast",
                kind="organ",
                organ="oracle",
                tool="forecast_river",
                builder="oracle.forecast_args",
                timeout_s=8,
            )
        ),
        organ(
            Node(
                id="oracle.explain",
                kind="organ",
                organ="oracle",
                tool="explain_forecast",
                builder="oracle.explain_args",
                deps=[s({"id": "oracle.forecast"})],
                optional=True,
                timeout_s=8,
            )
        ),
    ]
    for q in scenario.guidance_questions:
        nodes.append(
            organ(
                Node(
                    id=f"library.{q.id}",
                    kind="organ",
                    organ="library",
                    tool="answer_with_citations",
                    builder="library.question_args",
                    params={"qid": q.id},
                    timeout_s=20,
                )
            )
        )
    nodes += [
        organ(
            Node(
                id="ledger.districts",
                kind="resource",
                organ="ledger",
                tool="resource:districts",
                builder="ledger.districts_uri",
                timeout_s=5,
            )
        ),
        organ(
            Node(
                id="derive.ledger_input",
                kind="derive",
                builder="derive.ledger_input",
                deps=[
                    s({"id": "eyes.compare", "need": "soft"}),
                    s({"id": "oracle.forecast", "need": "soft"}),
                    s({"id": "ledger.districts", "need": "soft"}),
                ],
                timeout_s=2,
                max_attempts=1,
            )
        ),
        organ(
            Node(
                id="ledger.optimize",
                kind="organ",
                organ="ledger",
                tool="optimize_allocation",
                builder="ledger.optimize_args",
                deps=[s({"id": "derive.ledger_input", "need": "soft"})],
                timeout_s=15,
            )
        ),
        organ(
            Node(
                id="ledger.sensitivity",
                kind="organ",
                organ="ledger",
                tool="sensitivity_report",
                builder="ledger.sensitivity_args",
                deps=[s({"id": "ledger.optimize"})],
                optional=True,
                timeout_s=15,
            )
        ),
    ]
    soft_all = [s({"id": i, "need": "soft"}) for i in organ_ids]
    nodes += [
        Node(
            id="conflicts",
            kind="analysis",
            builder="analysis",
            deps=soft_all,
            timeout_s=2,
            max_attempts=1,
        ),
        Node(
            id="synth",
            kind="synthesis",
            builder="analysis",
            deps=[s({"id": "conflicts", "need": "soft"})],
            timeout_s=5,
            max_attempts=1,
        ),
        Node(
            id="phrase",
            kind="llm",
            builder="analysis",
            deps=[s({"id": "synth"})],
            optional=True,
            timeout_s=20,
            max_attempts=1,
        ),
        Node(
            id="translate",
            kind="llm",
            builder="analysis",
            deps=[s({"id": "synth"})],
            optional=True,
            timeout_s=20,
            max_attempts=1,
        ),
        Node(
            id="critic",
            kind="analysis",
            builder="analysis",
            deps=[
                s({"id": "synth"}),
                s({"id": "phrase", "need": "soft"}),
                s({"id": "translate", "need": "soft"}),
            ],
            timeout_s=20,
            max_attempts=1,
        ),
        Node(
            id="assemble",
            kind="analysis",
            builder="analysis",
            deps=[s({"id": "critic"})],
            timeout_s=2,
            max_attempts=1,
        ),
    ]
    plan = Plan(plan_id=plan_id, scenario=scenario.id, revision=1, planner="default", nodes=nodes)
    return validate_plan(plan, BUILDERS)


def rerun_node() -> Node:
    return Node(
        id="ledger.rerun",
        kind="organ",
        organ="ledger",
        tool="optimize_allocation",
        builder="ledger.rerun_args",
        deps=[Dep(id="ledger.optimize", need="soft"), Dep(id="derive.ledger_input", need="soft")],
        optional=True,
        timeout_s=15,
    )


def with_rerun(plan: Plan) -> Plan:
    """Revision 2 of a plan with the dynamic ``ledger.rerun`` node (design 9.4)."""
    if "ledger.rerun" in plan.ids():
        return plan
    nodes = list(plan.nodes)
    idx = plan.ids().index("synth")
    synth = nodes[idx]
    nodes[idx] = synth.model_copy(
        update={"deps": [*synth.deps, Dep(id="ledger.rerun", need="soft")]}
    )
    nodes.insert(idx, rerun_node())
    new = plan.model_copy(update={"nodes": nodes, "revision": plan.revision + 1})
    return validate_plan(new, BUILDERS)


def apply_variation(plan: Plan, reply: str) -> Plan:
    """An LLM plan variation (design 7.2, 12): strict JSON ``{"drop": [node ids]}`` where every
    id is an optional node from ``OPTIONAL_WHITELIST``. Anything else raises ``PlanError`` and
    the caller keeps the default plan (BRN-R2.3)."""
    import json

    try:
        obj = json.loads(reply)
    except ValueError as exc:
        raise PlanError([f"plan variation is not JSON: {exc}"]) from exc
    if not isinstance(obj, dict) or set(obj) != {"drop"} or not isinstance(obj["drop"], list):
        raise PlanError(['plan variation must be {"drop": [ids]}'])
    drop = obj["drop"]
    bad = [d for d in drop if not isinstance(d, str) or d not in OPTIONAL_WHITELIST]
    if bad:
        raise PlanError([f"not an optional node: {bad[0]!r}"])
    keep = [n for n in plan.nodes if n.id not in drop]
    nodes = [n.model_copy(update={"deps": [d for d in n.deps if d.id not in drop]}) for n in keep]
    new = plan.model_copy(update={"nodes": nodes, "planner": "llm"})
    return validate_plan(new, BUILDERS)


def organ_phase_nodes(plan: Plan) -> list[Node]:
    return [n for n in plan.nodes if n.kind in ORGAN_NODE_KINDS]
