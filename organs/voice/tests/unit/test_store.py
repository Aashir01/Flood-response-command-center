"""AudioStore and BudgetStore (voice task 2; VOX-R3.2, R10.4)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
import voice_helpers as h

from stitch_voice import store as store_mod
from stitch_voice.providers.prerendered import PrerenderedStore
from stitch_voice.store import AudioStore, BudgetStore


def test_cache_hit_returns_identical_bytes(tmp_path: Path) -> None:
    s = AudioStore(tmp_path / "audio")
    s.put("ab" * 32, b"RIFF-bytes", {"lang": "en"})
    hit = s.get("ab" * 32)
    assert hit is not None and hit[0] == b"RIFF-bytes" and hit[1] == {"lang": "en"}
    assert s.get("cd" * 32) is None


def test_failed_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(src: str, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store_mod.os, "replace", boom)
    s = AudioStore(tmp_path / "audio")
    s.put("ab" * 32, b"x" * 1000, {})  # a failing cache never fails the request
    assert s.get("ab" * 32) is None
    assert [p for p in (tmp_path / "audio").rglob("*") if p.is_file()] == []


def test_eviction_is_lru_and_never_touches_prerendered(tmp_path: Path) -> None:
    pre = tmp_path / "prerendered"
    wav = h.add_prerendered(pre, "Demo text.", "en", "v")
    s = AudioStore(tmp_path / "audio", max_bytes=2500)
    for i in range(5):
        s.put(f"{i:02d}" * 32, bytes([i]) * 1000, {})
    kept = sorted(p.name[:2] for p in (tmp_path / "audio").glob("*/*.wav"))
    assert kept == ["03", "04"]
    assert PrerenderedStore(pre).lookup("Demo text.", "en").wav == wav


def test_budget_never_exceeds_cap_under_concurrency(tmp_path: Path) -> None:
    b = BudgetStore(tmp_path / "budget.sqlite3")
    allowed: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        d = b.reserve("deepgram", "tts_chars", 30, 100)
        with lock:
            allowed.append(d.allowed)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(allowed) == 3 and b.used("deepgram", "tts_chars") == 90


def test_budget_release_and_month_rollover(tmp_path: Path) -> None:
    now = [datetime(2026, 11, 30, 23, 59, tzinfo=UTC)]
    b = BudgetStore(tmp_path / "budget.sqlite3", clock=lambda: now[0])
    assert b.reserve("deepgram", "tts_chars", 90, 100).allowed
    assert not b.reserve("deepgram", "tts_chars", 20, 100).allowed
    b.release("deepgram", "tts_chars", 90)
    assert b.used("deepgram", "tts_chars") == 0
    assert b.reserve("deepgram", "tts_chars", 95, 100).warn  # 80 % warning
    now[0] = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)
    assert b.used("deepgram", "tts_chars") == 0
    assert b.reserve("deepgram", "tts_chars", 100, 100).allowed
    assert b.used("azure", "tts_chars") == 0  # per provider
