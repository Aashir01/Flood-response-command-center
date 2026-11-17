"""Live mode and fallback (BRN-R9, design 16, task 27). Live paths use recorded fixtures only:
a wrapper makes the recorded Eyes and Oracle answer "live" or fail upstream."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

from brain_testkit import all_claims, recorded_registry, run_briefing


class LiveShaped:
    """Wraps a recorded client. ``fail_live``: a live call returns ``UPSTREAM_UNAVAILABLE``;
    otherwise a live call returns the fixture with ``provenance.mode = live``."""

    def __init__(self, inner: Any, *, fail_live: bool) -> None:
        self.inner = inner
        self.organ = inner.organ
        self.served_by = inner.served_by
        self.fail_live = fail_live
        self.modes: list[str] = []

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[str]:
        out: list[str] = await self.inner.list_tools()
        return out

    def health(self) -> Any:
        return self.inner.health()

    async def read_resource(self, uri: str, *, timeout_s: float, ctx: Any) -> Any:
        return await self.inner.read_resource(uri, timeout_s=timeout_s, ctx=ctx)

    async def call_tool(
        self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: Any
    ) -> Any:
        from stitch_brain.runtime.organs import CallOutcome
        from stitch_brain.runtime.recorded import not_found

        mode = str(args.get("mode", "demo"))
        self.modes.append(mode)
        if mode == "live" and self.fail_live:
            res = not_found(self.organ, tool, args, ctx)
            res["error"] = {
                "code": "UPSTREAM_UNAVAILABLE",
                "message": "Open-Meteo unreachable",
                "retryable": True,
            }
            return CallOutcome(result=res)
        out = await self.inner.call_tool(tool, args, timeout_s=timeout_s, ctx=ctx)
        if mode == "live" and out.result is not None:
            res = copy.deepcopy(out.result)
            res["provenance"]["mode"] = "live"
            return CallOutcome(result=res, original_sha256=out.original_sha256, source=out.source)
        return out


def _registry(*, fail_live: bool, organs: tuple[str, ...] = ("eyes", "oracle")) -> Any:
    reg = recorded_registry()
    for o in organs:
        reg.clients[o] = LiveShaped(reg.clients[o], fail_live=fail_live)
    return reg


def _notices(result: Any) -> list[Any]:
    return [e for e in result.events if e.event == "notice"]


def _claim(result: Any, cid: str) -> Any:
    return next((c for c in all_claims(result.briefing) if c.id == cid), None)


def test_demo_fixtures_under_a_live_request_give_demo_mode_and_the_banner_event() -> None:
    result = asyncio.run(run_briefing(mode="live"))
    b = result.briefing
    assert b.mode == "demo"
    codes = [e.payload["code"] for e in _notices(result)]
    assert "MODE_FALLBACK" in codes
    mode_claim = _claim(result, "caveat.mode")
    assert mode_claim is not None
    assert "live" in mode_claim.text.lower()


def test_all_live_results_give_live_mode_without_a_fallback() -> None:
    result = asyncio.run(run_briefing(mode="live", registry=_registry(fail_live=False)))
    assert result.briefing.mode == "live"
    assert not [e for e in _notices(result) if e.payload["code"] == "MODE_FALLBACK"]
    meta = result.store.ok_node("run_meta")
    assert meta.data()["mode_effective"] == "live"


def test_a_mix_of_live_and_demo_results_is_demo() -> None:
    # Eyes answers live, Oracle answers from demo fixtures: any mix is demo (design 16 item 4).
    result = asyncio.run(
        run_briefing(mode="live", registry=_registry(fail_live=False, organs=("eyes",)))
    )
    assert result.briefing.mode == "demo"
    assert any(e.payload["code"] == "MODE_FALLBACK" for e in _notices(result))


def test_upstream_failure_falls_back_to_demo_once_per_node() -> None:
    reg = _registry(fail_live=True)
    result = asyncio.run(run_briefing(mode="live", registry=reg))
    b = result.briefing
    assert b.mode == "demo"
    node_notices = [e for e in _notices(result) if e.task_id != "run"]
    assert sorted(e.task_id for e in node_notices) == [
        "eyes.compare",
        "eyes.segment",
        "oracle.forecast",
    ]
    assert all(e.payload["code"] == "MODE_FALLBACK" for e in node_notices)
    # one live call then one demo call per node; the executor does not retry the live call
    assert reg.clients["eyes"].modes.count("live") == 2
    assert reg.clients["eyes"].modes.count("demo") == 2
    # the sections are filled from demo data and nothing is reported missing
    status = {s.id: s.status for s in b.sections}
    assert status["extent"] == "ok"
    assert status["forecast"] == "ok"
    assert not [c for c in all_claims(b) if c.id.startswith("caveat.missing")]
    # the failed live entry is kept as evidence
    failed = [e for e in result.store.entries() if e.organ == "eyes" and not e.ok]
    assert len(failed) == 2
    meta = result.store.ok_node("run_meta")
    assert meta.data()["fallback_nodes"] == ["eyes.compare", "eyes.segment", "oracle.forecast"]
    assert b.critic.passed


def test_demo_request_never_falls_back_or_calls_live() -> None:
    reg = _registry(fail_live=True)
    result = asyncio.run(run_briefing(mode="demo", registry=reg))
    assert result.briefing.mode == "demo"
    assert not _notices(result)
    assert set(reg.clients["eyes"].modes) == {"demo"}
