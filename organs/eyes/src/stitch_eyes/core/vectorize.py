"""Raster to GeoJSON polygons (design 8, EYE-P2, EYE-X4).

1. Classes: 1 = new flood with high confidence (p >= threshold), 2 = new flood, low confidence.
2. 4-connected components per class; one polygon (with holes) per component.
3. Drop components under ``min_polygon_km2`` (dropped area reported); cap the feature count by
   raising the minimum adaptively.
4. Simplify (``preserve_topology``), repair with ``make_valid`` (polygonal parts only),
   transform to WGS84, round to 5 decimals, repair again.
5. Properties: ``class``, ``confidence_class``, ``area_km2`` (raster area), ``mean_confidence``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

DECIMALS = 5


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


def _round_coords(geom: Any) -> Any:
    from shapely import set_precision

    return set_precision(geom, 10.0**-DECIMALS)


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
    from pyproj import Transformer
    from rasterio.features import shapes
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as shp_transform

    flood = np.asarray(new_flood, dtype=bool)
    high = flood & (prob >= low_conf_threshold)
    low = flood & ~high
    comps: list[tuple[str, npt.NDArray[np.int32], int]] = []
    for cls_name, m in (("high", high), ("low", low)):
        lab, n = _label4(m)
        comps.append((cls_name, lab, n))

    area_px = np.broadcast_to(col_area_m2[None, :], flood.shape)
    infos: list[tuple[float, str, int, npt.NDArray[np.int32], float]] = []
    for cls_name, lab, n in comps:
        if n == 0:
            continue
        flat = lab.ravel()
        areas = np.bincount(flat, weights=area_px.ravel(), minlength=n + 1) / 1e6
        conf_sum = np.bincount(flat, weights=confidence.ravel(), minlength=n + 1)
        cnt = np.bincount(flat, minlength=n + 1)
        for k in range(1, n + 1):
            infos.append((float(areas[k]), cls_name, k, lab, float(conf_sum[k] / cnt[k])))

    warnings: list[str] = []
    threshold = min_polygon_km2
    kept = [i for i in infos if i[0] >= threshold]
    if len(kept) > max_features:
        kept.sort(key=lambda i: -i[0])
        threshold = kept[max_features - 1][0]
        kept = [i for i in kept if i[0] >= threshold][:max_features]
        warnings.append(
            f"feature cap {max_features} reached: minimum polygon area raised to "
            f"{threshold:.4f} km2"
        )
    dropped = sum(i[0] for i in infos) - sum(i[0] for i in kept)
    if dropped > 0:
        warnings.append(
            f"{dropped:.3f} km2 of flood in polygons under {threshold:.4f} km2 is not drawn "
            "(it is counted in flood_extent_km2)"
        )

    keep_ids: dict[str, set[int]] = {"high": set(), "low": set()}
    meta: dict[tuple[str, int], tuple[float, float]] = {}
    for area, cls_name, k, _lab, conf in kept:
        keep_ids[cls_name].add(k)
        meta[(cls_name, k)] = (area, conf)

    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    features: list[dict[str, Any]] = []
    for cls_name, lab, n in comps:
        if n == 0 or not keep_ids[cls_name]:
            continue
        sel = np.isin(lab, np.fromiter(keep_ids[cls_name], dtype=np.int32))
        for geom_json, value in shapes(lab, mask=sel, connectivity=4, transform=transform):
            k = int(value)
            geom = shape(geom_json)
            if simplify_m > 0:
                geom = geom.simplify(simplify_m, preserve_topology=True)
            geom = _polygonal(geom)
            if geom.is_empty:
                continue
            geom = _polygonal(_round_coords(shp_transform(to_wgs.transform, geom)))
            if geom.is_empty:
                continue
            area, conf = meta[(cls_name, k)]
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": {
                        "class": "new_flood",
                        "confidence_class": cls_name,
                        "area_km2": round(area, 6),
                        "mean_confidence": round(conf, 4),
                    },
                }
            )
    features.sort(key=lambda f: (-f["properties"]["area_km2"], f["properties"]["confidence_class"]))
    return VectorResult(
        {"type": "FeatureCollection", "features": features},
        len(features),
        max(dropped, 0.0),
        threshold,
        warnings,
    )
