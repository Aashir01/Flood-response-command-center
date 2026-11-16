"""RunStore: ``forecast_river`` runs by ``run_id`` for ``explain_forecast`` (design section 7).

DuckDB table ``runs(run_id, created_us, seq, input_json, output_json, extra_json)``;
``created_us`` is epoch microseconds (UTC). ``extra_json`` holds what the explanation needs: the
feature row, the anchor discharge, the station and the bundle root hash. Runs are kept at least
24 h and purged once older than 48 h; at most ``MAX_ROWS`` rows (oldest first out). Writes are
serialised by a lock. ``path=None`` keeps the database in memory (the fallback when no volume is
mounted). The clock is injectable for tests.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

RETAIN = timedelta(hours=24)
PURGE_AFTER = timedelta(hours=48)
MAX_ROWS = 1000

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _us(t: datetime) -> int:
    return round(t.timestamp() * 1e6)


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    created_at: datetime
    input_json: str
    output_json: str
    extra_json: str


class RunStore:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Clock = utc_now,
        max_rows: int = MAX_ROWS,
        purge_after: timedelta = PURGE_AFTER,
    ) -> None:
        if purge_after < RETAIN:
            raise ValueError("purge_after must be at least the 24 h retention")
        self._clock = clock
        self._max_rows = max_rows
        self._purge_after = purge_after
        self._lock = threading.Lock()
        target = ":memory:"
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            target = str(path)
        self._con = duckdb.connect(target)
        with self._lock:
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                " run_id VARCHAR PRIMARY KEY,"
                " created_us BIGINT NOT NULL,"
                " seq BIGINT NOT NULL,"
                " input_json VARCHAR NOT NULL,"
                " output_json VARCHAR NOT NULL,"
                " extra_json VARCHAR NOT NULL)"
            )

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo else now.replace(tzinfo=UTC)

    def put(self, run_id: str, input_json: str, output_json: str, extra_json: str) -> None:
        with self._lock:
            now = self._now()
            row = self._con.execute("SELECT coalesce(max(seq), 0) + 1 FROM runs").fetchone()
            seq = int(row[0]) if row else 1
            self._con.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                [run_id, _us(now), seq, input_json, output_json, extra_json],
            )
            self._purge_locked(now)

    def get(self, run_id: str) -> StoredRun | None:
        """The run, or None when unknown or older than the purge age."""
        with self._lock:
            now = self._now()
            row = self._con.execute(
                "SELECT run_id, created_us, input_json, output_json, extra_json FROM runs "
                "WHERE run_id = ?",
                [run_id],
            ).fetchone()
        if row is None:
            return None
        created = datetime.fromtimestamp(int(row[1]) / 1e6, UTC)
        if now - created > self._purge_after:
            return None
        return StoredRun(str(row[0]), created, str(row[2]), str(row[3]), str(row[4]))

    def _purge_locked(self, now: datetime) -> None:
        self._con.execute("DELETE FROM runs WHERE created_us < ?", [_us(now - self._purge_after)])
        self._con.execute(
            "DELETE FROM runs WHERE seq NOT IN (SELECT seq FROM runs ORDER BY seq DESC LIMIT ?)",
            [self._max_rows],
        )

    def count(self) -> int:
        with self._lock:
            row = self._con.execute("SELECT count(*) FROM runs").fetchone()
        return int(row[0]) if row else 0

    def writable(self) -> bool:
        try:
            with self._lock:
                self._con.execute("CREATE TEMP TABLE IF NOT EXISTS _probe (x INT)")
            return True
        except duckdb.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._con.close()
