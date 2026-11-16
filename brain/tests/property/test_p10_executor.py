"""BRN-P10 executor invariants, plus named executor unit tests (task 6; BRN-R3.1 to R3.4)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from stitch_brain.core.graph import Dep, Node
from stitch_brain.runtime.clock import VirtualClock
from stitch_brain.runtime.executor import (
    TERMINAL,
    AttemptResult,
    ErrorDict,
    Executor,
    Limits,
    NodeOutcome,
)


def _node(nid: str, organ: str, deps: list[tuple[str, str]] = (), **kw: Any) -> Node:  # type: ignore[assignment]
    return Node(
        id=nid,
        kind="organ",
        organ=organ,
        tool="t",
        builder="analysis",
        deps=[Dep(id=d, need=n) for d, n in deps],  # type: ignore[arg-type]
        **kw,
    )


class Fake:
    """Attempt function with scripted delays and failures, recording start/end times."""

    def __init__(self, clock: VirtualClock, script: dict[str, list[tuple[float, str]]]) -> None:
        self.clock = clock
        self.script = script
        self.starts: dict[str, list[float]] = {}
        self.ends: dict[str, float] = {}
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, node: Node, attempt: int) -> AttemptResult:
        self.calls.append((node.id, attempt))
        self.starts.setdefault(node.id, []).append(self.clock.monotonic())
        steps = self.script.get(node.id, [(1.0, "ok")])
        delay, kind = steps[min(attempt - 1, len(steps) - 1)]
        await self.clock.sleep(delay)
        self.ends[node.id] = self.clock.monotonic()
        if kind == "ok":
            return AttemptResult(ok=True, entry_id=f"{node.id}#{attempt}")
        if kind == "raise":
            raise RuntimeError("boom")
        return AttemptResult(
            ok=False, error=ErrorDict("UPSTREAM_UNAVAILABLE", "x", kind == "retry")
        )


async def _run(
    nodes: list[Node], fake: Fake, clock: VirtualClock, **lim: Any
) -> tuple[dict[str, NodeOutcome], Executor]:
    ex = Executor(clock=clock, attempt=fake, limits=Limits(**lim))
    async with clock.autojump():
        out = await ex.run(nodes)
    return out, ex


GRAPH = [
    _node("eyes.a", "eyes"),
    _node("eyes.b", "eyes"),
    _node("eyes.c", "eyes"),
    _node("oracle.f", "oracle"),
    _node("oracle.x", "oracle", [("oracle.f", "hard")]),
    _node("lib.1", "library"),
    _node("lib.2", "library"),
    _node("lib.3", "library"),
    _node("led.o", "ledger", [("eyes.a", "soft"), ("oracle.f", "soft")]),
    _node("led.s", "ledger", [("led.o", "hard")]),
]
KINDS = st.sampled_from(["ok", "ok", "ok", "fail", "retry", "raise"])


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    st.dictionaries(
        st.sampled_from([n.id for n in GRAPH]),
        st.lists(st.tuples(st.floats(0, 12), KINDS), min_size=1, max_size=3),
    )
)
def test_brn_p10_invariants(script: dict[str, list[tuple[float, str]]]) -> None:
    async def go() -> None:
        clock = VirtualClock()
        fake = Fake(clock, script)
        out, ex = await _run(GRAPH, fake, clock, organ_phase_deadline_s=20)
        assert set(out) == {n.id for n in GRAPH}
        assert all(o.status in TERMINAL for o in out.values())
        assert clock.monotonic() <= 20 + 1e-9
        assert ex.max_seen_in_flight <= 6
        assert all(v <= 2 for v in ex.max_seen_per_organ.values())
        for n in GRAPH:
            for d in n.deps:
                if d.need == "hard" and out[d.id].status != "ok":
                    assert out[n.id].status in ("skipped", "timed_out")
                if d.need == "hard" and n.id in fake.starts:
                    assert min(fake.starts[n.id]) >= fake.ends.get(d.id, 0)
        for nid, attempts in _attempts(fake).items():
            assert attempts <= 3
            if attempts > 1:
                delay, kind = script[nid][0]
                assert kind == "retry" or delay > 10  # retryable error or a timeout

    asyncio.run(go())


def _attempts(fake: Fake) -> dict[str, int]:
    out: dict[str, int] = {}
    for nid, a in fake.calls:
        out[nid] = max(out.get(nid, 0), a)
    return out


async def test_retry_only_on_retryable() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"a": [(0, "retry"), (0, "retry"), (0, "ok")], "b": [(0, "fail")]})
    out, _ = await _run([_node("a", "x"), _node("b", "y")], fake, clock)
    assert out["a"].status == "ok" and out["a"].attempts == 3
    assert out["b"].status == "failed" and out["b"].attempts == 1


async def test_timeout_is_retryable_and_marks_timed_out() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"a": [(50, "ok")]})
    out, _ = await _run([_node("a", "x", timeout_s=5)], fake, clock, organ_phase_deadline_s=100)
    assert out["a"].status == "timed_out" and out["a"].attempts == 3
    assert out["a"].error is not None and out["a"].error.code == "TIMEOUT"


async def test_deadline_marks_in_flight_timed_out_and_skips_dependents() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"a": [(30, "ok")]})
    nodes = [_node("a", "x", timeout_s=40), _node("b", "y", [("a", "hard")])]
    out, _ = await _run(nodes, fake, clock, organ_phase_deadline_s=10)
    assert out["a"].status == "timed_out" and out["a"].reason == "DEADLINE"
    assert out["b"].status == "skipped"
    assert clock.monotonic() == 10


async def test_exception_becomes_failed_internal() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"a": [(0, "raise")]})
    out, _ = await _run([_node("a", "x")], fake, clock)
    assert out["a"].status == "failed"
    assert out["a"].error is not None and out["a"].error.code == "INTERNAL"


async def test_soft_dependency_runs_after_failure() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"a": [(1, "fail")]})
    out, _ = await _run([_node("a", "x"), _node("b", "y", [("a", "soft")])], fake, clock)
    assert out["b"].status == "ok"


async def test_cancellation_marks_cancelled() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"a": [(100, "ok")]})
    ex = Executor(clock=clock, attempt=fake)
    seen: dict[str, NodeOutcome] = {}
    ex.on_result = lambda n, o: seen.__setitem__(n.id, o)
    async with clock.autojump():
        task = asyncio.create_task(ex.run([_node("a", "x"), _node("b", "y", [("a", "hard")])]))
        await clock.sleep(1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert seen["a"].status == "cancelled" and seen["b"].status == "cancelled"


async def test_three_organ_graph_runs_in_expected_order() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {"eyes": [(3, "ok")], "oracle": [(1, "ok")], "ledger": [(2, "ok")]})
    nodes = [
        _node("eyes", "eyes"),
        _node("oracle", "oracle"),
        _node("ledger", "ledger", [("eyes", "soft"), ("oracle", "soft")]),
    ]
    out, _ = await _run(nodes, fake, clock)
    assert all(o.ok for o in out.values())
    assert fake.starts["eyes"] == [0] and fake.starts["oracle"] == [0]
    assert fake.starts["ledger"] == [3] and clock.monotonic() == 5


async def test_dynamic_node_uses_prior_outcomes() -> None:
    clock = VirtualClock()
    fake = Fake(clock, {})
    out1, ex = await _run([_node("a", "x")], fake, clock)
    async with clock.autojump():
        out2 = await ex.run([_node("r", "x", [("a", "soft")])], prior=out1)
    assert set(out2) == {"r"} and out2["r"].ok
