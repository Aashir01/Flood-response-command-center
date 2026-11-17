"""Run store, event log, traces and replay (task 22; BRN-R10.1, R12.1, BRN-P4, BRN-P11)."""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from brain_testkit import faulty_registry, recorded_registry, run_briefing
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from stitch_brain.config import load_scenarios
from stitch_brain.core.briefing import normalize_ids
from stitch_brain.runtime.clock import VirtualClock
from stitch_brain.runtime.store import (
    EventLog,
    RunRecord,
    RunStore,
    Trace,
    replay,
    trace_from_result,
)
from stitch_common.brain import TaskEvent
from stitch_common.brain_api import BriefingRequest

BID = "00000000-0000-4000-8000-0000000000b4"
SC = load_scenarios()["demo-sindh-2022"]
REQ = BriefingRequest(region=SC.region, scenario=SC.id)


def _norm(res: Any) -> Any:
    return normalize_ids(res.briefing.model_dump(mode="json"))


def _kinds(events: list[Any]) -> Counter[tuple[str, str]]:
    return Counter((e.event, e.task_id) for e in events)


class DelayedOrgan:
    """Delays every call on the virtual clock by a drawn amount (completion order varies)."""

    def __init__(self, inner: Any, clock: VirtualClock, rng: random.Random) -> None:
        self.inner, self.clock, self.rng = inner, clock, rng
        self.organ, self.served_by = inner.organ, inner.served_by

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[str]:
        out: list[str] = await self.inner.list_tools()
        return out

    def health(self) -> Any:
        return self.inner.health()

    async def call_tool(self, tool: str, args: dict[str, Any], **kw: Any) -> Any:
        await self.clock.sleep(self.rng.uniform(0, 10))
        return await self.inner.call_tool(tool, args, **kw)

    async def read_resource(self, uri: str, **kw: Any) -> Any:
        await self.clock.sleep(self.rng.uniform(0, 10))
        return await self.inner.read_resource(uri, **kw)


async def _delayed_run(seed: int, lang: str = "en") -> Any:
    clock = VirtualClock()
    reg = recorded_registry()
    rng = random.Random(seed)
    for o in list(reg.clients):
        reg.clients[o] = DelayedOrgan(reg.clients[o], clock, rng)
    async with clock.autojump():
        return await run_briefing(lang=lang, registry=reg, clock=clock, briefing_id=BID)


async def test_brn_p4_same_request_twice_gives_the_same_briefing() -> None:
    a = await run_briefing(briefing_id=BID)
    b = await run_briefing(briefing_id=BID)
    assert _norm(a) == _norm(b)
    assert [e.event for e in a.events] == [e.event for e in b.events]


@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(0, 2**16), st.sampled_from(["en", "ur"]))
async def test_brn_p4_completion_order_does_not_change_the_briefing(seed: int, lang: str) -> None:
    base = await run_briefing(lang=lang, briefing_id=BID)
    res = await _delayed_run(seed, lang)
    assert _norm(res) == _norm(base)


async def test_brn_p4_replayed_trace_equals_the_original(tmp_path: Path) -> None:
    res = await run_briefing(briefing_id=BID)
    trace = trace_from_result(res, REQ, BID, SC)
    loaded = Trace.load(trace.export(tmp_path / f"{BID}.json.gz"))
    again = await replay(loaded)
    assert _norm(again) == _norm(res)
    assert _kinds(again.events) == _kinds(res.events)
    assert again.events[0].event == "plan" and again.events[-1].event == "briefing"
    served = {e.payload["served_by"] for e in again.events if e.event == "organ_result"}
    assert served == {"recorded"}  # the replay keeps the original labels


@pytest.mark.parametrize("mode", ["error", "timeout", "exception", "hang"])
async def test_brn_p4_replay_reproduces_failures(mode: str) -> None:
    clock = VirtualClock()
    async with clock.autojump():
        res = await run_briefing(
            registry=faulty_registry(("oracle",), mode, clock), clock=clock, briefing_id=BID
        )
    trace = trace_from_result(res, REQ, BID, SC)
    clock2 = VirtualClock()
    async with clock2.autojump():
        again = await replay(Trace.from_json(trace.to_json()), clock=clock2)
    assert _norm(again) == _norm(res)


# --- RunStore ----------------------------------------------------------------------------------
NOW = datetime(2026, 1, 3, tzinfo=UTC)


def _rec(bid: str, at: datetime, status: str = "done") -> RunRecord:
    return RunRecord(briefing_id=bid, status=status, request=REQ.model_dump(), created_at=at)


def _ev(i: int, kind: str = "notice") -> TaskEvent:
    return TaskEvent(event=kind, ts=NOW, task_id="run", payload={"code": "X", "message": str(i)})  # type: ignore[arg-type]


