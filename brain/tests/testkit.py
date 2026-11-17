"""Shared Hypothesis strategies and test doubles for the Brain tests (``brain_testkit``)."""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

json_scalars = st.none() | st.booleans() | st.integers(-(10**9), 10**9) | st.text(max_size=8)
json_keys = st.text(
    alphabet=st.sampled_from(list("ab/~0 1é漢")) | st.characters(codec="utf-8"),
    max_size=6,
)


def recorded_registry(**settings_kw: Any) -> Any:
    from stitch_brain.runtime.registry import OrganRegistry
    from stitch_brain.settings import Settings

    settings = Settings(recorded_organs=("all",), **settings_kw)
    return OrganRegistry.build(settings, None)


async def run_briefing(
    scenario: str = "demo-sindh-2022",
    lang: str = "en",
    *,
    registry: Any = None,
    clock: Any = None,
    briefing_id: str = "00000000-0000-4000-8000-000000000001",
    mode: str = "demo",
    **runner_kw: Any,
) -> Any:
    from stitch_brain.config import load_scenarios
    from stitch_brain.runtime.runner import BriefingRunner
    from stitch_common.brain_api import BriefingRequest

    reg = registry or recorded_registry()
    sc = load_scenarios()[scenario]
    req = BriefingRequest(region=sc.region, scenario=scenario, lang=lang, mode=mode)  # type: ignore[arg-type]
    events: list[Any] = []
    runner = BriefingRunner(reg, clock=clock, **runner_kw)
    result = await runner.run(req, briefing_id, events.append)
    result.events = events
    return result


def fixture_result(organ: str, tool: str, name: str) -> dict[str, Any]:
    import copy
    import json

    from stitch_brain.paths import recorded_dir

    path = recorded_dir() / organ / tool.replace("resource:", "resource_") / f"{name}.json"
    out: dict[str, Any] = copy.deepcopy(json.loads(path.read_text(encoding="utf-8"))["result"])
    return out


DEFAULT_WORLD = {
    "eyes.segment": ("eyes", "segment_flood", "demo-sindh-2022"),
    "eyes.compare": ("eyes", "compare_with_permanent_water", "demo-sindh-2022"),
    "oracle.forecast": ("oracle", "forecast_river", "indus-kotri-2022-08-25"),
    "oracle.explain": ("oracle", "explain_forecast", "indus-kotri-2022-08-25"),
    "library.water": ("library", "answer_with_citations", "water-en"),
    "library.food": ("library", "answer_with_citations", "food-en"),
    "library.shelter": ("library", "answer_with_citations", "shelter-en"),
    "ledger.districts": ("ledger", "resource:districts", "demo-sindh-2022"),
    "ledger.optimize": ("ledger", "optimize_allocation", "demo-sindh-2022-full"),
    "ledger.sensitivity": ("ledger", "sensitivity_report", "demo-sindh-2022-full"),
}


def world_store(
    results: dict[str, dict[str, Any] | None] | None = None,
    *,
    served_by: str = "recorded",
    scenario: str = "demo-sindh-2022",
) -> Any:
    """An evidence store with one entry per node (``results`` overrides or removes nodes),
    plus the Brain-origin entries the runner writes. For renderer and checker tests."""
    from datetime import UTC, datetime

    from stitch_brain.config import load_i18n, load_scenarios
    from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore, brain_entry, sha256_json
    from stitch_brain.core.severity import build_ledger_input

    world: dict[str, dict[str, Any] | None] = {
        k: fixture_result(*v) for k, v in DEFAULT_WORLD.items()
    }
    world.update(results or {})
    store = EvidenceStore("b")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for node, res in world.items():
        if res is None:
            continue
        organ, tool, _ = DEFAULT_WORLD.get(node, ("ledger", "optimize_allocation", ""))
        res = dict(res)
        res["provenance"] = {**res["provenance"], "run_id": f"rid-{node}"}
        if served_by == "recorded" and res.get("ok"):
            res["warnings"] = [*res.get("warnings", []), "RECORDED_FIXTURE: served from test"]
        store.put(
            EvidenceEntry(
                call_run_id=f"rid-{node}",
                briefing_id="b",
                node_id=node,
                organ=organ,
                tool=tool,
                served_by=served_by,  # type: ignore[arg-type]
                started_at=now,
                ended_at=now,
                result=res,
                original_sha256=sha256_json(res),
            )
        )
    sc = load_scenarios()[scenario]
    i18n = load_i18n()
    data = build_ledger_input(
        sc,
        eyes_compare=store.ok_node("eyes.compare"),
        oracle_forecast=store.ok_node("oracle.forecast"),
        districts=store.ok_node("ledger.districts"),
        packs=i18n.packs,
    )
    store.put(
        brain_entry(
            briefing_id="b",
            node_id="derive.ledger_input",
            tool="derive.ledger_input",
            data=data,
            at=now,
        )
    )
    store.put(
        brain_entry(
            briefing_id="b",
            node_id="static.disclaimer",
            tool="static.disclaimer",
            data={"text": {k: p.disclaimer for k, p in i18n.packs.items()}},
            at=now,
        )
    )
    inputs = {f"library.{q.id}": {"query": q.query.en} for q in sc.guidance_questions}
    store.put(
        brain_entry(
            briefing_id="b",
            node_id="run_meta",
            tool="run_meta",
            data={
                "mode_requested": "demo",
                "mode_effective": "demo",
                "label": {"en": sc.label.en, "ur": sc.label.ur},
                "call_inputs": inputs,
            },
            at=now,
        )
    )
    if store.ok_node("ledger.optimize") is not None:
        store.alias("ledger.final", "rid-ledger.optimize")
    return store


