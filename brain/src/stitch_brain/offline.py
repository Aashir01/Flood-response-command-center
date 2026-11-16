"""Helpers for offline fixture capture: the exact Ledger arguments the Brain sends per variant,
computed from the recorded Eyes, Oracle and district fixtures of the scenario."""

from __future__ import annotations

import asyncio
from typing import Any

from stitch_brain.config import ScenarioCfg, load_i18n
from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore
from stitch_brain.core.graph import Node
from stitch_brain.core.plans import BUILDERS, BuildContext, default_plan, ledger_fallback_args
from stitch_brain.core.severity import build_ledger_input
from stitch_brain.paths import recorded_dir
from stitch_brain.runtime.organs import CallContext
from stitch_brain.runtime.recorded import DirectoryFixtureSource, RecordedOrgan
from stitch_brain.runtime.registry import recorded_tools


async def _entry(organ: RecordedOrgan, node: Node, bctx: BuildContext) -> EvidenceEntry | None:
    from datetime import UTC, datetime

    args = BUILDERS[node.builder](bctx, node)
    ctx = CallContext("offline", node.id, 1, bctx.scenario.fixture_set)
    if node.kind == "resource":
        out = await organ.read_resource(args["uri"], timeout_s=5, ctx=ctx)
    else:
        assert node.tool is not None
        out = await organ.call_tool(node.tool, args, timeout_s=5, ctx=ctx)
    if out.result is None or not out.result.get("ok"):
        return None
    now = datetime.now(UTC)
    e = EvidenceEntry(
        call_run_id=str(out.result["provenance"]["run_id"]),
        briefing_id="offline",
        node_id=node.id,
        organ=organ.organ,
        tool=node.tool or "",
        served_by="recorded",
        started_at=now,
        ended_at=now,
        result=out.result,
        original_sha256=out.original_sha256 or "",
    )
    bctx.store.put(e)
    return e


def ledger_variant_args(scenario: ScenarioCfg, variant: str) -> dict[str, Any] | None:
    """``defaults``: no district override. ``full`` and ``eyes_only``: the severity mapping
    (design 8) over the recorded Eyes, Oracle and district fixtures of the scenario."""
    if variant == "defaults":
        return ledger_fallback_args(scenario, "demo")
    if variant not in ("full", "eyes_only"):
        return None
    source = DirectoryFixtureSource(recorded_dir())
    store = EvidenceStore("offline")
    bctx = BuildContext(scenario=scenario, store=store)
    plan = default_plan(scenario)

    async def collect() -> None:
        for nid in ("eyes.compare", "oracle.forecast", "ledger.districts"):
            node = plan.node(nid)
            assert node.organ is not None
            organ = RecordedOrgan(node.organ, source, recorded_tools(node.organ))
            await _entry(organ, node, bctx)

    asyncio.run(collect())
    data = build_ledger_input(
        scenario,
        eyes_compare=store.ok_node("eyes.compare"),
        oracle_forecast=store.ok_node("oracle.forecast"),
        districts=store.ok_node("ledger.districts"),
        packs=load_i18n().packs,
        mode="full" if variant == "full" else "eyes_only",
    )
    if data["severity_mode"] == "defaults":
        return None
    args: dict[str, Any] = data["args"]
    return args
