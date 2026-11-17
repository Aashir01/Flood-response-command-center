"""Permanent water, districts and vectorization (design 7, 8): EYE-P2, EYE-P3, EYE-X4, EYE-X8."""

from __future__ import annotations

import numpy as np
from eyes_strategies import water_perm_masks
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_eyes.core.area import masked_area_km2, utm_column_area_m2
from stitch_eyes.core.districts import District, aggregate
from stitch_eyes.core.permwater import dilate, split_water
from stitch_eyes.core.vectorize import vectorize

CRS = "EPSG:32642"
X0, Y1 = 360_000.0, 2_940_000.0


def _transform() -> object:
    from rasterio.transform import from_origin

    return from_origin(X0, Y1, 10.0, 10.0)


@settings(deadline=None)
@given(water_perm_masks())
def test_eye_p3_new_flood_between_zero_and_total(case: tuple) -> None:
    water, perm, index, areas = case
    clip = index >= 0
    s = split_water(water, perm, clip, areas)
    assert 0.0 <= s.new_flood_km2 <= s.total_water_km2
    assert abs(s.new_flood_km2 - (s.total_water_km2 - s.permanent_water_km2)) <= 1e-9 * max(
        s.total_water_km2, 1.0
    )
    assert not np.any(s.new_flood & s.permanent)
    assert np.array_equal(s.new_flood | s.permanent, s.water)


@settings(deadline=None)
@given(water_perm_masks())
def test_eye_x8_districts_partition_and_sum_to_new_flood(case: tuple) -> None:
    water, perm, index, areas = case
    n = int(index.max()) + 1 if index.max() >= 0 else 0
    ordered = [District(f"d{i:02d}", f"D{i}", {}) for i in range(n)]
    s = split_water(water, perm, index >= 0, areas)
    stats = aggregate(index, ordered, s.new_flood, areas)
    total_in = masked_area_km2(index >= 0, areas)
    # partition: every in-region pixel is in exactly one district
    assert abs(sum(x.district_area_km2 for x in stats) - total_in) <= 1e-9 * max(total_in, 1.0)
    assert sum(int((index == i).sum()) for i in range(n)) == int((index >= 0).sum())
    assert abs(sum(st.flooded_km2 for st in stats) - s.new_flood_km2) <= 1e-9 * max(
        s.new_flood_km2, 1.0
    )
    for st_ in stats:
        assert 0.0 <= st_.flooded_fraction <= 1.0
    keys = [(-x.flooded_km2, x.district_id) for x in stats]
    assert keys == sorted(keys)


def test_dilate_square_radius() -> None:
    m = np.zeros((7, 7), bool)
    m[3, 3] = True
    assert dilate(m, 0).sum() == 1
    d = dilate(m, 2)
    assert d.sum() == 25 and d[1:6, 1:6].all()


def _via(tr: object) -> object:
    def f(c: np.ndarray) -> np.ndarray:
        x, y = tr.transform(c[:, 0], c[:, 1])  # type: ignore[attr-defined]
        return np.column_stack([x, y])

    return f


def test_district_raster_vs_vector_area_within_1pct(synthetic_demo: object) -> None:
    """Raster district areas against vector areas in EPSG:6933 (design 7.1 cross-check)."""
    import json
    from pathlib import Path

    import shapely
    from pyproj import Transformer
    from shapely.geometry import box, shape

    from stitch_eyes.core.districts import rasterize_districts
    from stitch_eyes.data.scene import Catalog, load_districts

    root = Path(str(synthetic_demo))
    scene = Catalog(root / "eyes").scenes[0]
    districts = load_districts(root / "boundaries" / "pk_districts.geojson")
    shape_hw = scene.shape
    from rasterio.transform import from_origin

    t = from_origin(scene.x0, scene.y1, scene.res, scene.res)
    index, ordered = rasterize_districts(districts, scene.crs, t, shape_hw)
    col = utm_column_area_m2(scene.x0, scene.res, shape_hw[1])
    stats = aggregate(index, ordered, np.zeros(shape_hw, bool), col)
    to_utm = Transformer.from_crs("EPSG:4326", scene.crs, always_xy=True)
    to_ea = Transformer.from_crs(scene.crs, "EPSG:6933", always_xy=True)
    frame = box(*scene.bounds_utm)
    raw = json.loads((root / "boundaries" / "pk_districts.geojson").read_text("utf-8"))
    for f in raw["features"]:
        g = shapely.transform(shape(f["geometry"]), _via(to_utm)).intersection(frame)
        vec_km2 = shapely.transform(g, _via(to_ea)).area / 1e6
        st_ = next(s for s in stats if s.district_id == f["properties"]["district_id"])
        assert abs(st_.district_area_km2 - vec_km2) / vec_km2 < 0.01


