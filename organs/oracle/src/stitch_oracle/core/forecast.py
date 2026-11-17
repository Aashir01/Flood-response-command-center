"""Forecast pipeline (design section 5, steps 1 to 5). Pure: history, catalog and model in,
``ForecastResult`` out. Deterministic for a given (station, as_of, data snapshot) (ORA-P4).

Discharge here is always **modeled** GloFAS discharge (via Open-Meteo).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from stitch_oracle.core import conformal, ood
from stitch_oracle.core.bundle import QuantileModel
from stitch_oracle.core.exceedance import Cdf
from stitch_oracle.core.features import FEATURES, FeatureRow, Frames, row_from_wide, to_wide
from stitch_oracle.core.gaps import GapError, fill_window
from stitch_oracle.core.quantiles import repair
from stitch_oracle.core.splits import AS_OF_MIN
from stitch_oracle.core.stations import THRESHOLD_MODELED, Catalog, Station

MAX_HORIZON = 14
#: Target-space clip before the back-transform, so absurd model outputs stay finite (ORA-P2).
Y_CLIP = 50.0
DECIMALS = 3


class ForecastError(Exception):
    """An expected failure, mapped to a ``ToolFailure`` code by the service."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class Request:
    station_id: str
    horizon_days: int
    as_of: date | None = None
    coverage: float = conformal.DEFAULT_COVERAGE


@dataclass(frozen=True)
class LeadForecast:
    date: date
    lead: int
    lo: float  # lower interval bound at the requested coverage, m3/s
    p50: float
    hi: float
    lo80: float  # 0.8-calibrated bounds, used for exceedance
    hi80: float
    repaired: bool


@dataclass(frozen=True)
class ForecastResult:
    station: Station
    as_of: date
    coverage: float
    points: tuple[LeadForecast, ...]
    exceedance: tuple[tuple[date, float], ...]
    threshold_m3s: float | None
    threshold_method: str | None
    n_calibration: int
    features: FeatureRow
    raw: np.ndarray  # (H, 3) raw quantiles in target space
    warnings: tuple[str, ...]

    @property
    def any_repair(self) -> bool:
        return any(p.repaired for p in self.points)


def back_transform(y: np.ndarray, q_t: float) -> np.ndarray:
    """``Q = (Q_t + 1) exp(y) - 1``, clipped at 0. Monotone in ``y``."""
    yc = np.clip(np.asarray(y, dtype="float64"), -Y_CLIP, Y_CLIP)
    out: np.ndarray = np.maximum((max(q_t, 0.0) + 1.0) * np.exp(yc) - 1.0, 0.0)
    return out


def calibrate_batch(raw: np.ndarray, q_t: np.ndarray, q_hat: np.ndarray) -> np.ndarray:
    """Vectorised steps 4a to 4d of the pipeline for many rows of one lead (used by the eval):
    repair, CQR interval with ``q_hat`` per row, final sort, back-transform. ``raw`` has shape
    ``(n, 3)`` in target space; returns ``(n, 3)`` discharge ``(lo, p50, hi)`` in m3/s, unrounded.
    Equal to ``forecast`` before its rounding (tested)."""
    rep, _ = repair(np.asarray(raw, dtype="float64"))
    lo, hi = conformal.interval(rep[:, 0], rep[:, 1], rep[:, 2], np.asarray(q_hat, "float64"))
    ys = np.sort(np.stack([lo, rep[:, 1], hi], axis=1), axis=1)
    a = np.maximum(np.asarray(q_t, dtype="float64"), 0.0)[:, None] + 1.0
    out: np.ndarray = np.maximum(a * np.exp(np.clip(ys, -Y_CLIP, Y_CLIP)) - 1.0, 0.0)
    return out


def data_end(frames: Frames) -> date:
    return max(frames.discharge["date"])  # type: ignore[no-any-return]


def validate(req: Request, catalog: Catalog, last: date) -> tuple[Station, date, list[str]]:
    notes: list[str] = []
    if not 1 <= req.horizon_days <= MAX_HORIZON:
        raise ForecastError("INVALID_INPUT", f"horizon_days must be 1 to {MAX_HORIZON}")
    if not (conformal.COVERAGE_MIN <= req.coverage <= conformal.COVERAGE_MAX):
        raise ForecastError(
            "INVALID_INPUT",
            f"coverage must be between {conformal.COVERAGE_MIN} and {conformal.COVERAGE_MAX}",
        )
    station = catalog.get(req.station_id)
    if station is None:
        near = ", ".join(catalog.nearby(req.station_id))
        raise ForecastError(
            "NOT_FOUND", f"unknown station_id {req.station_id!r}; nearby stations: {near}"
        )
    if not station.forecastable:
        near = ", ".join(catalog.nearby(req.station_id))
        raise ForecastError(
            "INVALID_INPUT",
            f"{req.station_id} is a feature-only station (not forecast); try: {near}",
        )
    as_of = req.as_of
    if as_of is None:
        as_of = last
        notes.append(f"as_of not given; used the last date in the dataset, {last.isoformat()}")
    if as_of < AS_OF_MIN:
        raise ForecastError(
            "INVALID_INPUT",
            f"as_of {as_of.isoformat()} is before the model's calibration cutoff "
            f"({AS_OF_MIN.isoformat()}); a forecast would use calibration data dated after as_of",
        )
    if as_of > last:
        raise ForecastError(
            "INVALID_INPUT",
            f"as_of {as_of.isoformat()} is after the last date in the data ({last.isoformat()})",
        )
    return station, as_of, notes