def render_world(store: Any, lang: str = "en", scenario: str = "demo-sindh-2022") -> list[Any]:
    from stitch_brain.config import load_i18n, load_scenarios
    from stitch_brain.core.synth import render_all
    from stitch_brain.core.templates.common import RenderCtx

    ctx = RenderCtx(store=store, scenario=load_scenarios()[scenario], i18n=load_i18n(), lang=lang)
    organ_entries = [e for e in store.entries() if e.served_by != "brain"]
    drafts: list[Any] = render_all(ctx, organ_entries)
    return drafts


def all_claims(briefing: Any) -> list[Any]:
    return [c for s in briefing.sections for c in s.claims]


def json_docs(max_leaves: int = 20) -> st.SearchStrategy[Any]:
    return st.recursive(
        json_scalars | st.floats(allow_nan=False, allow_infinity=False),
        lambda children: (
            st.lists(children, max_size=4) | st.dictionaries(json_keys, children, max_size=4)
        ),
        max_leaves=max_leaves,
    )


class FaultyOrgan:
    """Wraps a client and fails every call in one of the BRN-P3 failure modes: ``error``
    (an ok:false ToolResult), ``timeout`` (transport timeout), ``exception`` (raises), ``hang``
    (sleeps on the clock until the deadline) and ``invalid`` (schema-invalid result)."""

    def __init__(self, inner: Any, mode: str, clock: Any = None) -> None:
        self.inner = inner
        self.organ = inner.organ
        self.served_by = inner.served_by
        self.mode = mode
        self.clock = clock

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[str]:
        out: list[str] = await self.inner.list_tools()
        return out

    def health(self) -> Any:
        return self.inner.health()

    async def _fail(self, tool: str, args: dict[str, Any], ctx: Any) -> Any:
        from stitch_brain.runtime.organs import CallOutcome, TransportError
        from stitch_brain.runtime.recorded import not_found

        if self.mode == "error":
            res = not_found(self.organ, tool, args, ctx)
            res["error"] = {"code": "UPSTREAM_UNAVAILABLE", "message": "down", "retryable": False}
            return CallOutcome(result=res)
        if self.mode == "timeout":
            return CallOutcome(transport_error=TransportError("TIMEOUT", "timed out"))
        if self.mode == "exception":
            raise RuntimeError("organ client crashed")
        if self.mode == "hang":
            await self.clock.sleep(10_000)
            raise AssertionError("hang outlived the deadline")
        if self.mode == "invalid":
            return CallOutcome(transport_error=TransportError("PROTOCOL", "contract: bad shape"))
        raise ValueError(self.mode)

    async def call_tool(self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: Any) -> Any:
        return await self._fail(tool, args, ctx)

    async def read_resource(self, uri: str, *, timeout_s: float, ctx: Any) -> Any:
        return await self._fail("resource:districts", {"uri": uri}, ctx)


def faulty_registry(down: Any, mode: str, clock: Any = None) -> Any:
    reg = recorded_registry()
    for organ in down:
        reg.clients[organ] = FaultyOrgan(reg.clients[organ], mode, clock)
    return reg