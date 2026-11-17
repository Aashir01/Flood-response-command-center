"""Live mode against recorded Open-Meteo responses, sockets disabled (task 15; ORA-R1.3, R1.4,
R11.2; ORA-X10). One ``@pytest.mark.live`` test calls the real API and is excluded from CI.

The fixture ``tests/fixtures/live_openmeteo.json`` is written by
``scripts/record_oracle_live_fixture.py``. Data: modeled GloFAS discharge (Open-Meteo Flood API)
and forecast-model rain and temperature (Open-Meteo Forecast API), CC BY 4.0.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stitch_common.envelope import ToolResult
from stitch_common.tooling import run_tool
from stitch_oracle.data.loader import load_demo
from stitch_oracle.live import FLOOD_URL, LiveUnavailable, OpenMeteoLive
from stitch_oracle.service import OracleService
from stitch_oracle.store import RunStore

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "live_openmeteo.json"
DOC: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
NOW = datetime.strptime(DOC["recorded_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
TODAY = NOW.date()
REQ = {"station_id": "indus-sukkur", "horizon_days": 5, "mode": "live"}


def replay(doc: dict[str, Any]) -> Any:
    by_url = {c["url"]: c["response"] for c in doc["calls"]}

    def fetch(url: str, params: dict[str, str]) -> Any:
        return copy.deepcopy(by_url[url])

    return fetch


def outage(url: str, params: dict[str, str]) -> Any:
    raise OSError("network unreachable (simulated outage)")


def live(tmp: Path, fetch: Any = None) -> OpenMeteoLive:
    return OpenMeteoLive(tmp, fetch=fetch or replay(DOC), now=lambda: NOW)


def call(svc: OracleService, args: dict[str, Any]) -> ToolResult[Any]:
    return asyncio.run(
        run_tool("oracle", "forecast_river", "test", svc.cores()["forecast_river"], args)
    )


def test_fixture_parses_into_frames(tmp_path: Path) -> None:
    frames, notes = live(tmp_path).frames(DOC["stations"], load_demo())
    assert set(frames.discharge["station_id"]) == set(DOC["stations"])
    assert max(frames.discharge["date"]) == TODAY - timedelta(days=1)  # only days before today
    assert (frames.discharge["discharge_m3s"] >= 0).all()
    assert any("modeled GloFAS discharge" in n for n in notes)
    assert (tmp_path / "live_discharge.parquet").is_file()  # cached


def test_live_forecast_reports_live_mode(tmp_path: Path) -> None:
    svc = OracleService(store=RunStore(), live=live(tmp_path))
    r = call(svc, REQ)
    assert r.ok, r.error
    assert r.provenance.mode == "live"
    assert r.data is not None and r.data.as_of == TODAY - timedelta(days=1)
    assert r.data.target_kind == "modeled_glofas"
    assert not any(w.startswith("MODE_FALLBACK") for w in r.warnings)
    assert all("committed demo extract" not in s.name for s in r.provenance.data_sources)


def test_outage_uses_cache_with_warning(tmp_path: Path) -> None:
    live(tmp_path).frames(DOC["stations"], load_demo())  # fills the cache
    svc = OracleService(store=RunStore(), live=live(tmp_path, outage))
    r = call(svc, REQ)
    assert r.ok and r.provenance.mode == "live"
    assert any("live fetch failed (OSError); using cached live data" in w for w in r.warnings)


def test_outage_without_cache_falls_back_to_demo(tmp_path: Path) -> None:
    src = live(tmp_path / "empty", outage)
    with pytest.raises(LiveUnavailable):
        src.frames(DOC["stations"], load_demo())
    r = call(OracleService(store=RunStore(), live=src), REQ)
    assert r.ok and r.provenance.mode == "demo"
    assert any(w.startswith("MODE_FALLBACK") for w in r.warnings)


def _drop_days(n: int) -> dict[str, Any]:
    """Remove ``n`` consecutive days (ending 5 days before today) from Sukkur's series."""
    doc = copy.deepcopy(DOC)
    for c in doc["calls"]:
        if c["url"] != FLOOD_URL:
            continue
        items = c["response"] if isinstance(c["response"], list) else [c["response"]]
        daily = items[0]["daily"]  # first coordinate = indus-sukkur
        drop = {(TODAY - timedelta(days=5 + k)).isoformat() for k in range(n)}
        daily["river_discharge"] = [
            None if t in drop else v
            for t, v in zip(daily["time"], daily["river_discharge"], strict=True)
        ]
    return doc


def test_ora_x10_two_day_gap_is_filled_with_warning(tmp_path: Path) -> None:
    svc = OracleService(store=RunStore(), live=live(tmp_path, replay(_drop_days(2))))
    r = call(svc, REQ)
    assert r.ok and r.provenance.mode == "live"
    assert any("filled" in w.lower() for w in r.warnings), r.warnings


def test_ora_x10_three_day_gap_is_upstream_unavailable(tmp_path: Path) -> None:
    svc = OracleService(store=RunStore(), live=live(tmp_path, replay(_drop_days(3))))
    r = call(svc, REQ)
    assert not r.ok and r.error is not None
    assert r.error.code == "UPSTREAM_UNAVAILABLE" and r.error.retryable


def test_live_request_inside_demo_window_uses_demo(tmp_path: Path) -> None:
    svc = OracleService(store=RunStore(), live=live(tmp_path, outage))
    r = call(svc, {**REQ, "as_of": "2022-08-15"})
    assert r.ok and r.provenance.mode == "demo"
    assert any("demo data covers it" in w for w in r.warnings)


@pytest.mark.live
def test_real_open_meteo_round_trip(tmp_path: Path) -> None:  # pragma: no cover - network
    svc = OracleService(store=RunStore(), live=OpenMeteoLive(tmp_path))
    r = call(svc, REQ)
    assert r.ok, r.error
    assert r.provenance.mode == "live"
    assert r.data is not None and r.data.as_of >= date.today() - timedelta(days=3)
