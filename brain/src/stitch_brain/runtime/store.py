"""Run store, event log, traces and replay (design 15; BRN-R10.1, R12.1, BRN-P4, BRN-P11).

* ``EventLog``: the append-only, per-run list of ``TaskEvent``s with contiguous integer ids
  from 1. ``subscribe(after)`` yields every event with ``seq > after`` and then follows live
  appends, with no gaps or duplicates: in asyncio, registering and reading the backlog happen
  without an ``await`` in between, so no append can slip between them.
* ``RunStore``: DuckDB tables ``runs``, ``events``, ``evidence``, ``llm_calls`` (file from
  ``STITCH_BRAIN_DB`` or in-memory). One writer lock. Retention: the newest 50 runs and at
  most 48 h. At startup, runs still marked ``running`` become ``failed`` (``RESTART``).
* ``Trace``: the minimum to replay a run: request, scenario config hash, plans, organ
  outcomes in order, LLM calls, served_by per organ and events. ``replay`` runs the normal
  pipeline against ``TraceOrgan`` clients, so the briefing is equal after ``normalize_ids``.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import threading
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from stitch_brain.core.evidence import sha256_json
from stitch_brain.runtime.organs import (
    CallContext,
    CallOutcome,
    OrganHealth,
    TransportError,
    resource_tool,
)
from stitch_common.brain import TaskEvent

RETAIN_RUNS = 50
RETAIN_HOURS = 48
TERMINAL = ("done", "failed", "cancelled")


# --- event log ----------------------------------------------------------------------------------
class EventLog:
    """Append-only events of one run. ``close()`` marks the end of the stream."""

    def __init__(self, events: Iterable[TaskEvent] = (), *, closed: bool = False) -> None:
        self._events: list[TaskEvent] = list(events)
        self._closed = closed
        self._waiters: set[asyncio.Event] = set()
        self._listeners: list[Any] = []

    def __len__(self) -> int:
        return len(self._events)

    @property
    def closed(self) -> bool:
        return self._closed

    def on_append(self, fn: Any) -> None:
        """``fn(seq, event)`` is called synchronously for every append (the store writer)."""
        self._listeners.append(fn)

    def append(self, event: TaskEvent) -> int:
        if self._closed:
            raise RuntimeError("event log is closed")
        self._events.append(event)
        seq = len(self._events)
        for fn in self._listeners:
            fn(seq, event)
        self._wake()
        return seq

    def close(self) -> None:
        self._closed = True
        self._wake()

    def _wake(self) -> None:
        for w in list(self._waiters):
            w.set()

    def after(self, seq: int) -> list[tuple[int, TaskEvent]]:
        start = max(0, seq)
        return [(i + 1, e) for i, e in enumerate(self._events[start:], start=start)]

    async def subscribe(self, after: int = 0) -> AsyncIterator[tuple[int, TaskEvent]]:
        """Replay ``seq > after`` then follow live appends until the log closes."""
        cursor = max(0, after)
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        try:
            while True:
                waiter.clear()
                while cursor < len(self._events):
                    cursor += 1
                    yield cursor, self._events[cursor - 1]
                if self._closed:
                    return
                await waiter.wait()
        finally:
            self._waiters.discard(waiter)


# --- run store ----------------------------------------------------------------------------------
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS runs (
        briefing_id VARCHAR PRIMARY KEY, created_at VARCHAR, finished_at VARCHAR,
        status VARCHAR, request_json VARCHAR, plan_json VARCHAR, briefing_json VARCHAR,
        error_json VARCHAR, trace_json VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS events (
        briefing_id VARCHAR, seq INTEGER, ts VARCHAR, type VARCHAR, json VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS evidence (
        call_run_id VARCHAR, briefing_id VARCHAR, node_id VARCHAR, organ VARCHAR, tool VARCHAR,
        served_by VARCHAR, result_json VARCHAR, original_sha256 VARCHAR, entry_json VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS llm_calls (
        briefing_id VARCHAR, seq INTEGER, purpose VARCHAR, key VARCHAR, outcome VARCHAR,
        provider VARCHAR)""",
)


