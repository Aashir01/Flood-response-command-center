"""One briefing run: plan -> organ phase -> conflicts (and one reconciliation) -> synth ->
phrase/translate -> critic -> assemble (design 7.1). Emits ``TaskEvent``s through ``emit``."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stitch_brain.config import (
    I18n,
    ScenarioCfg,
    load_confidence,
    load_i18n,
    load_rules,
    load_scenarios,
)
from stitch_brain.core.briefing import StatusInputs, assemble, labels_for, section_status
from stitch_brain.core.claims import SECTION_ORDER, ClaimDraft
from stitch_brain.core.confidence import ConfidenceParams, confidence, organ_confidences
from stitch_brain.core.conflicts import ConflictRecord, apply_disputed, entry_data, records_from
from stitch_brain.core.critic import run_critic
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
from stitch_brain.core.templates.caveats import render_post_critic
from stitch_brain.core.templates.common import RenderCtx
from stitch_brain.runtime.clock import Clock, RealClock
from stitch_brain.runtime.executor import AttemptResult, ErrorDict, Executor, Limits, NodeOutcome
from stitch_brain.runtime.llm_steps import LlmSteps
from stitch_brain.runtime.organs import CallContext, CallOutcome, OrganClient
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.runtime.validate import ContractViolation, validate_input
from stitch_brain.settings import ORGANS, Settings
from stitch_common import CONTRACT_VERSION
from stitch_common.brain import Briefing, BriefingOrgan, Conflict, CriticVerdict, TaskEvent
from stitch_common.brain_api import BriefingRequest
from stitch_common.logging import get_logger
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.provenance import inputs_hash

Emit = Callable[[TaskEvent], None]
LOG = get_logger("stitch_brain.run")
SUMMARY_MAX = 10
#: organs that fetch upstream data in live mode (Library and Ledger are local, design 16)
LIVE_ORGANS = ("eyes", "oracle")
#: live failures that trigger the single demo-mode call
FALLBACK_CODES = ("UPSTREAM_UNAVAILABLE", "TIMEOUT")
MODE_TOOLS = ("segment_flood", "compare_with_permanent_water", "forecast_river")


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


def _organ_rank(organ: str) -> int:
    return ORGANS.index(organ) if organ in ORGANS else len(ORGANS)


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
        self.conf_params: ConfidenceParams = conf_params or load_confidence()
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
        self,
        request: BriefingRequest,
        briefing_id: str,
        emit: Emit | None = None,
        *,
        store: EvidenceStore | None = None,
    ) -> RunResult:
        """``store``: an empty store the run fills; the API passes one so that evidence is
        readable through ``GET /evidence/{run_id}`` while the run is still going."""
        emit = emit or (lambda e: None)
        run = _Run(self, request, briefing_id, emit, store)
        return await run.execute()


class _Run:
    """State of one run. Kept separate so the runner can serve several runs concurrently."""

    def __init__(
        self,
        r: BriefingRunner,
        req: BriefingRequest,
        bid: str,
        emit: Emit,
        store: EvidenceStore | None = None,
    ) -> None:
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
        self.store = store if store is not None else EvidenceStore(bid)
        self.bctx = BuildContext(scenario=scenario, store=self.store, lang=req.lang, mode=req.mode)
        self.failures = 0
        self.call_inputs: dict[str, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self.started_at = r.clock.now()
        self.health_at_start = r.registry.health()
        self.reruns = 0
        self.fallbacks: list[str] = []  # nodes re-called in demo mode after a live failure
        self.plans: list[dict[str, Any]] = []
        self.plan_fallback: str | None = None
        self.rule_trace: list[str] = []
        self.t0 = r.clock.monotonic()
        self.steps = LlmSteps(
            r.llm,
            r.i18n,
            phrase=r.settings.phrase,
            strict=r.settings.fake_strict,
        )

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
        self.plans.append(plan.model_dump(mode="json"))
        self.emit("plan", "plan", payload)

    def served_by_map(self) -> dict[str, str]:
        from stitch_brain.runtime.registry import DisabledOrgan

        return {
            o: "disabled" if isinstance(c, DisabledOrgan) else c.served_by
            for o, c in self.r.registry.clients.items()
        }

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
        LOG.info(
            "organ_result",
            extra={
                "briefing_id": self.bid,
                "task_id": node.id,
                "organ": node.organ,
                "attempt": payload["attempt"],
                "duration_ms": payload["duration_ms"],
                "ok": outcome.ok,
                "served_by": c.served_by,
            },
        )
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
        res = await self._call_once(node, attempt, args, c)
        if self._live_fallback_due(node, res):
            # Live upstream failed: one demo-mode call of the same tool (design 16, BRN-R9).
            # The failed live entry stays in the store; the demo entry is stored after it, so
            # it is the node's latest entry and no ``caveat.missing`` claim is rendered.
            err = res.error or ErrorDict("UPSTREAM_UNAVAILABLE", "", True)
            self.fallbacks.append(node.id)
            self.emit(
                "notice",
                node.id,
                {
                    "code": "MODE_FALLBACK",
                    "message": f"{node.organ} live call failed ({err.code}); using demo data",
                    "details": {"organ": node.organ, "tool": node.tool, "error_code": err.code},
                },
                organ=node.organ,
                tool=node.tool,
            )
            demo_args = {**args, "mode": "demo"}
            self.call_inputs[node.id] = demo_args
            res = await self._call_once(node, attempt, demo_args, c, fallback=True)
        return res

    def _live_fallback_due(self, node: Node, res: AttemptResult) -> bool:
        return (
            self.req.mode == "live"
            and not res.ok
            and node.kind == "organ"
            and node.organ in LIVE_ORGANS
            and node.id not in self.fallbacks
            and res.error is not None
            and res.error.code in FALLBACK_CODES
        )

    async def _call_once(
        self,
        node: Node,
        attempt: int,
        args: dict[str, Any],
        c: OrganClient,
        *,
        fallback: bool = False,
    ) -> AttemptResult:
        assert node.tool is not None
        ctx_node = f"{node.id}.demo_fallback" if fallback else node.id
        ctx = CallContext(self.bid, ctx_node, attempt, self.scenario.fixture_set)
        started, t0 = self.r.clock.now(), self.r.clock.monotonic()
        if node.kind != "resource":
            try:
                validate_input(node.organ or "", node.tool, args)
            except ContractViolation as exc:
                err = ErrorDict("INVALID_INPUT", f"brain built invalid arguments: {exc}", False)
                return AttemptResult(False, self.record_failure(node, attempt, err), err)
        base = {"node_id": node.id, "attempt": attempt, "organ": node.organ, "args": args}
        if fallback:
            base["fallback"] = "demo"
        try:
            if node.kind == "resource":
                out = await c.read_resource(args["uri"], timeout_s=node.timeout_s, ctx=ctx)
            else:
                out = await c.call_tool(node.tool, args, timeout_s=node.timeout_s, ctx=ctx)
        except asyncio.CancelledError:
            self.calls.append({**base, "cancelled": True})  # trace: replay hangs the same way
            raise
        except Exception as exc:
            self.calls.append({**base, "exception": type(exc).__name__})
            raise
        if out.result is None:
            assert out.transport_error is not None
            te = out.transport_error
            self.calls.append({**base, "transport_error": {"code": te.code, "message": te.message}})
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
        self.calls.append({**base, "entry": entry.model_dump(mode="json")})
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
        # Only the calls that take a ``mode`` input count; ``explain_forecast`` is keyed by a
        # prior run id and has no mode of its own (contract 1).
        live = [
            e
            for e in self.store.entries()
            if e.organ in LIVE_ORGANS and e.tool in MODE_TOOLS and e.ok
        ]
        if (
            live
            and all(e.mode == "live" for e in live)
            and self.store.ok_node("eyes.segment")
            and self.store.ok_node("oracle.forecast")
        ):
            return "live", None
        if self.fallbacks:
            return (
                "demo",
                f"live upstream failed for {', '.join(sorted(self.fallbacks))}; demo data used",
            )
        return "demo", "live mode was requested, but Eyes and Oracle did not all answer live"

    async def execute(self) -> RunResult:
        plan = default_plan(self.scenario, plan_id=det_uuid(self.bid, "plan"))
        plan, plan_fallback = await self.steps.vary_plan(
            plan, enabled=self.r.settings.planner == "llm"
        )
        self.plan_fallback = plan_fallback
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
                "fallback_nodes": sorted(self.fallbacks),
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
        organ_entries = [e for e in self.store.canonical_entries() if e.served_by != "brain"]
        drafts = render_all(ctx, organ_entries)
        apply_disputed(
            drafts, records, self.r.i18n.pack(self.req.lang).disputed_suffix, self.req.lang
        )
        cids = [r.cid for r in records]
        verdicts = await self.llm_stage(drafts, cids)
        drafts, critic = self.critic_stage(drafts, cids, ctx, verdicts)
        briefing = self._assemble(drafts, outcomes, conflicts, critic, mode)
        self.emit("briefing", "briefing", briefing.model_dump(mode="json"))
        return RunResult(
            briefing=briefing,
            store=self.store,
            plan=plan,
            outcomes=outcomes,
            drafts=drafts,
            trace={
                "calls": self.calls,
                "llm_calls": self.steps.trace.calls,
                "plans": self.plans,
                "served_by": self.served_by_map(),
                "started_at": self.started_at.isoformat(),
                "rule_trace": self.rule_trace,
                "plan_fallback": self.plan_fallback,
            },
        )

    # --- LLM steps and critic (design 10, 12, 13) ----------------------------------------------
    async def llm_stage(self, drafts: list[ClaimDraft], cids: list[str]) -> dict[str, bool]:
        """Phrase and translate within the run deadline; skipped when the deadline has passed
        (template text is used). Returns judge verdicts for rewritten claims."""
        lang = self.req.lang
        elapsed = self.r.clock.monotonic() - self.t0
        if elapsed < self.r.settings.run_deadline_s:
            await self.steps.phrase(drafts, self.store, lang, cids)
            await self.steps.translate(drafts, self.store, lang, cids)
            return await self.steps.judge_many(drafts, self.store)
        for d in drafts:
            if self.steps.needs_translation(d, lang):
                d.verbatim_foreign = True
        return {}

    def critic_stage(
        self,
        drafts: list[ClaimDraft],
        cids: list[str],
        ctx: RenderCtx,
        verdicts: Mapping[str, bool],
    ) -> tuple[list[ClaimDraft], CriticVerdict]:
        pre: dict[str, str] = {}
        for issue in ctx.issues:
            cid = issue.split(":", 1)[0].strip()
            pre.setdefault(cid, issue)
        res = run_critic(
            drafts,
            self.store,
            self.r.i18n,
            self.req.lang,
            self.scenario,
            conflict_ids=cids,
            judge=lambda d, _ev: verdicts.get(d.id, False),
            pre_removed=pre,
        )
        for p in res.passes:
            self.emit("critic", "critic", p.payload())
        last = res.passes[-1]
        unresolved = 0 if res.verdict.passed else max(1, len(last.issues))
        self.store.put(
            brain_entry(
                briefing_id=self.bid,
                node_id="critic",
                tool="critic",
                data={
                    "passed": res.verdict.passed,
                    "removed_claims": list(res.verdict.removed_claims),
                    "notes": list(res.verdict.notes),
                    "unresolved": unresolved,
                    "reverted": list(res.reverted),
                    "passes": [p.payload() for p in res.passes],
                },
                at=self.r.clock.now(),
                mode=self.req.mode,
            )
        )
        out = res.drafts + render_post_critic(ctx, res.drafts)
        return out, res.verdict

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
            for o, c in sorted(self.r.registry.clients.items(), key=lambda kv: _organ_rank(kv[0]))
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
