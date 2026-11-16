"""Oracle service: the layer between the MCP tools and the pure ``core`` (design sections 5 to 8).

It loads the committed dataset and the hash-verified model bundle, maps contract models to the
core request, maps core results and failures to contract models and ``ToolFailure`` codes, and
keeps runs in the ``RunStore`` so ``explain_forecast`` can find them by ``run_id`` (the call-level
``provenance.run_id``). All I/O lives here and in ``data``/``live``, none in ``core``.

Wording rule (ORA-R8): the target is always "modeled river discharge (GloFAS via Open-Meteo)".
Stations are "GloFAS grid cell nearest to <name>".
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np

from stitch_common.organs.oracle import (
    TARGET_LABEL,
    Calibration,
    Driver,
    ExceedancePoint,
    ExplainForecastIn,
    ExplainForecastOut,
    ForecastPoint,
    ForecastRiverIn,
    ForecastRiverOut,
    Station,
    StationInfo,
)
from stitch_common.provenance import DataSource, ModelInfo, canonical_json
from stitch_common.tooling import Outcome, ToolFailure, current_mode
from stitch_common.types import Interval, Mode
from stitch_oracle.core import conformal
from stitch_oracle.core.bundle import BundleError, ModelBundle
from stitch_oracle.core.explain import explain, narrative
from stitch_oracle.core.features import FEATURES, Frames
from stitch_oracle.core.forecast import ForecastError, ForecastResult, Request, forecast, peak_lead
from stitch_oracle.core.splits import AS_OF_MIN
from stitch_oracle.data.loader import DatasetError, DemoData, load_demo
from stitch_oracle.store import RunStore

TARGET_KIND: Final = "modeled_glofas"
DB_ENV = "STITCH_ORACLE_DB"
MODELS_ENV = "STITCH_ORACLE_MODELS"
DEFAULT_MODELS = Path(__file__).resolve().parents[2] / "models"

MODE_FALLBACK_WARNING = (
    "MODE_FALLBACK: live mode was requested, but live data could not be used ({reason}); "
    "the committed demo data was used instead"
)
DEMO_NOTE = (
    "demo data: modeled GloFAS discharge and ERA5 rainfall committed with Stitch "
    "({start} to {end}), not a live feed"
)


class LiveSource(Protocol):
    """Optional live data provider (``live.py``). Raises ``LiveUnavailable`` on any failure."""

    def frames(self, station_ids: list[str], demo: DemoData) -> tuple[Frames, list[str]]: ...


def data_sources(as_of: date | None, mode: Mode) -> tuple[DataSource, ...]:
    suffix = "" if mode == "live" else " (committed demo extract)"
    return (
        DataSource(
            id="open-meteo-flood-glofas-v4",
            name="Open-Meteo Flood API: GloFAS v4 modeled river discharge (Copernicus EMS / "
            "ECMWF). Weather data by Open-Meteo.com" + suffix,
            license="CC BY 4.0",
            as_of=as_of,
        ),
        DataSource(
            id="open-meteo-archive-era5",
            name="Open-Meteo Historical Weather API: ERA5 reanalysis rainfall and temperature "
            "(Copernicus C3S)" + suffix,
            license="CC BY 4.0",
            as_of=as_of,
        ),
    )


class OracleService:
    def __init__(
        self,
        store: RunStore | None = None,
        demo_root: Path | None = None,
        model_dir: Path | None = None,
        live: LiveSource | None = None,
    ) -> None:
        self.store = store if store is not None else RunStore(os.environ.get(DB_ENV) or None)
        self.demo_root = demo_root
        self.model_dir = model_dir or Path(os.environ.get(MODELS_ENV) or DEFAULT_MODELS)
        self.live = live
        self._bundle: ModelBundle | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ resources
    def data(self) -> DemoData:
        try:
            return load_demo(self.demo_root)
        except DatasetError as exc:
            raise ToolFailure("INTERNAL", f"demo dataset unusable: {exc}") from exc

    def bundle(self) -> ModelBundle:
        with self._lock:
            if self._bundle is None:
                try:
                    self._bundle = ModelBundle.load(self.model_dir)
                except BundleError as exc:
                    raise ToolFailure("INTERNAL", f"model bundle refused: {exc}") from exc
            return self._bundle

    def model_info(self) -> ModelInfo:
        b = self.bundle()
        return ModelInfo(name=b.name, version=b.version, sha256=b.sha256)

    # ------------------------------------------------------------------ tools
    def forecast_river(self, params: ForecastRiverIn) -> Outcome[ForecastRiverOut]:
        demo = self.data()
        bundle = self.bundle()
        requested: Mode = params.mode or current_mode()
        mode: Mode = "demo"
        notes: list[str] = []
        frames = demo.frames
        if requested == "live" and params.as_of is not None and params.as_of <= demo.end:
            notes.append(
                "live mode was requested for an as_of inside the committed dataset; the demo "
                "data covers it, so it was used (mode demo)"
            )
        elif requested == "live":
            frames, mode, notes = self._live_frames(params.station_id, demo)
        if mode == "demo":
            notes.append(DEMO_NOTE.format(start=demo.start.isoformat(), end=demo.end.isoformat()))
        req = Request(params.station_id, params.horizon_days, params.as_of, params.coverage)
        try:
            res = forecast(req, frames, demo.catalog, bundle)
        except ForecastError as exc:
            raise ToolFailure(exc.code, exc.message, exc.retryable) from exc  # type: ignore[arg-type]
        out = _to_output(res)
        run_id = str(uuid.uuid4())
        extra = {
            "station_id": res.station.station_id,
            "as_of": res.as_of.isoformat(),
            "q_t": res.features.q_t,
            "features": [None if np.isnan(v) else float(v) for v in res.features.values],
            "bundle_sha256": bundle.sha256,
            "coverage": res.coverage,
            "mode": mode,
        }
        self.store.put(run_id, canonical_json(params), out.model_dump_json(), json.dumps(extra))
        return Outcome(
            out,
            warnings=[*notes, *res.warnings],
            data_sources=data_sources(max(frames.discharge["date"]), mode),
            model=self.model_info(),
            run_id=run_id,
            mode=mode,
        )

    def _live_frames(self, station_id: str, demo: DemoData) -> tuple[Frames, Mode, list[str]]:
        if self.live is None:
            reason = "live mode is not configured for the Oracle"
            return demo.frames, "demo", [MODE_FALLBACK_WARNING.format(reason=reason)]
        st = demo.catalog.get(station_id)
        ids = [station_id, *(st.upstream if st else ())]
        try:
            frames, notes = self.live.frames(ids, demo)
        except Exception as exc:  # any live failure falls back (ORA-R11.2)
            reason = str(exc) or type(exc).__name__
            return demo.frames, "demo", [MODE_FALLBACK_WARNING.format(reason=reason)]
        return frames, "live", notes

    def explain_forecast(self, params: ExplainForecastIn) -> Outcome[ExplainForecastOut]:
        stored = self.store.get(params.run_id)
        if stored is None:
            raise ToolFailure("NOT_FOUND", f"run_id {params.run_id!r} is unknown or expired")
        extra = json.loads(stored.extra_json)
        out_prev = ForecastRiverOut.model_validate_json(stored.output_json)
        bundle = self.bundle()
        if extra["bundle_sha256"] != bundle.sha256:
            raise ToolFailure(
                "NOT_FOUND",
                f"run_id {params.run_id!r} was produced by a different model bundle; rerun "
                "forecast_river",
            )
        demo = self.data()
        station = demo.catalog.get(extra["station_id"])
        if station is None:
            raise ToolFailure("NOT_FOUND", f"station of run {params.run_id!r} is unknown")
        x = np.array([np.nan if v is None else v for v in extra["features"]], dtype="float64")
        points = out_prev.forecast
        peak = max(points, key=lambda p: (p.discharge.p50, -p.lead_days))
        phi = bundle.contrib(x[None, :], peak.lead_days)[0]
        names = [
            demo.catalog.get(u).name  # type: ignore[union-attr]
            for u in station.upstream
            if demo.catalog.get(u) is not None
        ]
        expl = explain(phi, float(extra["q_t"]), FEATURES, names)
        text = narrative(
            station_label=station.label,
            peak_date=peak.date,
            peak_lead=peak.lead_days,
            p50=peak.discharge.p50,
            lo=peak.discharge.p10,
            hi=peak.discharge.p90,
            coverage=float(extra["coverage"]),
            expl=expl,
        )
        data = ExplainForecastOut(
            drivers=[
                Driver(
                    feature=d.feature,
                    contribution_m3s=d.contribution_m3s,
                    direction="up" if d.direction == "up" else "down",
                    feature_group=d.group,
                )
                for d in expl.drivers
            ],
            narrative=text,
            baseline_m3s=expl.baseline_m3s,
            lead_days_explained=peak.lead_days,
        )
        warnings = [
            f"contributions are TreeSHAP values of the median model at lead day "
            f"{peak.lead_days}, mapped to m3/s by log share; they sum to the model's raw median "
            f"({expl.raw_p50_m3s:,.0f} m3/s) minus the baseline",
        ]
        return Outcome(
            data,
            warnings=warnings,
            data_sources=data_sources(date.fromisoformat(extra["as_of"]), extra["mode"]),
            model=self.model_info(),
            mode=extra["mode"],
        )

    def stations(self) -> list[StationInfo]:
        demo = self.data()
        out = []
        for s in demo.catalog.stations:
            thr, method = s.threshold()
            out.append(
                StationInfo(
                    station_id=s.station_id,
                    name=s.label,
                    river=s.river,
                    role=s.role,
                    cell_lat=s.cell_lat,
                    cell_lon=s.cell_lon,
                    danger_threshold_m3s=None if thr is None else round(thr, 1),
                    threshold_method=method if thr is not None else None,
                    as_of_min=AS_OF_MIN,
                    as_of_max=demo.end,
                )
            )
        return out

    # ------------------------------------------------------------------ wiring
    def cores(self) -> dict[str, Callable[[Any], Any]]:
        return {
            "forecast_river": self.forecast_river,
            "explain_forecast": self.explain_forecast,
        }

    def health(self) -> dict[str, bool]:
        """Bundle loaded and hash-verified, dataset loaded, store writable (ORA-R6.2)."""
        try:
            self.bundle()
            bundle_ok = True
        except ToolFailure:
            bundle_ok = False
        try:
            self.data()
            data_ok = True
        except ToolFailure:
            data_ok = False
        return {"bundle": bundle_ok, "dataset": data_ok, "store": self.store.writable()}


def _to_output(res: ForecastResult) -> ForecastRiverOut:
    lo_q, hi_q = conformal.quantile_levels(res.coverage)
    s = res.station
    return ForecastRiverOut(
        station_id=s.station_id,
        unit="m3/s",
        as_of=res.as_of,
        target_kind=TARGET_KIND,
        target_label=TARGET_LABEL,
        forecast=[
            ForecastPoint(
                date=p.date, lead_days=p.lead, discharge=Interval(p10=p.lo, p50=p.p50, p90=p.hi)
            )
            for p in res.points
        ],
        danger_threshold_m3s=res.threshold_m3s,
        exceedance_prob=[ExceedancePoint(date=d, p_exceed=p) for d, p in res.exceedance],
        calibration=Calibration(
            method="split_conformal",
            nominal_coverage=res.coverage,
            n_calibration=res.n_calibration,
            interval_lower_q=lo_q,
            interval_upper_q=hi_q,
        ),
        station=Station(
            name=s.label,
            river=s.river,
            cell_lat=s.cell_lat,
            cell_lon=s.cell_lon,
            requested_lat=s.requested_lat,
            requested_lon=s.requested_lon,
        ),
        quantile_correction_applied=res.any_repair,
    )


__all__ = ["OracleService", "peak_lead"]
