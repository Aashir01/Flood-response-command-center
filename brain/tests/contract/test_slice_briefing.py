"""Ledger-only vertical slice (task 10; BRN-R7, R12.1, BRN-P1 on the slice)."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from brain_testkit import all_claims, run_briefing

from stitch_brain.cli import main as cli_main
from stitch_brain.runtime.recorded import DirectoryFixtureSource
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.settings import Settings
from stitch_common.brain import Briefing, TaskEvent
from stitch_common.brain_api import validate_event_payload


def _ledger_only_registry(tmp_path: Path) -> OrganRegistry:
    src_root = Path(__file__).resolve().parents[3] / "data" / "demo" / "recorded"
    dst = tmp_path / "recorded"
    for f in (src_root / "ledger").rglob("*.json"):
        out = dst / f.relative_to(src_root)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(f.read_bytes())
    settings = Settings(recorded_organs=("all",))
    return OrganRegistry.build(settings, None, fixtures=DirectoryFixtureSource(dst))


async def test_ledger_only_briefing(tmp_path: Path) -> None:
    res = await run_briefing(registry=_ledger_only_registry(tmp_path))
    b: Briefing = res.briefing
    status = {s.id: s.status for s in b.sections}
    assert status["extent"] == "unavailable" and status["forecast"] == "unavailable"
    assert status["guidance"] == "unavailable"
    assert status["allocation"] in ("ok", "partial") and status["caveats"] == "ok"
    ids = {c.id for c in all_claims(b)}
    assert {"caveat.missing.eyes_segment", "caveat.missing.oracle_forecast"} <= ids
    # BRN-P1 on the slice: every claim has refs and each resolves
    for c in all_claims(b):
        assert c.evidence and all(res.store.resolves(r) for r in c.evidence), c.id
    Briefing.model_validate(b.model_dump(mode="json"))
    for e in res.events:
        validate_event_payload(TaskEvent.model_validate(e.model_dump(mode="json")))
    assert res.events[0].event == "plan" and res.events[-1].event == "briefing"


def test_cli_prints_a_valid_briefing_offline(tmp_path: Path) -> None:
    out = tmp_path / "b.json"
    assert (
        cli_main(
            ["run", "--scenario", "demo-sindh-2022", "--organs", "recorded", "--out", str(out)]
        )
        == 0
    )
    b = Briefing.model_validate(json.loads(out.read_text(encoding="utf-8")))
    assert b.mode == "demo"
    with pytest.raises(RuntimeError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)