@dataclass
class RunRecord:
    briefing_id: str
    status: str
    request: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None = None
    briefing: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None


def _dump(x: Any) -> str | None:
    return None if x is None else json.dumps(x, ensure_ascii=False, sort_keys=True)


def _load(s: str | None) -> Any:
    return None if s is None else json.loads(s)


class RunStore:
    """DuckDB-backed store. ``path=None`` keeps everything in memory (read-only containers)."""

    def __init__(self, path: str | None = None) -> None:
        import duckdb

        self.path = path
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = duckdb.connect(path or ":memory:")
        self._lock = threading.Lock()
        with self._lock:
            for stmt in _SCHEMA:
                self._db.execute(stmt)

    @classmethod
    def open(cls, path: str | None) -> RunStore:
        """Open ``path``; on any error fall back to memory (the API reports ``db_ok``)."""
        try:
            return cls(path)
        except Exception:
            store = cls(None)
            store.fallback = True
            return store

    fallback: bool = False

    def ok(self) -> bool:
        try:
            with self._lock:
                self._db.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _exec(self, sql: str, params: list[Any] | None = None) -> Any:
        with self._lock:
            return self._db.execute(sql, params or []).fetchall()

    # writes
    def create_run(self, rec: RunRecord) -> None:
        self._exec(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                rec.briefing_id,
                _ts(rec.created_at),
                _ts(rec.finished_at),
                rec.status,
                _dump(rec.request),
                _dump(rec.plan),
                _dump(rec.briefing),
                _dump(rec.error),
                _dump(rec.trace),
            ],
        )

    def append_event(self, briefing_id: str, seq: int, event: TaskEvent) -> None:
        self._exec(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
            [
                briefing_id,
                seq,
                _ts(event.ts),
                event.event,
                event.model_dump_json(exclude_none=True),
            ],
        )

    def finish_run(
        self,
        briefing_id: str,
        status: str,
        *,
        finished_at: datetime,
        briefing: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
        evidence: Iterable[dict[str, Any]] = (),
    ) -> None:
        self._exec(
            "UPDATE runs SET status = ?, finished_at = ?, briefing_json = ?, error_json = ?, "
            "plan_json = coalesce(?, plan_json), trace_json = coalesce(?, trace_json) "
            "WHERE briefing_id = ?",
            [
                status,
                _ts(finished_at),
                _dump(briefing),
                _dump(error),
                _dump(plan),
                _dump(trace),
                briefing_id,
            ],
        )
        for e in evidence:
            self._exec(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    e["call_run_id"],
                    briefing_id,
                    e["node_id"],
                    e["organ"],
                    e["tool"],
                    e["served_by"],
                    _dump(e["result"]),
                    e.get("original_sha256", ""),
                    _dump(e),
                ],
            )
        if trace:
            for i, c in enumerate(trace.get("llm_calls") or [], start=1):
                self._exec(
                    "INSERT INTO llm_calls VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        briefing_id,
                        i,
                        c.get("purpose"),
                        c.get("key"),
                        c.get("outcome"),
                        c.get("provider"),
                    ],
                )

    # reads
    def get_run(self, briefing_id: str) -> RunRecord | None:
        rows = self._exec(
            "SELECT briefing_id, status, request_json, created_at, finished_at, briefing_json, "
            "error_json, plan_json, trace_json FROM runs WHERE briefing_id = ?",
            [briefing_id],
        )
        if not rows:
            return None
        r = rows[0]
        return RunRecord(
            briefing_id=r[0],
            status=r[1],
            request=_load(r[2]),
            created_at=_aware(r[3]),
            finished_at=_aware(r[4]) if r[4] else None,
            briefing=_load(r[5]),
            error=_load(r[6]),
            plan=_load(r[7]),
            trace=_load(r[8]),
        )

    def events(self, briefing_id: str) -> list[TaskEvent]:
        rows = self._exec(
            "SELECT json FROM events WHERE briefing_id = ? ORDER BY seq", [briefing_id]
        )
        return [TaskEvent.model_validate_json(r[0]) for r in rows]

    def evidence_entry(self, call_run_id: str) -> dict[str, Any] | None:
        rows = self._exec(
            "SELECT entry_json FROM evidence WHERE call_run_id = ? LIMIT 1", [call_run_id]
        )
        return _load(rows[0][0]) if rows else None

    def run_ids(self) -> list[str]:
        return [r[0] for r in self._exec("SELECT briefing_id FROM runs ORDER BY created_at")]

    # maintenance
    def mark_interrupted(self, now: datetime) -> list[str]:
        """Runs left ``running`` by a previous process become ``failed`` (``RESTART``)."""
        ids = [r[0] for r in self._exec("SELECT briefing_id FROM runs WHERE status = 'running'")]
        err = {"code": "INTERNAL", "message": "RESTART: the Brain restarted during this run"}
        for bid in ids:
            seq = len(self.events(bid)) + 1
            ev = TaskEvent(
                event="error",
                ts=now,
                task_id="run",
                payload={**err, "fatal": True, "retryable": True},
            )
            self.append_event(bid, seq, ev)
            self.finish_run(bid, "failed", finished_at=now, error=err)
        return ids

    def prune(self, now: datetime, keep: int = RETAIN_RUNS, hours: int = RETAIN_HOURS) -> list[str]:
        """Keep the newest ``keep`` runs that are younger than ``hours``; never prune a run
        that is still running."""
        rows = self._exec("SELECT briefing_id, created_at, status FROM runs ORDER BY created_at")
        cutoff = now - timedelta(hours=hours)
        finished = [(r[0], _aware(r[1])) for r in rows if r[2] in TERMINAL]
        drop = {bid for bid, at in finished if at < cutoff}
        alive = [bid for bid, _ in finished if bid not in drop]
        running = len(rows) - len(finished)
        excess = len(alive) + running - keep
        if excess > 0:
            drop.update(alive[:excess])
        for bid in drop:
            for table in ("runs", "events", "evidence", "llm_calls"):
                self._exec(f"DELETE FROM {table} WHERE briefing_id = ?", [bid])
        return sorted(drop)


