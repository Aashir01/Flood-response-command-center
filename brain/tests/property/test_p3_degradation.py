"""Graceful degradation matrix (task 19, BRN-P3): every non-empty subset of the four briefing
organs times five failure modes, plus the all-down case. Runs in virtual time."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from brain_testkit import all_claims, faulty_registry, run_briefing

from stitch_brain.runtime.clock import VirtualClock

ORGANS = ("eyes", "oracle", "library", "ledger")
SECTION = {"eyes": "extent", "oracle": "forecast", "library": "guidance", "ledger": "allocation"}
MODES = ("error", "timeout", "exception", "hang", "invalid")
SUBSETS = [c for k in range(1, 5) for c in itertools.combinations(ORGANS, k)]
_BASE: dict[str, Any] = {}


async def _run(down: tuple[str, ...], mode: str) -> Any:
    clock = VirtualClock()
    reg = faulty_registry(down, mode, clock)
    async with clock.autojump():
        return await run_briefing(registry=reg, clock=clock)


async def _baseline() -> float:
    if "conf" not in _BASE:
        res = await _run((), "error")
        _BASE["conf"] = res.briefing.confidence
    return float(_BASE["conf"])


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("down", SUBSETS, ids=["+".join(s) for s in SUBSETS])
async def test_brn_p3_briefing_survives_failures(down: tuple[str, ...], mode: str) -> None:
    res = await _run(down, mode)
    b = res.briefing
    assert b is not None
    status = {s.id: s.status for s in b.sections}
    for organ in down:
        assert status[SECTION[organ]] in ("partial", "unavailable"), (organ, status)
    if "ledger" in down:
        assert status["allocation"] == "unavailable"
    claims = all_claims(b)
    for c in claims:  # BRN-P1 holds under failure
        assert c.evidence and all(res.store.resolves(r) for r in c.evidence), c.id
    missing = [c for c in claims if c.id.startswith("caveat.missing.")]
    for organ in down:
        cited = [r for c in missing for r in c.evidence if r.organ == organ]
        assert any(r.json_pointer.startswith("/error") for r in cited), organ
    assert b.critic.passed, b.critic.notes
    assert b.confidence <= await _baseline()
    assert status["caveats"] == "ok"


async def test_all_organs_down_still_returns_a_briefing() -> None:
    res = await _run(ORGANS, "timeout")
    status = {s.id: s.status for s in res.briefing.sections}
    assert status == {
        "extent": "unavailable",
        "forecast": "unavailable",
        "guidance": "unavailable",
        "allocation": "unavailable",
        "caveats": "ok",
    }
    ids = [c.id for c in all_claims(res.briefing)]
    assert "caveat.disclaimer" in ids and "caveat.mode" in ids
    assert res.briefing.confidence == 0.0
