"""Storage: synthesized-audio cache and the monthly budget counter (design 5 and 14).

Only synthesized briefing audio is stored. User audio is never written anywhere (VOX-R4.1).
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import tempfile
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stitch_voice.core.budget import Decision, decide, month_key


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class AudioStore:
    """Files at ``<root>/<key[:2]>/<key>.wav`` plus a ``.json`` sidecar. Writes are atomic.
    Least-recently-used eviction above ``max_bytes`` (the prerendered root is a different
    directory and is never touched)."""

    def __init__(self, root: Path, max_bytes: int = 100 * 1024 * 1024) -> None:
        self.root = root
        self.max_bytes = max_bytes

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.wav"

    def get(self, key: str) -> tuple[bytes, dict[str, Any]] | None:
        path = self._path(key)
        meta_path = path.with_suffix(".json")
        try:
            data = path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        with contextlib.suppress(OSError):
            os.utime(path)  # LRU bookkeeping
        return data, meta if isinstance(meta, dict) else {}

    def put(self, key: str, data: bytes, meta: dict[str, Any]) -> None:
        try:
            path = self._path(key)
            _atomic_write(path, data)
            _atomic_write(path.with_suffix(".json"), json.dumps(meta).encode("utf-8"))
            self._evict()
        except OSError:
            pass  # a read-only or full cache never fails a request

    def _evict(self) -> None:
        files = sorted(self.root.glob("*/*.wav"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= self.max_bytes:
                break
            total -= path.stat().st_size
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)


class BudgetStore:
    """Per provider and metric, per UTC month, in SQLite. ``reserve`` is atomic across threads
    and processes (``BEGIN IMMEDIATE``)."""

    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = path
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS usage (provider TEXT, metric TEXT, month TEXT, "
                "used REAL NOT NULL, PRIMARY KEY (provider, metric, month))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10, isolation_level=None)

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # `with sqlite3.connect(...)` does not close the connection; on Windows an open handle
        # keeps the file locked (cache directory cleanup, volume rotation).
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    def used(self, provider: str, metric: str) -> float:
        with self._db() as db:
            row = db.execute(
                "SELECT used FROM usage WHERE provider=? AND metric=? AND month=?",
                (provider, metric, month_key(self._clock())),
            ).fetchone()
        return float(row[0]) if row else 0.0

    def reserve(self, provider: str, metric: str, amount: float, cap: float) -> Decision:
        month = month_key(self._clock())
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT used FROM usage WHERE provider=? AND metric=? AND month=?",
                    (provider, metric, month),
                ).fetchone()
                decision = decide(float(row[0]) if row else 0.0, amount, cap)
                if decision.allowed:
                    db.execute(
                        "INSERT INTO usage VALUES (?, ?, ?, ?) ON CONFLICT(provider, metric, month)"
                        " DO UPDATE SET used = excluded.used",
                        (provider, metric, month, decision.used_after),
                    )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            finally:
                db.close()
        return decision

    def release(self, provider: str, metric: str, amount: float) -> None:
        month = month_key(self._clock())
        with self._lock, self._db() as db:
            db.execute(
                "UPDATE usage SET used = MAX(0, used - ?)"
                " WHERE provider=? AND metric=? AND month=?",
                (amount, provider, metric, month),
            )
