"""District id raster and per-district aggregation (design 7.1).

Boundaries are rasterized onto the window grid into an int32 index raster (``-1`` outside any
district). Overlaps resolve to the smallest ``district_id`` (shapes are burned in descending id
order, so the smallest is written last). Every in-region pixel belongs to exactly one district
(EYE-X8), so the district sums of new flood equal ``new_flood_km2`` up to float rounding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

I32 = npt.NDArray[np.int32]


@dataclass(frozen=True)
class District:
    district_id: str
    name: str
    geometry: Mapping[str, Any]  # GeoJSON geometry in WGS84


@dataclass(frozen=True)
class DistrictStat:
    district_id: str
    name: str
    flooded_km2: float
    district_area_km2: float

    @property
    def flooded_fraction(self) -> float:
        if self.district_area_km2 <= 0:
            return 0.0
        return min(max(self.flooded_km2 / self.district_area_km2, 0.0), 1.0)


def rasterize_districts(
    districts: Sequence[District],
    crs: str,
    transform: Any,
    shape: tuple[int, int],
) -> tuple[I32, list[District]]:
    """Index raster into the returned list of districts sorted by id; -1 means none."""
    import shapely
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely.geometry import mapping
    from shapely.geometry import shape as to_shape

    ordered = sorted(districts, key=lambda d: d.district_id)
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    def _xy(c: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        x, y = tr.transform(c[:, 0], c[:, 1])
        return np.column_stack([x, y])

    shapes = []
    for idx in range(len(ordered) - 1, -1, -1):  # descending id: smallest written last
        geom = shapely.transform(to_shape(ordered[idx].geometry), _xy)
        if not geom.is_empty:
            shapes.append((mapping(geom), idx))
    if not shapes:
        return np.full(shape, -1, np.int32), ordered
    raster = rasterize(
        shapes, out_shape=shape, transform=transform, fill=-1, dtype="int32", all_touched=False
    )
    return np.asarray(raster, dtype=np.int32), ordered


def aggregate(
    index: I32,
    ordered: Sequence[District],
    new_flood: npt.ArrayLike,
    col_area_m2: npt.NDArray[np.float64],
) -> list[DistrictStat]:
    """Per-district new-flood and in-window district areas; districts without pixels omitted.

    Sorted by ``flooded_km2`` descending, then ``district_id``.
    """
    flood = np.asarray(new_flood, dtype=bool)
    n = len(ordered)
    area_px = np.broadcast_to(col_area_m2[None, :], index.shape)
    inside = index >= 0
    idx = index[inside]
    dist_area = np.bincount(idx, weights=area_px[inside], minlength=n)
    flood_in = inside & flood
    flood_area = np.bincount(index[flood_in], weights=area_px[flood_in], minlength=n)
    counts = np.bincount(idx, minlength=n)
    stats = [
        DistrictStat(
            ordered[i].district_id,
            ordered[i].name,
            float(flood_area[i]) / 1e6,
            float(dist_area[i]) / 1e6,
        )
        for i in range(n)
        if counts[i] > 0
    ]
    return sorted(stats, key=lambda s: (-s.flooded_km2, s.district_id))
