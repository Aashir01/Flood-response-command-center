"""Station catalog (design section 3.1). A station is a named place snapped to a GloFAS grid cell.
It is never a physical gauge: every label reads "GloFAS grid cell nearest to <name>"."""

from __future__ import annotations

import difflib
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

THRESHOLD_MODELED = "modeled_5yr_return_level"
THRESHOLD_PUBLISHED = "published"
CUSEC_M3S = 0.0283168


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str
    river: str
    requested_lat: float
    requested_lon: float
    cell_lat: float
    cell_lon: float
    role: str  # "forecast" or "feature"
    upstream: tuple[str, ...] = ()
    danger_threshold_m3s: float | None = None
    threshold_method: str | None = None
    published_warning_cusecs: float | None = None
    note: str = ""

    @property
    def label(self) -> str:
        return f"GloFAS grid cell nearest to {self.name}"

    @property
    def forecastable(self) -> bool:
        return "forecast" in self.role

    def threshold(self) -> tuple[float | None, str | None]:
        """Danger threshold in m3/s and its method. A published level takes precedence."""
        if self.published_warning_cusecs is not None:
            return self.published_warning_cusecs * CUSEC_M3S, THRESHOLD_PUBLISHED
        return self.danger_threshold_m3s, self.threshold_method

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> Station:
        cusecs = d.get("published_warning_cusecs")
        thr = d.get("danger_threshold_m3s")
        return Station(
            station_id=str(d["station_id"]),
            name=str(d["name"]),
            river=str(d["river"]),
            requested_lat=float(d["requested_lat"]),
            requested_lon=float(d["requested_lon"]),
            cell_lat=float(d["cell_lat"]),
            cell_lon=float(d["cell_lon"]),
            role=str(d["role"]),
            upstream=tuple(str(u) for u in d.get("upstream", ())),
            danger_threshold_m3s=None if thr is None else float(thr),
            threshold_method=d.get("threshold_method"),
            published_warning_cusecs=None if cusecs is None else float(cusecs),
            note=str(d.get("note", "")),
        )


@dataclass(frozen=True)
class Catalog:
    stations: tuple[Station, ...]

    def __post_init__(self) -> None:
        ids = [s.station_id for s in self.stations]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate station_id in catalog")
        known = set(ids)
        for s in self.stations:
            missing = [u for u in s.upstream if u not in known]
            if missing:
                raise ValueError(f"{s.station_id}: unknown upstream {missing}")

    def get(self, station_id: str) -> Station | None:
        for s in self.stations:
            if s.station_id == station_id:
                return s
        return None

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(s.station_id for s in self.stations)

    @property
    def forecast_ids(self) -> tuple[str, ...]:
        return tuple(sorted(s.station_id for s in self.stations if s.forecastable))

    def nearby(self, station_id: str, k: int = 3) -> list[str]:
        """Up to ``k`` forecast station ids close to an unknown id: by name similarity, then (for
        a known feature-only station) by grid-cell distance."""
        pool = list(self.forecast_ids)
        known = self.get(station_id)
        if known is not None:
            return sorted(
                pool,
                key=lambda sid: _dist(known, self.get(sid)),  # type: ignore[arg-type]
            )[:k]
        close = difflib.get_close_matches(station_id.lower(), pool, n=k, cutoff=0.0)
        return close or pool[:k]


def _dist(a: Station, b: Station) -> float:
    return math.hypot(a.cell_lat - b.cell_lat, a.cell_lon - b.cell_lon)


def catalog_from_dicts(items: Iterable[Mapping[str, Any]]) -> Catalog:
    return Catalog(tuple(Station.from_dict(d) for d in items))
