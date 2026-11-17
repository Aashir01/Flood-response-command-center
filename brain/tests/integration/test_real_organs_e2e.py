"""End to end: the Brain drives the real Eyes, Oracle, Library and Ledger over stdio (task 29).

Each organ is a subprocess speaking MCP over pipes in demo mode (committed data). The test
process keeps ``no_network``; the organ processes get ``HF_HUB_OFFLINE=1`` and
``TRANSFORMERS_OFFLINE=1`` so a missing model cache fails instead of downloading. Voice is not
part of a briefing and is disabled. An organ that is not installed or does not start skips
the test (it is marked ``integration``)."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from typing import Any

import pytest

from stitch_brain.config import OrganEndpoint, OrgansCfg, load_scenarios
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.runtime.runner import BriefingRunner
from stitch_brain.settings import Settings
from stitch_common.brain import Briefing
from stitch_common.brain_api import BriefingRequest

ORGANS = ("eyes", "oracle", "library", "ledger")
OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "STITCH_LLM_PROVIDER": "fake"}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        any(importlib.util.find_spec(f"stitch_{o}") is None for o in ORGANS),
        reason="an organ package is not installed",
    ),
]


def _cfg() -> OrgansCfg:
    return OrgansCfg(
        organs={
            o: OrganEndpoint(
                transport="stdio",
                command=[sys.executable, "-m", f"stitch_{o}.server", "--stdio"],
                env=OFFLINE,
                connect_timeout_s=180.0,
            )
            for o in ORGANS
        }
    )


async def _run(reg: OrganRegistry, settings: Settings, scenario: str, lang: str) -> Any:
    sc = load_scenarios()[scenario]
    req = BriefingRequest(region=sc.region, scenario=scenario, lang=lang, mode="demo")  # type: ignore[arg-type]
    runner = BriefingRunner(reg, settings=settings, llm=None)
    events: list[Any] = []
    res = await runner.run(req, str(uuid.uuid4()), events.append)
    res.events = events
    return res


async def test_brain_with_all_real_organs_over_stdio() -> None:
    settings = Settings(disabled_organs=("voice",), organ_deadline_s=240.0, run_deadline_s=300.0)
    reg = OrganRegistry.build(settings, _cfg())
    await reg.start()
    try:
        for o in ORGANS:
            client: Any = reg.clients[o]
            if not await client.wait_connected(180):
                pytest.skip(f"{o} did not start: {client.health().last_error}")
            assert client.health().compat == "compatible", (o, client.health().reason)
        res = await _run(reg, settings, "demo-sindh-2022", "en")
        b: Briefing = res.briefing
        Briefing.model_validate(b.model_dump(mode="json"))
        assert b.mode == "demo"
        served = {o.organ: o.served_by for o in b.organs or []}
        assert served == {o: "real" for o in ORGANS}
        status = {s.id: s.status for s in b.sections}
        assert status["extent"] == "ok", status
        assert status["forecast"] == "ok", status
        assert status["allocation"] in ("ok", "partial"), status
        assert status["guidance"] in ("ok", "partial"), status  # a refusal makes it partial
        assert b.critic.passed, b.critic.notes
        claims = [c for s in b.sections for c in s.claims]
        for c in claims:  # BRN-P1 against real organ output
            assert c.evidence, c.id
            for ref in c.evidence:
                assert res.store.resolves(ref), (c.id, ref)
        organ_refs = {r.organ for c in claims for r in c.evidence}
        assert set(ORGANS) <= organ_refs
        oracle_claims = [c for c in claims if any(r.organ == "oracle" for r in c.evidence)]
        assert oracle_claims and all("modeled" in (c.labels or []) for c in oracle_claims)
        results = [e for e in res.events if e.event == "organ_result"]
        assert results and all(e.payload["served_by"] == "real" for e in results)
        assert res.events[0].event == "plan" and res.events[-1].event == "briefing"
        assert b.confidence > 0

        ur = await _run(reg, settings, "demo-sindh-2022", "ur")
        assert ur.briefing.lang == "ur" and ur.briefing.critic.passed, ur.briefing.critic.notes
    finally:
        await reg.close()
