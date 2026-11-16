"""One briefing run: plan -> organ phase -> conflicts (and one reconciliation) -> synth ->
phrase/translate -> critic -> assemble (design 7.1). Emits ``TaskEvent``s through ``emit``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stitch_brain.config import I18n, ScenarioCfg, load_i18n, load_rules, load_scenarios
from stitch_brain.core.briefing import StatusInputs, assemble, labels_for, section_status
from stitch_brain.core.claims import SECTION_ORDER, ClaimDraft
from stitch_brain.core.confidence import ConfidenceParams, confidence, organ_confidences
from stitch_brain.core.conflicts import ConflictRecord, apply_disputed, entry_data, records_from
from stitch_brain.core.evidence import (
    EvidenceEntry,
    EvidenceStore,
    brain_entry,
    det_uuid,
    sha256_json,
)
from stitch_brain.core.facts import FactCtx
from stitch_brain.core.graph import Node, Plan
from stitch_brain.core.plans import (
    BUILDERS,
    BuildContext,
    default_plan,
    organ_phase_nodes,
    with_rerun,
)
from stitch_brain.core.rules import RuleSet, evaluate, evaluate_rule
from stitch_brain.core.severity import build_ledger_input
from stitch_brain.core.synth import render_all
from stitch_brain.core.templates.common import RenderCtx
from stitch_brain.runtime.clock import Clock, RealClock
from stitch_brain.runtime.executor import AttemptResult, ErrorDict, Executor, Limits, NodeOutcome
from stitch_brain.runtime.organs import CallContext, CallOutcome, OrganClient
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.runtime.validate import ContractViolation, validate_input
from stitch_brain.settings import Settings
from stitch_common import CONTRACT_VERSION
from stitch_common.brain import Briefing, BriefingOrgan, Conflict, CriticVerdict, TaskEvent
from stitch_common.brain_api import BriefingRequest
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.provenance import inputs_hash

Emit = Callable[[TaskEvent], None]
SUMMARY_MAX = 10


class RunError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RunResult:
    briefing: Briefing | None
    store: EvidenceStore
    plan: Plan
    outcomes: dict[str, NodeOutcome]
    drafts: list[ClaimDraft] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    events: list[Any] = field(default_factory=list)


def _summary(data: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str | int | float | bool) or v is None:
                out[k] = v
            if len(out) >= SUMMARY_MAX:
                break
    return out


def _transport_error(out: CallOutcome) -> ErrorDict:
    te = out.transport_error
    assert te is not None
    if te.code == "TIMEOUT":
        return ErrorDict("TIMEOUT", te.message, True)
    if te.code == "PROTOCOL":
        msg = te.message if te.message.startswith("contract") else f"protocol error: {te.message}"
        return ErrorDict("INTERNAL", msg, False)
    retry = te.code == "CONNECTION" or te.message == "circuit open"
    return ErrorDict("UPSTREAM_UNAVAILABLE", te.message, retry)


class BriefingRunner:
    def __init__(
        self,
        registry: OrganRegistry,
        *,
        settings: Settings | None = None,
        clock: Clock | None = None,
        scenarios: Mapping[str, ScenarioCfg] | None = None,
        i18n: I18n | None = None,
        conf_params: ConfidenceParams | None = None,
        rules: RuleSet | None = None,
        llm: Any = None,
    ) -> None:
        self.registry = registry
        self.settings = settings or registry.settings
        self.clock = clock or RealClock()
        self.scenarios = dict(scenarios or load_scenarios())
        self.i18n = i18n or load_i18n()
        self.conf_params = conf_params or ConfidenceParams()
        self.rules: RuleSet = rules or load_rules()
        self.llm = llm

    # --- entries -----------------------------------------------------------------------------
    def _failed_result(
        self, node: Node, attempt: int, err: ErrorDict, bid: str, n: int
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "data": None,
            "error": err.as_dict(),
            "provenance": {
                "organ": node.organ or "brain",
                "tool": node.tool or node.id,
                "tool_version": "unknown",
                "contract_version": CONTRACT_VERSION,
                "run_id": det_uuid(bid, node.id, str(attempt), "failure", str(n)),
                "inputs_hash": inputs_hash({"node": node.id}),
                "mode": "demo",
                "data_sources": [],
                "model": None,
                "models": [],
                "generated_at": self.clock.now().isoformat(),
            },
            "warnings": [],
        }

    async def run(
        self, request: BriefingRequest, briefing_id: str, emit: Emit | None = None
    ) -> RunResult:
        emit = emit or (lambda e: None)
        run = _Run(self, request, briefing_id, emit)
        return await run.execute()


class _Run:
    """State of one run. Kept separate so the runner can serve several runs concurrently."""

    def __init__(self, r: BriefingRunner, req: BriefingRequest, bid: str, emit: Emit) -> None:
        self.r = r
        self.req = req
        self.bid = bid
        self._emit = emit
        scenario = r.scenarios.get(req.scenario)
        if scenario is None:
            raise RunError("INVALID_INPUT", f"unknown scenario {req.scenario!r}")
        if scenario.region != req.region:
            raise RunError("INVALID_INPUT", f"scenario {req.scenario} is not for {req.region}")
        self.scenario = scenario
        self.store = EvidenceStore(bid)
        self.bctx = BuildContext(scenario=scenario, store=self.store, lang=req.lang, mode=req.mode)
        self.failures = 0
        self.call_inputs: dict[str, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self.started_at = r.clock.now()
        self.health_at_start = r.registry.health()
        self.reruns = 0
        self.rule_trace: list[str] = []

    # --- events ------------------------------------------------------------------------------
    def emit(
        self,
        event: str,
        task_id: str,
        payload: dict[str, Any],
        *,
        organ: str | None = None,
        tool: str | None = None,
    ) -> None:
        self._emit(
            TaskEvent(
                event=event,
                ts=self.r.clock.now(),
                task_id=task_id,
                organ=organ,
                tool=tool,
                payload=payload,
            )
        )

    def plan_event(self, plan: Plan, added: list[str] | None = None) -> None:
        payload: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "revision": plan.revision,
            "planner": plan.planner,
            "scenario": plan.scenario,
            "lang": self.req.lang,
            "mode_requested": self.req.mode,
            "nodes": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "organ": n.organ,
                    "tool": n.tool,
                    "deps": [d.id for d in n.deps],
                    "optional": n.optional,
                }
                for n in plan.nodes
            ],
            "stub_organs": self.r.registry.stub_organs(),
        }
        if added:
            payload["added"] = added
        self.emit("plan", "plan", payload)

    # --- organ phase -------------------------------------------------------------------------
    def client(self, node: Node) -> OrganClient | None:
        return self.r.registry.get(node.organ or "")

    def on_call(self, node: Node, attempt: int, at: datetime) -> None:
        c = self.client(node)
        if node.kind not in ("organ", "resource") or c is None:
            return
        self.emit(
            "organ_call",
            node.id,
            {
                "attempt": attempt,
                "max_attempts": min(node.max_attempts, 3),
                "timeout_s": node.timeout_s,
                "served_by": c.served_by,
                "started_at": at.isoformat(),
            },
            organ=node.organ,
            tool=node.tool,
        )

    def on_result(self, node: Node, outcome: NodeOutcome) -> None:
        c = self.client(node)
        if node.kind not in ("organ", "resource") or c is None or outcome.attempts == 0:
            return
        entry = self.store.get(outcome.entry_id) if outcome.entry_id else None
        payload: dict[str, Any] = {
            "ok": outcome.ok,
            "attempt": max(outcome.attempts, 1),
            "duration_ms": float(outcome.duration_ms),
            "served_by": c.served_by,
            "run_id": entry.call_run_id if entry else det_uuid(self.bid, node.id, "none"),
            "mode": entry.mode if entry else "demo",
            "warnings": list((entry.result.get("warnings") or []) if entry else []),
            "summary": _summary(entry.result.get("data")) if entry and entry.ok else {},
        }
        if not outcome.ok:
            err = outcome.error or ErrorDict("INTERNAL", "failed", False)
            payload["error"] = err.as_dict()
        self.emit("organ_result", node.id, payload, organ=node.organ, tool=node.tool)

    def record_failure(self, node: Node, attempt: int, err: ErrorDict) -> str | None:
        if node.kind not in ("organ", "resource"):
            return None
        self.failures += 1
        res = self.r._failed_result(node, attempt, err, self.bid, self.failures)
        c = self.client(node)
        now = self.r.clock.now()
        entry = EvidenceEntry(
            call_run_id=res["provenance"]["run_id"],
            briefing_id=self.bid,
            node_id=node.id,
            organ=node.organ or "brain",
            tool=node.tool or node.id,
            served_by=c.served_by if c else "real",
            attempt=attempt,
            started_at=now,
            ended_at=now,
            result=res,
            original_sha256=sha256_json(res),
        )
        self.store.put(entry)
        return entry.call_run_id

    async def attempt(self, node: Node, attempt: int) -> AttemptResult:
        if node.kind == "derive":
            return self.derive(node)
        c = self.client(node)
        if c is None or node.tool is None:
            err = ErrorDict("UPSTREAM_UNAVAILABLE", f"no client for {node.organ}", False)
            return AttemptResult(False, self.record_failure(node, attempt, err), err)
        args = BUILDERS[node.builder](self.bctx, node)
        self.call_inputs[node.id] = args
        ctx = CallContext(self.bid, node.id, attempt, self.scenario.fixture_set)
        started, t0 = self.r.clock.now(), self.r.clock.monotonic()
        if node.kind == "resource":
            out = await c.read_resource(args["uri"], timeout_s=node.timeout_s, ctx=ctx)
        else:
            try:
                validate_input(node.organ or "", node.tool, args)
            except ContractViolation as exc:
                err = ErrorDict("INVALID_INPUT", f"brain built invalid arguments: {exc}", False)
                return AttemptResult(False, self.record_failure(node, attempt, err), err)
            out = await c.call_tool(node.tool, args, timeout_s=node.timeout_s, ctx=ctx)
        if out.result is None:
            err = _transport_error(out)
            return AttemptResult(False, self.record_failure(node, attempt, err), err)
        ended = self.r.clock.now()
        entry = EvidenceEntry(
            call_run_id=str(out.result["provenance"]["run_id"]),
            briefing_id=self.bid,
            node_id=node.id,
            organ=node.organ or "",
            tool=node.tool,
            served_by=c.served_by,
            attempt=attempt,
            started_at=started,
            ended_at=ended,
            duration_ms=round((self.r.clock.monotonic() - t0) * 1000),
            result=out.result,
            original_sha256=out.original_sha256 or sha256_json(out.result),
            source=out.source,
        )
        self.store.put(entry)  # stored before the node is marked done (BRN-R3.5)
        self.calls.append(
            {
                "node_id": node.id,
                "attempt": attempt,
                "args": args,
                "entry": entry.model_dump(mode="json"),
            }
        )
        if entry.ok:
            return AttemptResult(True, entry.call_run_id)
        e = out.result.get("error") or {}
        err = ErrorDict(
            str(e.get("code", "INTERNAL")),
            str(e.get("message", "")),
            bool(e.get("retryable", False)),
        )
        return AttemptResult(False, entry.call_run_id, err)

    def derive(self, node: Node, mode: str = "full") -> AttemptResult:
        data = build_ledger_input(
            self.scenario,
            eyes_compare=self.store.ok_node("eyes.compare"),
            oracle_forecast=self.store.ok_node("oracle.forecast"),
            districts=self.store.ok_node("ledger.districts"),
            packs=self.r.i18n.packs,
            mode="eyes_only" if mode == "eyes_only" else "full",
            request_mode=self.req.mode,
        )
        node_id = node.id if mode == "full" else f"{node.id}.eyes_only"
        entry = brain_entry(
            briefing_id=self.bid,
            node_id=node_id,
            tool="derive.ledger_input",
            data=data,
            at=self.r.clock.now(),
            mode=self.req.mode,
        )
        self.store.put(entry)
        self.bctx.ledger_inputs[mode] = data["args"]
        return AttemptResult(True, entry.call_run_id)

    # --- the run -----------------------------------------------------------------------------
    def _static_entries(self) -> None:
        packs = self.r.i18n.packs
        self.store.put(
            brain_entry(
                briefing_id=self.bid,
                node_id="static.disclaimer",
                tool="static.disclaimer",
                data={"text": {k: p.disclaimer for k, p in packs.items()}, "version": "1"},
                at=self.started_at,
                mode=self.req.mode,
            )
        )
        self.store.put(
            brain_entry(
                briefing_id=self.bid,
                node_id="run_meta.start",
                tool="run_meta",
                data={
                    "mode_requested": self.req.mode,
                    "scenario": self.scenario.id,
                    "label": {"en": self.scenario.label.en, "ur": self.scenario.label.ur},
                    "served_by": {o: c.served_by for o, c in self.r.registry.clients.items()},
                    "health": {o: h.status for o, h in self.health_at_start.items()},
                },
                at=self.started_at,
                mode=self.req.mode,
            )
        )

    def _effective_mode(self) -> tuple[str, str | None]:
        if self.req.mode != "live":
            return "demo", None
        live = [e for e in self.store.entries() if e.organ in ("eyes", "oracle") and e.ok]
        if (
            live
            and all(e.mode == "live" for e in live)
            and self.store.ok_node("eyes.segment")
            and self.store.ok_node("oracle.forecast")
        ):
            return "live", None
        return "demo", "live mode was requested, but Eyes and Oracle did not all answer live"

    async def execute(self) -> RunResult:
        plan = default_plan(self.scenario, plan_id=det_uuid(self.bid, "plan"))
        self._static_entries()
        self.plan_event(plan)
        limits = Limits(organ_phase_deadline_s=self.r.settings.organ_deadline_s)
        ex = Executor(
            clock=self.r.clock,
            attempt=self.attempt,
            record_failure=self.record_failure,
            on_call=self.on_call,
            on_result=self.on_result,
            limits=limits,
        )
        outcomes = await ex.run(organ_phase_nodes(plan))
        final = self.store.ok_node("ledger.optimize")
        if final is not None:
            self.store.alias("ledger.final", final.call_run_id)
        plan, records = await self.conflict_stage(plan, ex, outcomes)
        conflicts: list[Conflict] = [r.to_contract(self.req.lang) for r in records]
        mode, fallback = self._effective_mode()
        if fallback:
            self.emit("notice", "run", {"code": "MODE_FALLBACK", "message": fallback})
        meta = brain_entry(
            briefing_id=self.bid,
            node_id="run_meta",
            tool="run_meta",
            data={
                "mode_requested": self.req.mode,
                "mode_effective": mode,
                "fallback_reason": fallback,
                "label": {"en": self.scenario.label.en, "ur": self.scenario.label.ur},
                "served_by": {o: c.served_by for o, c in self.r.registry.clients.items()},
                "call_inputs": self.call_inputs,
            },
            at=self.r.clock.now(),
            mode=mode,
        )
        self.store.put(meta)
        ctx = RenderCtx(
            store=self.store,
            scenario=self.scenario,
            i18n=self.r.i18n,
            lang=self.req.lang,
            digits=self.r.settings.ur_digits,
            node_status={k: o.status for k, o in outcomes.items()},
        )
        organ_entries = [e for e in self.store.entries() if e.served_by != "brain"]
        drafts = render_all(ctx, organ_entries)
        apply_disputed(
            drafts, records, self.r.i18n.pack(self.req.lang).disputed_suffix, self.req.lang
        )
        critic = CriticVerdict(passed=True, removed_claims=[], notes=[])
        briefing = self._assemble(drafts, outcomes, conflicts, critic, mode)
        self.emit("briefing", "briefing", briefing.model_dump(mode="json"))
        return RunResult(
            briefing=briefing,
            store=self.store,
            plan=plan,
            outcomes=outcomes,
            drafts=drafts,
            trace={"calls": self.calls},
        )

    # --- conflicts and the single reconciliation (design 9.4) ---------------------------------
    def _conflict_event(self, rec: ConflictRecord) -> None:
        self.emit("conflict", "conflicts", rec.to_contract(self.req.lang).model_dump(mode="json"))

    async def conflict_stage(
        self, plan: Plan, ex: Executor, outcomes: dict[str, NodeOutcome]
    ) -> tuple[Plan, list[ConflictRecord]]:
        rs = self.r.rules
        fctx = FactCtx(store=self.store, scenario=self.scenario)
        pass1 = evaluate(rs, fctx)
        records = records_from(pass1, rs.params, self.r.i18n, self.scenario)
        budget = 1  # per run, not per rule (BRN-P20)
        for rec in records:
            rule = rec.outcome.rule
            if rule.reconcile is None or budget == 0:
                continue
            budget -= 1
            rec.status = "reconciling"
            self._conflict_event(rec)
            plan = with_rerun(plan)
            self.plan_event(plan, added=["ledger.rerun"])
            self.derive(plan.node("derive.ledger_input"), mode="eyes_only")
            node = plan.node("ledger.rerun")
            rerun = await ex.run([node], prior=outcomes, deadline_s=node.timeout_s * 3)
            outcomes.update(rerun)
            self.reruns += 1
            new = self.store.ok_node("ledger.rerun")
            if new is None:
                rec.resolution = "escalated"
                continue
            self.store.alias("ledger.final", new.call_run_id)
            again = evaluate_rule(rule, fctx, rs.params)  # pass 2 cannot schedule nodes
            rec.evidence += [new.ref("/data/status"), new.ref("/data/allocation")]
            rec.resolution = "escalated" if again.fired else "reconciled"
        for rec in records:
            rec.status = "final"
            self._conflict_event(rec)
        trace = [*fctx.trace, *(f"{o.rule.id} skipped: {o.skipped}" for o in pass1 if o.skipped)]
        self.store.put(
            brain_entry(
                briefing_id=self.bid,
                node_id="conflicts",
                tool="conflicts",
                data=entry_data(records, pass1, trace),
                at=self.r.clock.now(),
                mode=self.req.mode,
            )
        )
        self.rule_trace = trace
        return plan, records

    def _assemble(
        self,
        drafts: list[ClaimDraft],
        outcomes: Mapping[str, NodeOutcome],
        conflicts: list[Conflict],
        critic: CriticVerdict,
        mode: str,
    ) -> Briefing:
        lib_nodes = [n for n in outcomes if n.startswith("library.")]
        node_ok = {k: o.ok for k, o in outcomes.items()}
        node_ok["ledger.final"] = self.store.ok_node("ledger.final") is not None
        led = self.store.ok_node("ledger.final")
        refusals = sum(
            1
            for n in lib_nodes
            if (e := self.store.ok_node(n)) is not None and e.data().get("status") == "refused"
        )
        kept: dict[str, int] = {s: sum(1 for d in drafts if d.section == s) for s in SECTION_ORDER}
        removed_by: dict[str, int] = {}
        for cid in critic.removed_claims:
            sec = cid.split(".", 1)[0]
            sec = "caveats" if sec == "caveat" else sec
            removed_by[sec] = removed_by.get(sec, 0) + 1
        s_in = StatusInputs(
            node_ok=node_ok,
            library_nodes=lib_nodes,
            refusals=refusals,
            exceedance_rendered=any(d.id == "forecast.exceedance" for d in drafts),
            ledger_status=led.data().get("status") if led else None,
            ledger_gap=led.data().get("optimality_gap") if led else None,
            removed_by_section=removed_by,
            kept_by_section=kept,
        )
        statuses: dict[str, tuple[str, list[str]]] = {
            s: section_status(s, s_in) for s in SECTION_ORDER
        }
        seg = self.store.ok_node("eyes.segment")
        unvalidated = bool(
            seg and seg.data().get("validation", {}).get("validated_for_region") is False
        )
        for d in drafts:
            d.labels = labels_for(d, self.store, unvalidated)
        oc = organ_confidences(self.store, lib_nodes, refusals, self.r.conf_params)
        conf = confidence(
            oc,
            [c.resolution for c in conflicts],
            critic.passed,
            len(critic.removed_claims),
            self.r.conf_params,
        )
        pack = self.r.i18n.pack(self.req.lang)
        organs = [
            BriefingOrgan(
                organ=o,
                status=self.health_at_start[o].status,
                served_by=c.served_by,
            )
            for o, c in self.r.registry.clients.items()
            if o in ORGAN_TOOLS and o != "voice"
        ]
        return assemble(
            briefing_id=self.bid,
            scenario=self.scenario.id,
            lang=self.req.lang,
            mode=mode,
            drafts=drafts,
            statuses=statuses,
            titles=pack.section_titles,
            conflicts=conflicts,
            critic=critic,
            confidence=conf,
            generated_at=self.r.clock.now(),
            organs=organs,
            disclaimer=pack.disclaimer,
        )


async def run_once(
    request: BriefingRequest,
    briefing_id: str,
    registry: OrganRegistry,
    **kw: Any,
) -> RunResult:
    return await BriefingRunner(registry, **kw).run(request, briefing_id)


__all__ = ["BriefingRunner", "RunError", "RunResult", "run_once"]
