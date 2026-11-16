"""oracle-mcp tool I/O (mcp-contracts.md section 4).

Ambiguities: ``coverage`` is an open interval (0, 1). ``forecast`` has at least one point.
``target_kind`` and ``target_label`` are single-value literals so a forecast can never be
labelled as a gauge reading (ORA-P8).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from stitch_common.base import Contract
from stitch_common.types import Interval, Mode, Unit

TARGET_LABEL = "Modeled river discharge (GloFAS via Open-Meteo)"


class ForecastRiverIn(Contract):
    station_id: str = Field(min_length=1)
    horizon_days: int = Field(ge=1, le=14)
    as_of: date | None = None
    coverage: float = Field(default=0.8, gt=0.0, lt=1.0)
    mode: Mode | None = None  # v0.4


class ForecastPoint(Contract):
    date: date
    lead_days: int = Field(ge=0)
    discharge: Interval
    rainfall_mm: Interval | None = None


class ExceedancePoint(Contract):
    date: date
    p_exceed: Unit


class Calibration(Contract):
    method: Literal["split_conformal"]
    nominal_coverage: Unit
    n_calibration: int = Field(ge=0)
    # v0.4: quantile levels that Interval.p10 / p90 represent at the requested coverage
    # (for example 0.05 and 0.95 at coverage 0.9). Absent means unknown.
    interval_lower_q: Unit | None = None
    interval_upper_q: Unit | None = None


class Station(Contract):
    """v0.4: the station and the GloFAS grid cell that was actually read (ORA-R8.3)."""

    name: str
    river: str
    cell_lat: float = Field(ge=-90.0, le=90.0)
    cell_lon: float = Field(ge=-180.0, le=180.0)
    requested_lat: float = Field(ge=-90.0, le=90.0)
    requested_lon: float = Field(ge=-180.0, le=180.0)


class ForecastRiverOut(Contract):
    station_id: str
    unit: Literal["m3/s"]
    as_of: date
    target_kind: Literal["modeled_glofas"]
    target_label: Literal["Modeled river discharge (GloFAS via Open-Meteo)"]
    forecast: list[ForecastPoint] = Field(min_length=1)
    danger_threshold_m3s: float | None
    exceedance_prob: list[ExceedancePoint]
    calibration: Calibration
    station: Station | None = None  # v0.4
    quantile_correction_applied: bool | None = None  # v0.4


class ExplainForecastIn(Contract):
    run_id: str = Field(min_length=1)


class Driver(Contract):
    feature: str
    contribution_m3s: float
    direction: Literal["up", "down"]
    feature_group: str | None = None  # v0.4


class ExplainForecastOut(Contract):
    drivers: list[Driver]
    narrative: str
    baseline_m3s: float
    lead_days_explained: int | None = Field(default=None, ge=0)  # v0.4


class StationInfo(Contract):
    """One item of the read-only resource ``oracle://stations`` (v0.4)."""

    station_id: str = Field(min_length=1)
    name: str
    river: str
    role: str
    cell_lat: float = Field(ge=-90.0, le=90.0)
    cell_lon: float = Field(ge=-180.0, le=180.0)
    danger_threshold_m3s: float | None
    threshold_method: str | None
    as_of_min: date
    as_of_max: date
