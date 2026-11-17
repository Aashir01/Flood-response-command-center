"""Committed demo data: scene catalog, COG window reads, permanent water, districts, overlay.

Reads only files under ``data/demo`` (no network). ``catalog.json`` lists each scene with its
file, SHA-256, CRS, UTM bounds, shape, acquisition time and permanent-water file.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from stitch_eyes.core.districts import District


class SceneNotFound(LookupError):
    def __init__(self, message: str, nearest: list[date]) -> None:
        super().__init__(message)
        self.nearest = nearest


class WindowError(ValueError):
    """bbox does not intersect the scene (``kind='not_found'``) or is too large."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Scene:
    region_id: str
    scene_id: str
    date: date
    acquired: datetime
    sensor: str
    path: Path
    sha256: str
    crs: str
    res: float
    bounds_utm: tuple[float, float, float, float]
    shape: tuple[int, int]
    validated_region: bool
    perm_path: Path | None
    license: str
    attribution: str
    source_name: str

    @property
    def x0(self) -> float:
        return self.bounds_utm[0]

    @property
    def y1(self) -> float:
        return self.bounds_utm[3]


@dataclass(frozen=True)
class Window:
    row0: int
    col0: int
    height: int
    width: int

    def transform(self, scene: Scene) -> Any:
        from rasterio.transform import from_origin

        return from_origin(
            scene.x0 + self.col0 * scene.res, scene.y1 - self.row0 * scene.res, scene.res, scene.res
        )

    @property
    def key(self) -> tuple[int, int, int, int]:
        return (self.row0, self.col0, self.height, self.width)


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Catalog:
    def __init__(self, eyes_dir: Path) -> None:
        self.eyes_dir = eyes_dir
        raw = json.loads((eyes_dir / "catalog.json").read_text(encoding="utf-8"))
        self.scenes: list[Scene] = []
        for s in raw["scenes"]:
            perm = s.get("perm_water", {}).get("file")
            self.scenes.append(
                Scene(
                    region_id=s["region_id"],
                    scene_id=s["scene_id"],
                    date=date.fromisoformat(s["date"]),
                    acquired=_parse_dt(s["acquired"]),
                    sensor=s["sensor"],
                    path=eyes_dir / s["file"],
                    sha256=s["sha256"],
                    crs=s["crs"],
                    res=float(s["resolution_m"]),
                    bounds_utm=tuple(s["bounds_utm"]),  # type: ignore[arg-type]
                    shape=tuple(s["shape"]),  # type: ignore[arg-type]
                    validated_region=bool(s.get("validated_region", False)),
                    perm_path=(eyes_dir / perm) if perm else None,
                    license=s["license"],
                    attribution=s["attribution"],
                    source_name=s["source"]["provider"],
                )
            )
        self.scenes.sort(key=lambda sc: (sc.region_id, sc.date, sc.scene_id))

    def find(self, region_id: str, when: date, tolerance_days: int) -> tuple[Scene, int]:
        """Scene for the region nearest to ``when`` within the tolerance; returns (scene, days).

        Raises ``SceneNotFound`` with up to 3 nearest dates (ordered by distance) otherwise.
        """
        cands = [s for s in self.scenes if s.region_id == region_id]
        if not cands:
            regions = sorted({s.region_id for s in self.scenes})
            raise SceneNotFound(f"no scene for region '{region_id}' (available: {regions})", [])
        ranked = sorted(cands, key=lambda s: (abs((s.date - when).days), s.date))
        best = ranked[0]
        diff = abs((best.date - when).days)
        if diff <= tolerance_days:
            return best, diff
        nearest = []
        for s in ranked:
            if s.date not in nearest:
                nearest.append(s.date)
        raise SceneNotFound(
            f"no scene for '{region_id}' on {when.isoformat()}; nearest available dates: "
            + ", ".join(d.isoformat() for d in nearest[:3]),
            nearest[:3],
        )


def full_window(scene: Scene) -> Window:
    return Window(0, 0, scene.shape[0], scene.shape[1])


def window_for_bbox(
    scene: Scene, bbox: tuple[float, float, float, float], max_area_km2: float
) -> Window:
    """Pixel window covering ``bbox`` (WGS84) clipped to the scene."""
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", scene.crs, always_xy=True)
    xmin, ymin, xmax, ymax = tr.transform_bounds(*bbox, densify_pts=21)
    sx0, sy0, sx1, sy1 = scene.bounds_utm
    ix0, iy0, ix1, iy1 = max(xmin, sx0), max(ymin, sy0), min(xmax, sx1), min(ymax, sy1)
    if ix0 >= ix1 or iy0 >= iy1:
        raise WindowError("bbox does not intersect the scene", "not_found")
    col0 = max(math.floor((ix0 - sx0) / scene.res), 0)
    col1 = min(math.ceil((ix1 - sx0) / scene.res), scene.shape[1])
    row0 = max(math.floor((sy1 - iy1) / scene.res), 0)
    row1 = min(math.ceil((sy1 - iy0) / scene.res), scene.shape[0])
    if col1 <= col0 or row1 <= row0:
        raise WindowError("bbox does not intersect the scene", "not_found")
    area = (col1 - col0) * (row1 - row0) * scene.res**2 / 1e6
    if area > max_area_km2:
        raise WindowError(
            f"window area {area:.0f} km2 exceeds the maximum {max_area_km2:.0f} km2", "too_large"
        )
    return Window(row0, col0, row1 - row0, col1 - col0)


def read_codes(scene: Scene, win: Window) -> npt.NDArray[np.uint8]:
    import rasterio
    from rasterio.windows import Window as RWindow

    with rasterio.open(scene.path) as src:
        arr = src.read(window=RWindow(win.col0, win.row0, win.width, win.height))
    return np.asarray(arr, dtype=np.uint8)


def read_perm(scene: Scene, win: Window) -> npt.NDArray[np.bool_]:
    if scene.perm_path is None or not scene.perm_path.exists():
        return np.zeros((win.height, win.width), dtype=bool)
    import rasterio
    from rasterio.windows import Window as RWindow

    with rasterio.open(scene.perm_path) as src:
        arr = src.read(1, window=RWindow(win.col0, win.row0, win.width, win.height))
    return np.asarray(arr) > 0


def load_districts(path: Path) -> list[District]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for f in raw["features"]:
        p = f["properties"]
        out.append(District(str(p["district_id"]), str(p["name"]), f["geometry"]))
    return out


def load_overlay(eyes_dir: Path, region_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Reference extent and its note, or (None, None) when no redistributable file exists."""
    path = eyes_dir / f"reference_extent_{region_id}.geojson"
    if not path.exists():
        return None, None
    fc = json.loads(path.read_text(encoding="utf-8"))
    meta = fc.get("properties") or (fc["features"][0]["properties"] if fc["features"] else {})
    note = (
        f"Reference extent: {meta.get('source', 'unknown source')}, product "
        f"{meta.get('product_id', '?')} dated {meta.get('product_date', '?')}, licence "
        f"{meta.get('license', '?')}. Qualitative only; not the same date as the scene."
    )
    clean = {"type": "FeatureCollection", "features": fc["features"]}
    return clean, note
