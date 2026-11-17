"""Raster to GeoJSON polygons (design 8, EYE-P2, EYE-X4).

1. Classes: new flood with high confidence (``p >= low_conf_threshold``) and new flood with low
   confidence.
2. 4-connected components per class (SciPy labelling); one polygon, with holes, per component.
3. Components under ``min_polygon_km2`` are not drawn (their area is reported in a warning and
   still counted in the km2 numbers). The feature count is capped by raising the minimum.
4. All polygons are simplified together as one coverage (``shapely.coverage_simplify``), so
   neighbouring high and low confidence polygons keep shared edges and no gaps or overlaps
   appear. This is about 10x faster than ``simplify(preserve_topology=True)`` on the demo scene,
   where one polygon has 145,000 vertices and 6,400 holes.
5. Transform to WGS84, snap to a 1e-5 degree grid with ``set_precision`` (which returns valid
   geometry), keep polygonal parts only.
6. Properties: ``class``, ``confidence_class``, ``area_km2`` (raster area of the component) and
   ``mean_confidence``. Features are sorted by area (descending), then class, then component id.

Everything here is deterministic: labelling, ``shapes`` and the GEOS calls depend only on the
mask, not on any processing order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

DECIMALS = 5
GRID_DEG = 10.0**-DECIMALS


@dataclass
class VectorResult:
    feature_collection: dict[str, Any]
    n_features: int
    dropped_km2: float
    min_polygon_km2: float
    warnings: list[str] = field(default_factory=list)


def _label4(mask: npt.NDArray[np.bool_]) -> tuple[npt.NDArray[np.int32], int]:
    from scipy import ndimage

    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
    lab, n = ndimage.label(mask, structure=structure)
    return np.asarray(lab, dtype=np.int32), int(n)


def _polygonal(geom: Any) -> Any:
    """Polygonal part of a geometry (repairing it first if needed); empty Polygon if none."""
    from shapely import make_valid
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    g = geom if geom.is_valid else make_valid(geom)
    if isinstance(g, Polygon | MultiPolygon):
        return g
    if isinstance(g, GeometryCollection):
        polys: list[Polygon] = []
        for part in g.geoms:
            if isinstance(part, Polygon):
                polys.append(part)
            elif isinstance(part, MultiPolygon):
                polys.extend(part.geoms)
        return MultiPolygon(polys) if polys else Polygon()
    return Polygon()


def components(
    new_flood: npt.ArrayLike, prob: npt.NDArray[np.float64], low_conf_threshold: float
) -> tuple[npt.NDArray[np.int32], int, int]:
    """Component id raster (0 = none; 1..n_high high confidence, then low), n_high, n_total."""
    flood = np.asarray(new_flood, dtype=bool)
    high = flood & (prob >= low_conf_threshold)
    low = flood & ~high
    lab_h, n_h = _label4(high)
    lab_l, n_l = _label4(low)
    comp = np.where(high, lab_h, np.where(low, lab_l + n_h, 0)).astype(np.int32)
    return comp, n_h, n_h + n_l


def vectorize(
    new_flood: npt.ArrayLike,
    prob: npt.NDArray[np.float64],
    confidence: npt.NDArray[np.float64],
    transform: Any,
    crs: str,
    col_area_m2: npt.NDArray[np.float64],
    low_conf_threshold: float = 0.75,
    min_polygon_km2: float = 0.005,
    simplify_m: float = 15.0,
    max_features: int = 3000,
) -> VectorResult:
    import shapely
    from pyproj import Transformer
    from rasterio.features import shapes
    from shapely.geometry import mapping, shape

    comp, n_high, n = components(new_flood, prob, low_conf_threshold)
    empty: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    if n == 0:
        return VectorResult(empty, 0, 0.0, min_polygon_km2, [])

    flat = comp.ravel()
    area_px = np.broadcast_to(col_area_m2[None, :], comp.shape).ravel()
    areas = np.bincount(flat, weights=area_px, minlength=n + 1)[1:] / 1e6
    conf_sum = np.bincount(flat, weights=np.asarray(confidence).ravel(), minlength=n + 1)[1:]
    counts = np.bincount(flat, minlength=n + 1)[1:]
    mean_conf = conf_sum / np.maximum(counts, 1)

    warnings: list[str] = []
    threshold = min_polygon_km2
    keep = areas >= threshold
    if int(keep.sum()) > max_features:
        order = np.lexsort((np.arange(n), -areas))  # area descending, then id
        top = order[:max_features]
        threshold = float(areas[top[-1]])
        keep = np.zeros(n, dtype=bool)
        keep[top] = True
        warnings.append(
            f"feature cap {max_features} reached: minimum polygon area raised to "
            f"{threshold:.4f} km2"
        )
    dropped = float(areas[~keep].sum())
    if dropped > 0:
        warnings.append(
            f"{dropped:.3f} km2 of flood in polygons under {threshold:.4f} km2 is not drawn "
            "(it is counted in flood_extent_km2)"
        )
    if not keep.any():
        return VectorResult(empty, 0, dropped, threshold, warnings)

    lookup = np.concatenate([[False], keep])
    sel = lookup[comp]
    geoms: list[Any] = []
    ids: list[int] = []
    for geom_json, value in shapes(comp, mask=sel, connectivity=4, transform=transform):
        geoms.append(shape(geom_json))
        ids.append(int(value))
    arr = np.array(geoms, dtype=object)
    if simplify_m > 0:
        arr = shapely.coverage_simplify(arr, simplify_m)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def _xy(coords: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        lon, lat = to_wgs.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([lon, lat])

    arr = shapely.transform(arr, _xy)
    arr = shapely.set_precision(arr, GRID_DEG)

    features: list[tuple[tuple[float, int, int], dict[str, Any]]] = []
    for geom, cid in zip(arr, ids, strict=True):
        g = _polygonal(geom)
        if g.is_empty:
            continue
        k = cid - 1
        cls_name = "high" if cid <= n_high else "low"
        area = float(areas[k])
        features.append(
            (
                (-area, 0 if cls_name == "high" else 1, cid),
                {
                    "type": "Feature",
                    "geometry": mapping(g),
                    "properties": {
                        "class": "new_flood",
                        "confidence_class": cls_name,
                        "area_km2": round(area, 6),
                        "mean_confidence": round(float(mean_conf[k]), 4),
                    },
                },
            )
        )
    features.sort(key=lambda kv: kv[0])
    fc = {"type": "FeatureCollection", "features": [f for _, f in features]}
    return VectorResult(fc, len(features), dropped, threshold, warnings)