def _ts(dt: datetime | None) -> str | None:
    """UTC ISO text: sorts like time, and needs no timezone module in DuckDB."""
    return None if dt is None else dt.astimezone(UTC).isoformat()


def _aware(dt: Any) -> datetime:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(dt))


# --- traces and replay --------------------------------------------------------------------------
def scenario_hash(scenario: Any) -> str:
    dump = scenario.model_dump(mode="json", by_alias=True)
    return hashlib.sha256(json.dumps(dump, sort_keys=True).encode()).hexdigest()


@dataclass
class Trace:
    request: dict[str, Any]
    briefing_id: str
    scenario_config_hash: str
    plans: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    llm_calls: list[dict[str, Any]]
    served_by: dict[str, str]
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "briefing_id": self.briefing_id,
            "scenario_config_hash": self.scenario_config_hash,
            "plans": self.plans,
            "calls": self.calls,
            "llm_calls": self.llm_calls,
            "served_by": self.served_by,
            "events": self.events,
            "started_at": self.started_at,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Trace:
        return cls(
            request=d["request"],
            briefing_id=d["briefing_id"],
            scenario_config_hash=d["scenario_config_hash"],
            plans=list(d.get("plans") or []),
            calls=list(d.get("calls") or []),
            llm_calls=list(d.get("llm_calls") or []),
            served_by=dict(d.get("served_by") or {}),
            events=list(d.get("events") or []),
            started_at=d.get("started_at"),
        )

    def export(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(self.to_json(), fh, ensure_ascii=False, sort_keys=True)
        return path

    @classmethod
    def load(cls, path: Path) -> Trace:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return cls.from_json(json.load(fh))


class TraceOrgan:
    """Replays the stored outcome of each ``(node_id, attempt)`` of a trace (design 15). A call
    the trace does not hold is a transport error, never an invented result."""

    def __init__(self, organ: str, calls: list[dict[str, Any]], served_by: str) -> None:
        self.organ = organ
        self.served_by: Any = served_by if served_by in ("real", "recorded") else "recorded"
        self._by_key = {
            (str(c["node_id"]), int(c["attempt"])): c
            for c in calls
            if str(c.get("organ") or c.get("entry", {}).get("organ")) == organ
        }

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[str]:
        return []

    async def call_tool(
        self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: CallContext
    ) -> CallOutcome:
        c = self._by_key.get((ctx.node_id, ctx.attempt))
        if c is None:
            return CallOutcome(transport_error=TransportError("UNAVAILABLE", "not in trace"))
        if c.get("cancelled"):  # the original attempt hung until its timeout or the deadline
            await asyncio.Event().wait()
        if c.get("exception"):
            raise RuntimeError(f"replayed organ client failure: {c['exception']}")
        te = c.get("transport_error")
        if te is not None:
            return CallOutcome(transport_error=TransportError(te["code"], te["message"]))
        entry = c["entry"]
        return CallOutcome(
            result=entry["result"],
            original_sha256=entry.get("original_sha256") or sha256_json(entry["result"]),
            source=entry.get("source"),
        )

    async def read_resource(self, uri: str, *, timeout_s: float, ctx: CallContext) -> CallOutcome:
        return await self.call_tool(resource_tool(uri), {"uri": uri}, timeout_s=timeout_s, ctx=ctx)

    def health(self) -> OrganHealth:
        return OrganHealth(
            organ=self.organ,
            status="ready",
            compat="compatible",
            served_by=self.served_by,
            connected=True,
            reason="trace replay",
        )


def trace_registry(trace: Trace, settings: Any) -> Any:
    from stitch_brain.runtime.registry import DisabledOrgan, OrganRegistry

    clients: dict[str, Any] = {}
    for organ, served in trace.served_by.items():
        if served == "disabled":
            clients[organ] = DisabledOrgan(organ)
        else:
            clients[organ] = TraceOrgan(organ, trace.calls, served)
    return OrganRegistry(clients, settings)


async def replay(trace: Trace, *, settings: Any = None, clock: Any = None) -> Any:
    """Run the pipeline again from a trace: organ results from the trace, LLM replies from the
    trace's recordings (none are stored, so a replay uses the template fallbacks unless the
    caller passes a FakeLLM), the same briefing id."""
    from stitch_brain.runtime.runner import BriefingRunner
    from stitch_brain.settings import Settings
    from stitch_common.brain_api import BriefingRequest

    settings = settings or Settings()
    reg = trace_registry(trace, settings)
    runner = BriefingRunner(reg, settings=settings, clock=clock)
    req = BriefingRequest.model_validate(trace.request)
    events: list[TaskEvent] = []
    result = await runner.run(req, trace.briefing_id, events.append)
    result.events = events
    return result


def trace_from_result(result: Any, request: Any, briefing_id: str, scenario: Any) -> Trace:
    served = dict(result.trace.get("served_by") or {})
    return Trace(
        request=request.model_dump(mode="json"),
        briefing_id=briefing_id,
        scenario_config_hash=scenario_hash(scenario),
        plans=list(result.trace.get("plans") or []),
        calls=list(result.trace.get("calls") or []),
        llm_calls=list(result.trace.get("llm_calls") or []),
        served_by=served,
        events=[e.model_dump(mode="json") for e in result.events],
        started_at=result.trace.get("started_at"),
    )


__all__ = [
    "EventLog",
    "RunRecord",
    "RunStore",
    "Trace",
    "TraceOrgan",
    "replay",
    "scenario_hash",
    "trace_from_result",
    "trace_registry",
]
