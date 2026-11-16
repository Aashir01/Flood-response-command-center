"""Clocks. The executor, retries, deadlines, rate limiter and store take time from a ``Clock``
so tests can run in virtual time (design 7.3).

``VirtualClock`` keeps a heap of sleepers. Time only moves when a test calls ``advance`` or
while ``autojump()`` is active: the jumper yields to the event loop a number of times and, when
the loop has gone quiet, jumps to the earliest pending deadline. It is meant for pure-async
fakes; code that blocks in threads must use ``RealClock``.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return asyncio.get_running_loop().time() if _has_loop() else _mono()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


def _has_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _mono() -> float:
    import time

    return time.monotonic()


class VirtualClock:
    """Deterministic clock. ``now()`` is ``start + elapsed``."""

    def __init__(self, start: datetime | None = None, *, idle_spins: int = 30) -> None:
        self._start = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._t = 0.0
        self._heap: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()
        self._idle_spins = idle_spins

    def now(self) -> datetime:
        return self._start + timedelta(seconds=self._t)

    def monotonic(self) -> float:
        return self._t

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._heap, (self._t + seconds, next(self._seq), fut))
        await fut

    def pending(self) -> int:
        return sum(1 for _, _, f in self._heap if not f.done())

    def advance(self, seconds: float) -> None:
        self._advance_to(self._t + max(0.0, seconds))

    def _advance_to(self, target: float) -> None:
        while self._heap and self._heap[0][0] <= target:
            when, _, fut = heapq.heappop(self._heap)
            self._t = max(self._t, when)
            if not fut.done():
                fut.set_result(None)
        self._t = max(self._t, target)

    def _jump_next(self) -> bool:
        while self._heap and self._heap[0][2].done():
            heapq.heappop(self._heap)
        if not self._heap:
            return False
        self._advance_to(self._heap[0][0])
        return True

    @asynccontextmanager
    async def autojump(self) -> AsyncIterator[None]:
        async def jumper() -> None:
            while True:
                for _ in range(self._idle_spins):
                    await asyncio.sleep(0)
                self._jump_next()

        task = asyncio.create_task(jumper())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def wait_for[T](clock: Clock, aw: Awaitable[T], timeout: float) -> T:
    """Like ``asyncio.wait_for`` but the timer runs on ``clock``. Raises ``TimeoutError``."""
    task: asyncio.Future[T] = asyncio.ensure_future(aw)
    timer: asyncio.Future[None] = asyncio.ensure_future(clock.sleep(timeout))
    try:
        waiters: set[asyncio.Future[Any]] = {task, timer}
        done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        task.cancel()
        timer.cancel()
        raise
    if task in done:
        timer.cancel()
        return task.result()
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task
    raise TimeoutError(f"timed out after {timeout} s")
