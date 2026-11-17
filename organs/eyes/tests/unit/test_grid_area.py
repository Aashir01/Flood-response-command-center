"""Tile grid, padding and per-pixel area (design 4.1, 5): hand-computed cases and EYE-X3."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_eyes.core.area import (
    geographic_row_area_m2,
    masked_area_km2,
    utm_column_area_m2,
    utm_epsg,
    utm_scale_factor,
)
from stitch_eyes.core.grid import make_grid, pad_window, valid_tile_size, weight_1d


def test_grid_for_small_and_odd_windows() -> None:
    g = make_grid(5, 7, 64)  # window smaller than a tile: one tile, padded to 64 x 64
    assert (g.n_y, g.n_x, g.overlap, g.stride) == (1, 1, 8, 56)
    assert g.padded_shape == (64, 64) and g.origins() == [(0, 0)]
    g = make_grid(2560, 2560, 256)  # the demo scene: 12 x 12 = 144 tiles
    assert (g.n_y, g.n_x, g.stride) == (12, 12, 224)
    assert g.padded_shape == (11 * 224 + 256, 11 * 224 + 256)
    g = make_grid(65, 200, 64)
    assert (g.n_y, g.n_x) == (2, 4) and g.origins()[:2] == [(0, 0), (0, 56)]


def test_weight_ramp_is_integer_positive_and_capped() -> None:
    w = weight_1d(64, 8)
    assert w.dtype == np.int64 and w.min() == 1 and w.max() == 8
    assert list(w[:9]) == [1, 2, 3, 4, 5, 6, 7, 8, 8] and list(w[-3:]) == [3, 2, 1]


@pytest.mark.parametrize(("h", "w"), [(1, 1), (5, 7), (3, 200), (130, 2)])
def test_pad_window_keeps_the_original_pixels(h: int, w: int) -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(size=(2, h, w)).astype(np.float32)
    g = make_grid(h, w, 64)
    p = pad_window(a, g)
    assert p.shape == (2, *g.padded_shape)
    assert np.array_equal(p[:, :h, :w], a)


@pytest.mark.parametrize("t", [0, 32, 63, 100, 2048, -64])
def test_invalid_tile_sizes(t: int) -> None:
    assert not valid_tile_size(t)
    with pytest.raises(ValueError):
        make_grid(10, 10, t)


def test_utm_area_at_the_central_meridian_is_100_over_k0_squared() -> None:
    a = utm_column_area_m2(500_000.0 - 5.0, 10.0, 1)
    assert a[0] == pytest.approx(100.0 / 0.9996**2, rel=1e-9)
    assert utm_epsg(67.7, 26.5) == 32642  # Sindh is in UTM 42N
    assert utm_scale_factor(500_000.0) == pytest.approx(0.9996)


@settings(deadline=None, max_examples=60)
@given(
    st.floats(166_000, 834_000),
    st.floats(2_700_000, 3_100_000),
    st.sampled_from([10.0, 30.0, 100.0]),
    st.integers(1, 50),
    st.integers(1, 50),
)
def test_eye_x3_utm_pixel_area_matches_geodesic_area(
    x0: float, y1: float, res: float, w: int, h: int
) -> None:
    """Area of a pixel block in UTM 42N vs the WGS84 geodesic area (pyproj.Geod), 0.2%."""
    from pyproj import Geod, Transformer

    tr = Transformer.from_crs("EPSG:32642", "EPSG:4326", always_xy=True)
    xs = [x0, x0 + w * res, x0 + w * res, x0, x0]
    ys = [y1, y1, y1 - h * res, y1 - h * res, y1]
    # densify the edges so the geodesic polygon follows the grid lines
    lon: list[float] = []
    lat: list[float] = []
    for i in range(4):
        for f in np.linspace(0, 1, 20, endpoint=False):
            lo, la = tr.transform(xs[i] + f * (xs[i + 1] - xs[i]), ys[i] + f * (ys[i + 1] - ys[i]))
            lon.append(lo)
            lat.append(la)
    geod_area = abs(Geod(ellps="WGS84").polygon_area_perimeter(lon, lat)[0])
    ours = float(utm_column_area_m2(x0, res, w).sum() * h)
    assert ours == pytest.approx(geod_area, rel=0.002)


def test_eye_x3_window_area_equals_sum_of_its_parts() -> None:
    col = utm_column_area_m2(357_670.0, 10.0, 300)
    rng = np.random.default_rng(1)
    m = rng.random((200, 300)) < 0.4
    whole = masked_area_km2(m, col)
    left = masked_area_km2(m[:, :120], col[:120])
    right = masked_area_km2(m[:, 120:], col[120:])
    assert whole == pytest.approx(left + right, rel=1e-12)


def test_geographic_cells_sum_to_the_sphere_band() -> None:
    import math

    rows = geographic_row_area_m2(10.0, 1.0, 360.0, 10)
    band = 2 * math.pi * 6_371_007.2**2 * (math.sin(math.radians(10)) - 0)
    assert rows.sum() == pytest.approx(band, rel=1e-9)
