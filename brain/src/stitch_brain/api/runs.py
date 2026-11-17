"""Briefing runs behind the API: start, follow, cancel, persist (design 14, 15).

Each run is an asyncio task that feeds an ``EventLog``. Every appended event is written to the
``RunStore`` at once, so a finished (or interrupted) run can be replayed from DuckDB after the
in-memory copy is gone. Evidence of recent runs stays in memory and is also persisted when the
run finishes."""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from stitch_brain.api.errors import ApiException
from stitch_brain.config import ScenarioCfg
from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore
from stitch_brain.runtime.runner import BriefingRunner, RunError
from stitch_brain.runtime.store import EventLog, RunRecord, RunStore, trace_from_result
from stitch_common.brain import TaskEvent
from stitch_common.brain_api import BriefingRequest
from stitch_common.logging import get_logger

LOG = get_logger("stitch_brain.api")
KEEP_IN_MEMORY = 50
RUN_GRACE_S = 30.0  # on top of the run deadline: the hard stop of a run task


@dataclass
class ActiveRun:
    briefing_id: str
    request: BriefingRequest
    created_at: datetime
    log: EventLog
    store: EvidenceStore
    status: str = "running"
    finished_at: datetime | None = None
    briefing: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class RunManager:
    def __init__(
        self,
        runner: BriefingRunner,
        db: RunStore,
        *,
        max_runs: int = 4,
        run_deadline_s: float = 60.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.runner = runner
        self.db = db
        self.max_runs = max_runs
        self.run_deadline_s = run_deadline_s
        self.now = now
        self.runs: OrderedDict[str, ActiveRun] = OrderedDict()
        self.asks: OrderedDict[str, EvidenceStore] = OrderedDict()

    # --- lifecycle ---------------------------------------------------------------------------
    def running(self) -> int:
        return sum(1 for r in self.runs.values() if r.status == "running")

    def validate(self, req: BriefingRequest) -> ScenarioCfg:
        sc = self.runner.scenarios.get(req.scenario)
        if sc is None:
            raise ApiException(
                "INVALID_INPUT",
                f"unknown scenario {req.scenario!r}",
                details={"scenarios": sorted(self.runner.scenarios)},
            )
        if sc.region != req.region:
            raise ApiException(
                "INVALID_INPUT",
                f"scenario {req.scenario!r} is for region {sc.region!r}",
                details={"region": sc.region},
            )
        return sc

    def start(self, req: BriefingRequest) -> ActiveRun:
        self.validate(req)
        if self.running() >= self.max_runs:
            raise ApiException(
                "BUSY",
                f"{self.max_runs} briefings are already running",
                headers={"Retry-After": "5"},
            )
        bid = str(uuid.uuid4())
        run = ActiveRun(bid, req, self.now(), EventLog(), EvidenceStore(bid))
        self._db(
            self.db.create_run,
            RunRecord(
                briefing_id=bid,
                status="running",
                request=req.model_dump(mode="json"),
                created_at=run.created_at,
            ),
        )
        run.log.on_append(lambda seq, ev: self._db(self.db.append_event, bid, seq, ev))
        self.runs[bid] = run
        run.task = asyncio.create_task(self._drive(run), name=f"briefing-{bid}")
        self._trim()
        return run

    def _db(self, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
        """A DuckDB failure never breaks a run; ``/healthz`` reports ``db_ok``."""
        try:
            return fn(*args, **kw)
        except Exception as exc:
            LOG.warning("run_store_error", extra={"error": type(exc).__name__})
            return None

    def _trim(self) -> None:
        while len(self.runs) > KEEP_IN_MEMORY:
            oldest = next(
                (k for k, r in self.runs.items() if r.status != "running"),
                None,
            )
            if oldest is None:
                break
            del self.runs[oldest]

    async def _drive(self, run: ActiveRun) -> None:
        bid = run.briefing_id
        sc = self.validate(run.request)
        result: Any = None

        def emit(ev: TaskEvent) -> None:
            run.log.append(ev)

        try:
            async with asyncio.timeout(self.run_deadline_s + RUN_GRACE_S):
                result = await self.runner.run(run.request, bid, emit, store=run.store)
            assert result.briefing is not None
            run.briefing = result.briefing.model_dump(mode="json")
            run.status = "done"
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.error = {"code": "CANCELLED", "message": "the briefing was cancelled"}
        except TimeoutError:
            run.status = "failed"
            run.error = {"code": "INTERNAL", "message": "the run deadline was exceeded"}
        except RunError as exc:
            run.status = "failed"
            code = exc.code if exc.code in ("INVALID_INPUT", "NOT_FOUND") else "INTERNAL"
            run.error = {"code": code, "message": exc.message}
        except Exception as exc:
            run.status = "failed"
            run.error = {"code": "INTERNAL", "message": "the briefing failed"}
            LOG.error("run_failed", extra={"briefing_id": bid, "error": type(exc).__name__})
        run.finished_at = self.now()
        if run.error is not None and not run.log.closed:
            run.log.append(
                TaskEvent(
                    event="error",
                    ts=run.finished_at,
                    task_id="run",
                    payload={
                        **run.error,
                        "fatal": True,
                        "retryable": run.status == "failed",
                    },
                )
            )
        run.log.close()
        trace = None
        if result is not None:
            result.events = [e for _, e in run.log.after(0)]
            trace = self._db(lambda: trace_from_result(result, run.request, bid, sc).to_json())
        self._db(
            self.db.finish_run,
            bid,
            run.status,
            finished_at=run.finished_at,
            briefing=run.briefing,
            error=run.error,
            trace=trace,
            evidence=[e.model_dump(mode="json") for e in run.store.entries()],
        )
        self._db(self.db.prune, self.now())
        LOG.info(
            "run_finished", extra={"briefing_id": bid, "task_id": "run", "ok": run.error is None}
        )

    def cancel(self, bid: str) -> str:
        run = self.runs.get(bid)
        if run is not None:
            if run.task is not None and not run.task.done():
                run.task.cancel()
                return "cancelling"
            return run.status
        rec = self._db(self.db.get_run, bid)
        if rec is None:
            raise ApiException("NOT_FOUND", "unknown briefing id", details={"reason": "unknown id"})
        return str(rec.status)

    async def close(self) -> None:
        tasks = [r.task for r in self.runs.values() if r.task is not None and not r.task.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- reads -------------------------------------------------------------------------------
    def state(self, bid: str) -> dict[str, Any]:
        run = self.runs.get(bid)
        if run is not None:
            return {
                "briefing_id": bid,
                "status": run.status,
                "request": run.request.model_dump(mode="json"),
                "created_at": run.created_at,
                "finished_at": run.finished_at,
                "briefing": run.briefing,
                "error": run.error,
            }
        rec = self._db(self.db.get_run, bid)
        if rec is None:
            raise ApiException("NOT_FOUND", "unknown briefing id", details={"reason": "unknown id"})
        return {
            "briefing_id": bid,
            "status": rec.status,
            "request": rec.request,
            "created_at": rec.created_at,
            "finished_at": rec.finished_at,
            "briefing": rec.briefing,
            "error": rec.error,
        }

    def event_log(self, bid: str) -> EventLog:
        run = self.runs.get(bid)
        if run is not None:
            return run.log
        rec = self._db(self.db.get_run, bid)
        if rec is None:
            raise ApiException("NOT_FOUND", "unknown briefing id", details={"reason": "unknown id"})
        return EventLog(self._db(self.db.events, bid) or [], closed=True)

    def remember_ask(self, ask_id: str, store: EvidenceStore) -> None:
        self.asks[ask_id] = store
        while len(self.asks) > 200:
            self.asks.popitem(last=False)

    def evidence(self, run_id: str) -> EvidenceEntry | None:
        for store in [*(r.store for r in reversed(self.runs.values())), *self.asks.values()]:
            e = store.get(run_id)
            if e is not None:
                return e
        raw = self._db(self.db.evidence_entry, run_id)
        return EvidenceEntry.model_validate(raw) if raw else None


__all__ = ["ActiveRun", "RunManager"]
