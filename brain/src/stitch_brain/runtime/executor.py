"""Asyncio task-graph executor (design 7.3, BRN-R3, BRN-P10). No agent framework.

The executor knows nothing about organs or evidence. It schedules nodes, applies concurrency
limits, per-attempt timeouts, bounded retries with deterministic jitter, the organ-phase
deadline and cancellation, and calls back into the runner:

* ``attempt(node, attempt_no)`` performs one attempt and returns an ``AttemptResult``.
* ``record_failure(node, attempt_no, error)`` stores a synthesized failed entry when an attempt
  produced no result (timeout, exception, deadline) and returns its entry id.
* ``on_call`` / ``on_result`` emit ``organ_call`` (per attempt) and ``organ_result`` (once).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from stitch_brain.core.graph import Node
from stitch_brain.runtime.clock import Clock, wait_for

Status = Literal["ok", "failed", "skipped", "timed_out", "cancelled"]
TERMINAL: frozenset[str] = frozenset({"ok", "failed", "skipped", "timed_out", "cancelled"})
BACKOFF_S = (0.25, 0.5)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ErrorDict:
    code: str
    message: str
    retryable: bool

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class AttemptResult:
    ok: bool
    entry_id: str | None = None
    error: ErrorDict | None = None

    @property
    def retryable(self) -> bool:
        return self.error is not None and self.error.retryable


@dataclass
class NodeOutcome:
    node_id: str
    status: Status
    entry_id: str | None = None
    error: ErrorDict | None = None
    attempts: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int = 0
    reason: str | None = None  # DEP_FAILED, DEADLINE, CANCELLED

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class Limits:
    max_in_flight: int = 6
    per_organ: int = 2
    organ_phase_deadline_s: float = 45.0


AttemptFn = Callable[[Node, int], Awaitable[AttemptResult]]
FailureFn = Callable[[Node, int, ErrorDict], str | None]
CallHook = Callable[[Node, int, datetime], None]
ResultHook = Callable[[Node, NodeOutcome], None]


def jitter(node_id: str, attempt: int) -> float:
    """Deterministic jitter in [0, 0.1) from the node id and attempt (design 7.3)."""
    h = hashlib.sha256(f"{node_id}:{attempt}".encode()).digest()
    return (int.from_bytes(h[:4], "big") % 1000) / 10000.0


def backoff(node_id: str, attempt: int) -> float:
    base = BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)]
    return base * (1.0 + jitter(node_id, attempt))


@dataclass
class Executor:
    clock: Clock
    attempt: AttemptFn
    record_failure: FailureFn = lambda node, attempt, err: None
    on_call: CallHook = lambda node, attempt, at: None
    on_result: ResultHook = lambda node, outcome: None
    limits: Limits = field(default_factory=Limits)
    # observability for tests (BRN-P10)
    max_seen_in_flight: int = 0
    max_seen_per_organ: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._global = asyncio.Semaphore(self.limits.max_in_flight)
        self._organs: dict[str, asyncio.Semaphore] = {}
        self._in_flight = 0
        self._per_organ: dict[str, int] = {}
        self._current: dict[str, int] = {}

    def _organ_sem(self, organ: str) -> asyncio.Semaphore:
        if organ not in self._organs:
            self._organs[organ] = asyncio.Semaphore(self.limits.per_organ)
        return self._organs[organ]

    # --- readiness ---------------------------------------------------------------------------
    @staticmethod
    def _readiness(node: Node, outcomes: Mapping[str, NodeOutcome]) -> str:
        for d in node.deps:
            o = outcomes.get(d.id)
            if o is None:
                return "wait"
            if d.need == "hard" and not o.ok:
                return "skip"
        return "ready"

    # --- one node ----------------------------------------------------------------------------
    async def _run_node(self, node: Node) -> NodeOutcome:
        organ = node.organ or f"_{node.kind}"
        started = self.clock.now()
        t0 = self.clock.monotonic()
        max_attempts = min(node.max_attempts, MAX_ATTEMPTS)
        result = AttemptResult(ok=False, error=ErrorDict("INTERNAL", "no attempt", False))
        attempt_no = 0
        async with self._global, self._organ_sem(organ):
            self._in_flight += 1
            self._per_organ[organ] = self._per_organ.get(organ, 0) + 1
            self.max_seen_in_flight = max(self.max_seen_in_flight, self._in_flight)
            self.max_seen_per_organ[organ] = max(
                self.max_seen_per_organ.get(organ, 0), self._per_organ[organ]
            )
            try:
                for attempt_no in range(1, max_attempts + 1):
                    self._current[node.id] = attempt_no
                    self.on_call(node, attempt_no, self.clock.now())
                    result = await self._one_attempt(node, attempt_no)
                    if result.ok or not result.retryable or attempt_no == max_attempts:
                        break
                    await self.clock.sleep(backoff(node.id, attempt_no))
            finally:
                self._in_flight -= 1
                self._per_organ[organ] -= 1
        status: Status = "ok" if result.ok else "failed"
        if not result.ok and result.error is not None and result.error.code == "TIMEOUT":
            status = "timed_out"
        return NodeOutcome(
            node_id=node.id,
            status=status,
            entry_id=result.entry_id,
            error=result.error,
            attempts=attempt_no,
            started_at=started,
            ended_at=self.clock.now(),
            duration_ms=round((self.clock.monotonic() - t0) * 1000),
        )

    async def _one_attempt(self, node: Node, attempt_no: int) -> AttemptResult:
        try:
            return await wait_for(self.clock, self.attempt(node, attempt_no), node.timeout_s)
        except TimeoutError:
            err = ErrorDict("TIMEOUT", f"{node.id} timed out after {node.timeout_s:g} s", True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a node never raises into the group
            err = ErrorDict("INTERNAL", f"{node.id} raised {type(exc).__name__}", False)
        return AttemptResult(
            ok=False, entry_id=self.record_failure(node, attempt_no, err), error=err
        )

    # --- the graph ---------------------------------------------------------------------------
    async def run(
        self,
        nodes: Iterable[Node],
        prior: Mapping[str, NodeOutcome] | None = None,
        *,
        deadline_s: float | None = None,
    ) -> dict[str, NodeOutcome]:
        """Run ``nodes`` to terminal states. ``prior`` holds outcomes of earlier passes that
        dependencies may refer to (dynamic nodes). Returns the outcomes of ``nodes`` only."""
        known: dict[str, NodeOutcome] = dict(prior or {})
        mine: dict[str, NodeOutcome] = {}
        pending = {n.id: n for n in nodes}
        running: dict[asyncio.Task[NodeOutcome], Node] = {}
        budget = self.limits.organ_phase_deadline_s if deadline_s is None else deadline_s
        deadline_at = self.clock.monotonic() + budget

        def finish(node: Node, outcome: NodeOutcome) -> None:
            known[node.id] = outcome
            mine[node.id] = outcome
            self.on_result(node, outcome)

        try:
            while pending or running:
                progressed = True
                while progressed:
                    progressed = False
                    for nid in sorted(pending):
                        node = pending[nid]
                        r = self._readiness(node, known)
                        if r == "skip":
                            del pending[nid]
                            finish(node, NodeOutcome(nid, "skipped", reason="DEP_FAILED"))
                            progressed = True
                        elif r == "ready":
                            del pending[nid]
                            running[asyncio.create_task(self._run_node(node))] = node
                if not running:
                    for nid in sorted(pending):  # deps that can never finish
                        finish(pending.pop(nid), NodeOutcome(nid, "skipped", reason="DEP_FAILED"))
                    break
                remaining = deadline_at - self.clock.monotonic()
                timer: asyncio.Task[None] = asyncio.create_task(self.clock.sleep(max(remaining, 0)))
                waiters: set[asyncio.Future[Any]] = {*running, timer}
                done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t is timer:
                        continue
                    node = running.pop(t)  # type: ignore[call-overload]
                    finish(node, t.result())
                if timer in done and running:
                    await self._expire(running, finish)
                    for nid in sorted(pending):
                        finish(pending.pop(nid), NodeOutcome(nid, "skipped", reason="DEADLINE"))
                elif timer in done and pending and not running:
                    for nid in sorted(pending):
                        finish(pending.pop(nid), NodeOutcome(nid, "skipped", reason="DEADLINE"))
                else:
                    timer.cancel()
                    with suppress(asyncio.CancelledError):
                        await timer
        except asyncio.CancelledError:
            for t, node in list(running.items()):
                t.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await t
                finish(node, NodeOutcome(node.id, "cancelled", reason="CANCELLED"))
            for nid in sorted(pending):
                finish(pending.pop(nid), NodeOutcome(nid, "cancelled", reason="CANCELLED"))
            raise
        return mine

    async def _expire(
        self,
        running: dict[asyncio.Task[NodeOutcome], Node],
        finish: Callable[[Node, NodeOutcome], None],
    ) -> None:
        for t, node in list(running.items()):
            t.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await t
            err = ErrorDict("TIMEOUT", f"{node.id} cancelled at the organ-phase deadline", True)
            attempt_no = max(self._current.get(node.id, 1), 1)
            entry_id = self.record_failure(node, attempt_no, err)
            outcome = NodeOutcome(
                node.id,
                "timed_out",
                entry_id=entry_id,
                error=err,
                attempts=attempt_no,
                reason="DEADLINE",
                ended_at=self.clock.now(),
            )
            finish(node, outcome)
            del running[t]
