"""Service-level unit tests: tool wiring, error mapping, explain (ORA-R4, X4), run store."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from stitch_common.envelope import ToolResult
from stitch_common.organs.oracle import TARGET_LABEL, ForecastRiverOut
from stitch_common.tooling import run_tool
from stitch_oracle.models import TOOL_NAMES
from stitch_oracle.service import OracleService
from stitch_oracle.store import RunStore

SUKKUR = {"station_id": "indus-sukkur", "horizon_days": 14, "as_of": "2022-08-15"}


@pytest.fixture(scope="module")
def svc() -> OracleService:
    return OracleService(store=RunStore())


def call(svc: OracleService, tool: str, args: dict[str, Any]) -> ToolResult[Any]:
    return asyncio.run(run_tool("oracle", tool, "test", svc.cores()[tool], args))


def test_cores_cover_exactly_the_contract_tools(svc: OracleService) -> None:
    assert sorted(svc.cores()) == sorted(TOOL_NAMES)


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_invalid_input_is_reported_not_raised(svc: OracleService, tool: str) -> None:
    result = call(svc, tool, {"unexpected": 1})
    assert result.error is not None and result.error.code == "INVALID_INPUT"


def test_forecast_envelope_labels_and_provenance(svc: OracleService) -> None:
    r = call(svc, "forecast_river", SUKKUR)
    assert r.ok and r.data is not None
    out = ForecastRiverOut.model_validate(r.data.model_dump())
    assert out.target_kind == "modeled_glofas" and out.target_label == TARGET_LABEL
    assert [p.lead_days for p in out.forecast] == list(range(1, 15))
    assert out.station is not None and out.station.name.startswith("GloFAS grid cell nearest to")
    assert out.calibration.interval_lower_q == 0.1 and out.calibration.interval_upper_q == 0.9
    assert len(out.exceedance_prob) == 14 and out.danger_threshold_m3s
    p = r.provenance
    assert p.mode == "demo" and p.model is not None and len(p.model.sha256) == 64
    assert p.model.sha256 == svc.bundle().sha256
    assert {s.license for s in p.data_sources} == {"CC BY 4.0"}
    assert any("demo data" in w for w in r.warnings)
    assert any("modeled 5-year return level" in w for w in r.warnings)


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ({"station_id": "indus-sukkur", "horizon_days": 15}, "INVALID_INPUT"),
        ({"station_id": "indus-sukkur", "horizon_days": 0}, "INVALID_INPUT"),
        ({"station_id": "indus-sukkur", "horizon_days": 3, "as_of": "2015-08-01"}, "INVALID_INPUT"),
        ({"station_id": "indus-sukkur", "horizon_days": 3, "coverage": 0.995}, "INVALID_INPUT"),
        ({"station_id": "indus-kalabagh", "horizon_days": 3}, "INVALID_INPUT"),
        ({"station_id": "sukkur", "horizon_days": 3}, "NOT_FOUND"),
    ],
)
def test_error_mapping(svc: OracleService, args: dict[str, Any], code: str) -> None:
    r = call(svc, "forecast_river", args)
    assert not r.ok and r.error is not None and r.error.code == code
    if code == "NOT_FOUND":
        assert "indus-sukkur" in r.error.message


def test_explain_round_trip(svc: OracleService) -> None:
    r = call(svc, "forecast_river", SUKKUR)
    e = call(svc, "explain_forecast", {"run_id": r.provenance.run_id})
    assert e.ok and e.data is not None
    d = e.data
    assert 1 <= len(d.drivers) <= 5 and d.lead_days_explained in range(1, 15)
    assert all(x.feature_group for x in d.drivers)
    assert "Modeled river discharge (GloFAS via Open-Meteo)" in d.narrative
    assert "gauge" not in d.narrative.lower() and "observed" not in d.narrative.lower()
    assert e.provenance.model is not None


def test_explain_unknown_run_is_not_found(svc: OracleService) -> None:
    e = call(svc, "explain_forecast", {"run_id": "no-such-run"})
    assert e.error is not None and e.error.code == "NOT_FOUND"


def test_live_request_without_live_source_falls_back_to_demo() -> None:
    svc = OracleService(store=RunStore())
    args = {"station_id": "indus-kotri", "horizon_days": 3, "mode": "live"}
    r = call(svc, "forecast_river", args)
    assert r.ok and r.provenance.mode == "demo"
    assert any(w.startswith("MODE_FALLBACK") for w in r.warnings)


def test_stations_resource(svc: OracleService) -> None:
    rows = svc.stations()
    ids = {s.station_id for s in rows}
    assert {"indus-guddu", "indus-sukkur", "indus-kotri"} <= ids
    for s in rows:
        assert s.name.startswith("GloFAS grid cell nearest to")
        assert s.as_of_min == date(2017, 1, 1) and s.as_of_max == date(2023, 12, 31)


def test_health(svc: OracleService) -> None:
    assert svc.health() == {"bundle": True, "dataset": True, "store": True}