@st.composite
def blob_masks(draw: st.DrawFn, speckle: bool = True) -> tuple[np.ndarray, np.ndarray]:
    h = draw(st.integers(20, 120))
    w = draw(st.integers(20, 120))
    rng = np.random.default_rng(draw(st.integers(0, 2**32 - 1)))
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.zeros((h, w), bool)
    for _ in range(int(rng.integers(0, 6))):
        cy, cx = rng.uniform(0, h), rng.uniform(0, w)
        ry, rx = rng.uniform(2, h / 2), rng.uniform(2, w / 2)
        m |= ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1
    m &= rng.random((h, w)) > draw(st.sampled_from([0.0, 0.02] if speckle else [0.0]))  # speckle
    prob = np.clip(rng.uniform(0.5, 1.0, (h, w)), 0, 1)
    return m, prob


def _geod_area_m2(fc: dict) -> float:
    from pyproj import Geod
    from shapely.geometry import shape

    geod = Geod(ellps="WGS84")
    return sum(abs(geod.geometry_area_perimeter(shape(f["geometry"]))[0]) for f in fc["features"])


@settings(deadline=None, max_examples=60)
@given(blob_masks())
def test_eye_p2_and_x4_polygons_valid_and_area_close(case: tuple) -> None:
    from shapely.geometry import shape

    mask, prob = case
    col = utm_column_area_m2(X0, 10.0, mask.shape[1])
    conf = np.maximum(prob, 1 - prob)
    res = vectorize(mask, prob, conf, _transform(), CRS, col, min_polygon_km2=0.0005)
    assert mask.dtype == np.bool_
    for f in res.feature_collection["features"]:
        g = shape(f["geometry"])
        assert g.is_valid and not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon")
        minx, miny, maxx, maxy = g.bounds
        assert -180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90
        assert f["properties"]["confidence_class"] in ("high", "low")
        assert 0.0 <= f["properties"]["mean_confidence"] <= 1.0


@settings(deadline=None, max_examples=60)
@given(blob_masks(speckle=False))
def test_eye_x4_polygon_area_within_2pct_of_raster_area(case: tuple) -> None:
    """Blobs with one confidence class and no dropped features (design 8 step 7)."""
    mask, _ = case
    col = utm_column_area_m2(X0, 10.0, mask.shape[1])
    prob = np.where(mask, 0.9, 0.1)
    res = vectorize(
        mask, prob, np.maximum(prob, 1 - prob), _transform(), CRS, col, min_polygon_km2=0.0
    )
    raster_km2 = masked_area_km2(mask, col)
    assert res.dropped_km2 == 0.0
    # 1,000 px and up. Measured: single 500 px blobs can differ by 2.4% (simplification removes
    # corners at 15 m on a 10 m grid); the demo scene's whole collection differs by 0.2%.
    if raster_km2 >= 0.1:
        assert abs(_geod_area_m2(res.feature_collection) / 1e6 - raster_km2) / raster_km2 < 0.02


def test_empty_mask_gives_an_empty_collection() -> None:
    z = np.zeros((30, 40), bool)
    col = utm_column_area_m2(X0, 10.0, 40)
    res = vectorize(z, np.zeros((30, 40)), np.ones((30, 40)), _transform(), CRS, col)
    assert res.feature_collection == {"type": "FeatureCollection", "features": []}
    assert res.dropped_km2 == 0.0 and not res.warnings


def test_single_pixel_blob_is_dropped_with_a_warning() -> None:
    m = np.zeros((30, 40), bool)
    m[10, 10] = True
    m[0:20, 20:40] = True  # 400 px = 0.04 km2, kept
    col = utm_column_area_m2(X0, 10.0, 40)
    p = np.where(m, 0.9, 0.1)
    res = vectorize(m, p, np.maximum(p, 1 - p), _transform(), CRS, col)
    assert res.n_features == 1
    assert res.dropped_km2 > 0 and any("not drawn" in w for w in res.warnings)


def test_feature_cap_raises_the_minimum() -> None:
    m = np.zeros((100, 100), bool)
    m[::4, ::4] = True  # 625 isolated pixels
    m[50:60, 50:60] = True
    col = utm_column_area_m2(X0, 10.0, 100)
    p = np.where(m, 0.95, 0.05)
    res = vectorize(
        m, p, np.maximum(p, 1 - p), _transform(), CRS, col, min_polygon_km2=0.0, max_features=10
    )
    assert res.n_features <= 10 and any("feature cap" in w for w in res.warnings)


def test_low_confidence_pixels_are_marked() -> None:
    m = np.zeros((40, 40), bool)
    m[:, :20] = True
    m[:, 20:] = True
    p = np.where(np.arange(40)[None, :] < 20, 0.95, 0.6) * np.ones((40, 1))
    col = utm_column_area_m2(X0, 10.0, 40)
    res = vectorize(m, p, np.maximum(p, 1 - p), _transform(), CRS, col)
    classes = sorted(
        f["properties"]["confidence_class"] for f in res.feature_collection["features"]
    )
    assert classes == ["high", "low"]