def forecast(
    req: Request, frames: Frames, catalog: Catalog, model: QuantileModel
) -> ForecastResult:
    last = data_end(frames)
    station, as_of, warnings = validate(req, catalog, last)
    h_max = req.horizon_days
    leads = tuple(range(1, h_max + 1))
    if tuple(model.leads[:h_max]) != leads:
        raise ForecastError("INTERNAL", "model bundle does not cover the requested leads")

    # 2. history, sliced to <= as_of, gap rules on the feature window
    needed = [station.station_id, *(u for u in station.upstream if catalog.get(u) is not None)]
    try:
        wide, gaps = fill_window(to_wide(frames.until(as_of)), as_of, needed)
    except GapError as exc:
        raise ForecastError("UPSTREAM_UNAVAILABLE", str(exc), retryable=True) from exc
    except (ValueError, KeyError) as exc:
        raise ForecastError(
            "UPSTREAM_UNAVAILABLE", f"no usable history before {as_of.isoformat()}", True
        ) from exc
    gap_note = gaps.warning()
    if gap_note:
        warnings.append(gap_note)

    # 3. features and the out-of-range check
    row = row_from_wide(wide, station, as_of, catalog, dict(model.station_codes))
    flagged = ood.out_of_range(FEATURES, list(row.values), model.feature_ranges)
    ood_note = ood.warning(flagged)
    if ood_note:
        warnings.append(ood_note)

    # 4. raw quantiles, repair, CQR, back-transform
    raw = np.asarray(model.predict(row.values[None, :])[0, :h_max, :], dtype="float64")
    if not np.all(np.isfinite(raw)):
        raise ForecastError("INTERNAL", "model produced a non-finite prediction")
    rep, flags = repair(raw)
    small: list[int] = []
    capped: list[int] = []
    points: list[LeadForecast] = []
    for j, h in enumerate(leads):
        qh = model.conformity.lookup(station.station_id, h, req.coverage)
        q80 = model.conformity.lookup(station.station_id, h, conformal.DEFAULT_COVERAGE)
        if qh.pooled:
            small.append(h)
        if qh.k_exceeds_n:
            capped.append(h)
        q10, q50, q90 = rep[j]
        lo, hi = conformal.interval(
            np.array([q10]), np.array([q50]), np.array([q90]), np.array([qh.value])
        )
        lo8, hi8 = conformal.interval(
            np.array([q10]), np.array([q50]), np.array([q90]), np.array([q80.value])
        )
        ys = np.sort(np.array([lo[0], q50, hi[0]]))  # final monotone guarantee
        vals = np.round(back_transform(ys, row.q_t), DECIMALS)
        v80 = np.round(back_transform(np.array([lo8[0], q50, hi8[0]]), row.q_t), DECIMALS)
        points.append(
            LeadForecast(
                date=as_of + timedelta(days=h),
                lead=h,
                lo=float(vals[0]),
                p50=float(vals[1]),
                hi=float(vals[2]),
                lo80=float(min(v80[0], vals[1])),
                hi80=float(max(v80[2], vals[1])),
                repaired=bool(flags[j]),
            )
        )
    k = int(np.sum(flags))
    if k:
        warnings.append(f"quantile crossing repaired on {k} of {h_max} lead days")
    if small:
        n_min = min(model.conformity.n(station.station_id, h) for h in small)
        warnings.append(
            f"calibration set below {model.conformity.min_cal} points (min n={n_min}) on lead "
            f"days {_days(small)}; pooled scores of all stations were used and the interval was "
            "widened"
        )
    if capped:
        warnings.append(
            f"coverage {req.coverage:g} needs more calibration points than available on lead "
            f"days {_days(capped)}; the largest score was used"
        )

    # 5. exceedance against the danger threshold
    threshold, method = station.threshold()
    exceed: list[tuple[date, float]] = []
    if threshold is not None:
        tails = 0
        for p in points:
            cdf = Cdf.from_quantiles(p.lo80, p.p50, p.hi80)
            exceed.append((p.date, round(cdf.p_exceed(threshold), 6)))
            tails += cdf.in_tail(threshold)
        if method == THRESHOLD_MODELED:
            warnings.append(
                "danger threshold is the modeled 5-year return level of the GloFAS series "
                "(1997-2016); an assumption, not an official warning level"
            )
        if tails:
            warnings.append(
                f"the danger threshold lies outside the 80% band on {tails} of {h_max} lead days; "
                "exceedance there uses extrapolated tails (approximate)"
            )
    if station.note:
        warnings.append(station.note)
    mid = leads[(len(leads) - 1) // 2]
    n_cal = model.conformity.n(station.station_id, mid)
    return ForecastResult(
        station=station,
        as_of=as_of,
        coverage=req.coverage,
        points=tuple(points),
        exceedance=tuple(exceed),
        threshold_m3s=None if threshold is None else round(threshold, 1),
        threshold_method=method if threshold is not None else None,
        n_calibration=n_cal,
        features=row,
        raw=raw,
        warnings=tuple(warnings),
    )


def _days(leads: list[int]) -> str:
    return ", ".join(str(h) for h in leads)


def peak_lead(points: tuple[LeadForecast, ...]) -> LeadForecast:
    """The lead with the largest median; ties go to the earliest."""
    best = points[0]
    for p in points[1:]:
        if p.p50 > best.p50:
            best = p
    return best
