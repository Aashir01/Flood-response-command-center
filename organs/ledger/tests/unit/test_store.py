"""RunStore: round trip, TTL with an injected clock, row cap, concurrent writes, restart
(LED-R8.2, LED-R6.4)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stitch_ledger.store import MAX_ROWS, RunStore


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def test_round_trip() -> None:
    store = RunStore()
    store.put("r1", '{"a":1}', '{"b":2}')
    got = store.get("r1")
    assert got is not None and (got.input_json, got.output_json) == ('{"a":1}', '{"b":2}')
    assert store.get("missing") is None


def test_runs_are_kept_for_24h_and_gone_after_48h() -> None:
    clock = FakeClock()
    store = RunStore(clock=clock)
    store.put("r1", "{}", "{}")
    clock.advance(hours=24)
    assert store.get("r1") is not None  # at least 24 h
    clock.advance(hours=23, minutes=59)
    assert store.get("r1") is not None
    clock.advance(minutes=2)
    assert store.get("r1") is None  # older than 48 h reads as expired
    store.purge()
    assert store.count() == 0


def test_purge_happens_on_write() -> None:
    clock = FakeClock()
    store = RunStore(clock=clock)
    store.put("old", "{}", "{}")
    clock.advance(hours=49)
    store.put("new", "{}", "{}")
    assert store.count() == 1 and store.get("new") is not None


def test_row_cap_evicts_the_oldest_first() -> None:
    clock = FakeClock()
    store = RunStore(clock=clock, max_rows=5)
    for i in range(8):
        store.put(f"r{i}", "{}", "{}")
        clock.advance(seconds=1)
    assert store.count() == 5
    assert store.get("r0") is None and store.get("r2") is None
    assert all(store.get(f"r{i}") is not None for i in range(3, 8))
    assert MAX_ROWS == 1000


def test_cap_counts_insertion_order_even_with_equal_timestamps() -> None:
    store = RunStore(clock=FakeClock(), max_rows=3)
    for i in range(5):
        store.put(f"r{i}", "{}", "{}")
    assert [store.get(f"r{i}") is not None for i in range(5)] == [False, False, True, True, True]


def test_concurrent_writes_are_serialised() -> None:
    store = RunStore()

    def writer(base: int) -> None:
        for i in range(25):
            store.put(f"w{base}-{i}", "{}", "{}")

    threads = [threading.Thread(target=writer, args=(b,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.count() == 200


def test_file_mode_survives_a_restart(tmp_path: Path) -> None:
    clock = FakeClock()
    path = tmp_path / "runs" / "ledger.duckdb"
    store = RunStore(path, clock=clock)
    store.put("r1", '{"x":1}', "{}")
    store.close()
    clock.advance(hours=23)
    reopened = RunStore(path, clock=clock)
    got = reopened.get("r1")
    assert got is not None and got.input_json == '{"x":1}'
    assert reopened.writable()
    reopened.close()


def test_purge_age_below_the_retention_is_rejected() -> None:
    with pytest.raises(ValueError):
        RunStore(purge_after=timedelta(hours=1))