async def test_run_store_round_trip(tmp_path: Path) -> None:
    res = await run_briefing(briefing_id=BID)
    store = RunStore(str(tmp_path / "brain.duckdb"))
    store.create_run(_rec(BID, NOW, "running"))
    for i, e in enumerate(res.events, start=1):
        store.append_event(BID, i, e)
    entries = [e.model_dump(mode="json") for e in res.store.entries()]
    store.finish_run(
        BID,
        "done",
        finished_at=NOW,
        briefing=res.briefing.model_dump(mode="json"),
        trace=trace_from_result(res, REQ, BID, SC).to_json(),
        evidence=entries,
    )
    store.close()
    again = RunStore(str(tmp_path / "brain.duckdb"))
    rec = again.get_run(BID)
    assert rec is not None and rec.status == "done"
    assert rec.briefing == res.briefing.model_dump(mode="json")
    assert [e.event for e in again.events(BID)] == [e.event for e in res.events]
    first = entries[0]
    assert again.evidence_entry(first["call_run_id"]) == first
    replayed = await replay(Trace.from_json(rec.trace or {}))
    assert _norm(replayed) == _norm(res)


def test_retention_keeps_fifty_runs_and_forty_eight_hours() -> None:
    store = RunStore(None)
    for i in range(55):
        store.create_run(_rec(f"r{i:02d}", NOW - timedelta(minutes=55 - i)))
    store.create_run(_rec("old", NOW - timedelta(hours=49)))
    store.create_run(_rec("live", NOW - timedelta(hours=50), status="running"))
    dropped = store.prune(NOW)
    ids = set(store.run_ids())
    assert "old" in dropped and "live" in ids
    assert len(ids) == 50 and {f"r{i:02d}" for i in range(6, 55)} <= ids


def test_restart_marks_running_runs_failed_with_a_fatal_event() -> None:
    store = RunStore(None)
    store.create_run(_rec("a", NOW, "running"))
    store.append_event("a", 1, _ev(1))
    assert store.mark_interrupted(NOW) == ["a"]
    rec = store.get_run("a")
    assert rec is not None and rec.status == "failed" and rec.error is not None
    assert "RESTART" in rec.error["message"]
    last = store.events("a")[-1]
    assert last.event == "error" and last.payload["fatal"] is True


def test_unwritable_db_path_falls_back_to_memory(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = RunStore.open(str(blocker / "sub" / "brain.duckdb"))
    assert store.fallback and store.ok()


# --- EventLog (BRN-P11) ------------------------------------------------------------------------
@settings(max_examples=60, deadline=None)
@given(
    st.integers(1, 40),
    st.lists(st.integers(0, 45), min_size=1, max_size=6),
    st.randoms(use_true_random=False),
)
async def test_brn_p11_resume_has_no_gaps_or_duplicates(
    n: int, disconnects: list[int], rnd: random.Random
) -> None:
    log = EventLog()

    async def producer() -> None:
        for i in range(n):
            log.append(_ev(i))
            for _ in range(rnd.randint(0, 2)):
                await asyncio.sleep(0)
        log.close()

    received: list[int] = []

    async def consumer() -> None:
        last = 0
        cuts = sorted(disconnects)
        while True:
            cut = cuts.pop(0) if cuts else None
            got_any = False
            async for seq, _ev in log.subscribe(last):
                received.append(seq)
                last = seq
                got_any = True
                if cut is not None and seq >= cut:
                    break  # the client disconnects, then resumes with Last-Event-ID = last
            else:
                return
            if not got_any and log.closed:
                return

    await asyncio.gather(producer(), consumer())
    assert received == list(range(1, n + 1))


async def test_last_event_id_beyond_the_end_waits_for_new_events() -> None:
    log = EventLog([_ev(0), _ev(1)])
    got: list[int] = []

    async def consume() -> None:
        async for seq, _e in log.subscribe(5):
            got.append(seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert got == []
    for i in range(5):
        log.append(_ev(i))
    log.close()
    await task
    assert got == [6, 7]


async def test_info_logs_carry_ids_and_no_claim_text(caplog: pytest.LogCaptureFixture) -> None:
    from stitch_common.logging import JsonFormatter

    with caplog.at_level("INFO", logger="stitch_brain"):
        await run_briefing(briefing_id=BID)
    lines = [JsonFormatter().format(r) for r in caplog.records if r.name.startswith("stitch")]
    assert lines and all('"briefing_id"' in ln and '"task_id"' in ln for ln in lines)
    text = "\n".join(lines)
    assert "Send " not in text and "New flood water" not in text and "system" not in text
