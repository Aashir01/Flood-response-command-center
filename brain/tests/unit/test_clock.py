"""Virtual clock ordering and ``wait_for`` (task 2)."""

from __future__ import annotations

import asyncio

import pytest

from stitch_brain.runtime.clock import VirtualClock, wait_for


async def test_virtual_clock_wakes_sleepers_in_deadline_order() -> None:
    clock = VirtualClock()
    order: list[str] = []

    async def sleeper(name: str, s: float) -> None:
        await clock.sleep(s)
        order.append(f"{name}@{clock.monotonic():g}")

    async with clock.autojump():
        await asyncio.gather(sleeper("c", 3), sleeper("a", 1), sleeper("b", 2))
    assert order == ["a@1", "b@2", "c@3"]


async def test_wait_for_times_out_in_virtual_time() -> None:
    clock = VirtualClock()

    async def slow() -> int:
        await clock.sleep(100)
        return 1

    async with clock.autojump():
        with pytest.raises(TimeoutError):
            await wait_for(clock, slow(), 5)
        assert clock.monotonic() == 5
        assert await wait_for(clock, slow(), 500) == 1
