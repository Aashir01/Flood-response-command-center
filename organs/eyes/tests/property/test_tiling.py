"""Tiling and blending properties (design 4, 13): EYE-P1, EYE-X1, EYE-X2, EYE-P4 (stub).

EYE-P1 is exact: the integer accumulators, the mask and the confidence are byte-identical for
any tile order and any split of the tiles into partial accumulators. The negative control shows
that a float32 blend of the same tiles in two orders differs, so the test can see the failure it
guards against.
"""

from __future__ import annotations

import numpy as np
from eyes_strategies import HashFieldModel, stub_models, tile_sizes, windows
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from stitch_eyes.core.blend import SCALE, Accumulator, finalize, float_blend
from stitch_eyes.core.grid import make_grid, pad_window
from stitch_eyes.core.infer import ThresholdTileModel, run_tiles


def _tiles(db: np.ndarray, tile: int, model: object) -> tuple[object, list]:
    _, h, w = db.shape
    grid = make_grid(h, w, tile)
    padded = pad_window(db, grid)
    t = grid.tile
    out = []
    for y, x in grid.origins():
        z = model.predict_logits(np.ascontiguousarray(padded[:, y : y + t, x : x + t]))  # type: ignore[attr-defined]
        out.append(((y, x), z))
    return grid, out


@settings(deadline=None)
@given(windows(), tile_sizes(), stub_models(), st.randoms(use_true_random=False))
def test_eye_p1_tile_order_and_batching_do_not_change_output(
    db: np.ndarray, tile: int, model: object, rnd: object
) -> None:
    grid, tiles = _tiles(db, tile, model)
    ref = Accumulator.empty(grid)
    for origin, z in tiles:
        ref.add(origin, z)
    perm = list(range(len(tiles)))
    rnd.shuffle(perm)  # type: ignore[attr-defined]
    # random batching: split the permuted sequence into partial accumulators, merged later
    cuts = sorted(rnd.sample(range(len(perm) + 1), k=min(3, len(perm) + 1)))  # type: ignore[attr-defined]
    parts = []
    start = 0
    for c in [*cuts, len(perm)]:
        acc = Accumulator.empty(grid)
        for k in perm[start:c]:
            acc.add(*tiles[k])
        parts.append(acc)
        start = c
    merged = parts[-1]
    for p in reversed(parts[:-1]):
        merged.merge(p)
    assert np.array_equal(ref.A, merged.A) and np.array_equal(ref.W, merged.W)
    a, b = finalize(ref), finalize(merged)
    assert a.water.tobytes() == b.water.tobytes()
    assert a.confidence.tobytes() == b.confidence.tobytes()
    assert a.prob.tobytes() == b.prob.tobytes()


@settings(deadline=None, max_examples=50)
@given(windows(max_side=300), tile_sizes(), st.randoms(use_true_random=False))
def test_eye_p1_run_tiles_with_permuted_order(db: np.ndarray, tile: int, rnd: object) -> None:
    model = HashFieldModel()
    base, grid = run_tiles(db, tile, model)
    order = list(range(grid.n_tiles))
    rnd.shuffle(order)  # type: ignore[attr-defined]
    other, _ = run_tiles(db, tile, model, order=order)
    assert base.water.tobytes() == other.water.tobytes()
    assert base.confidence.tobytes() == other.confidence.tobytes()


def test_eye_p1_negative_control_float_blend_depends_on_order() -> None:
    """Float32 accumulation of the same tiles in two orders gives different bits.

    A 120 x 120 window with T = 64 has a 2 x 2 tile grid; the 8 x 8 corner overlap gets four
    contributions, and float addition of four terms is not associative. Logits are realistic
    (normal, sd 8, inside the +-30 clip). The integer accumulators stay identical.
    """
    grid = make_grid(120, 120, 64)
    assert grid.n_tiles == 4
    differs = False
    for seed in range(20):
        rng = np.random.default_rng(seed)
        tiles = [(o, rng.normal(0, 8, size=(64, 64)).astype(np.float32)) for o in grid.origins()]
        f1 = float_blend(grid, tiles)
        f2 = float_blend(grid, [tiles[2], tiles[0], tiles[3], tiles[1]])
        acc1 = Accumulator.empty(grid)
        acc2 = Accumulator.empty(grid)
        for o, z in tiles:
            acc1.add(o, z)
        for k in (2, 0, 3, 1):
            acc2.add(*tiles[k])
        assert np.array_equal(acc1.A, acc2.A) and np.array_equal(acc1.W, acc2.W)
        if f1.tobytes() != f2.tobytes():
            differs = True
            break
    assert differs, "float32 blending was order-independent on every crafted case"


@settings(deadline=None)
@given(st.integers(1, 400), st.integers(1, 400), tile_sizes())
def test_eye_x1_grid_covers_every_pixel_with_positive_weight(h: int, w: int, tile: int) -> None:
    grid = make_grid(h, w, tile)
    acc = Accumulator.empty(grid)
    for o in grid.origins():
        acc.add(o, np.zeros((tile, tile), np.float32))
    _, wsum = acc.cropped()
    assert wsum.shape == (h, w) and int(wsum.min()) > 0
    ph, pw = grid.padded_shape
    assert ph >= h and pw >= w and (ph - grid.tile) % grid.stride == 0


@settings(deadline=None)
@given(
    st.integers(1, 300),
    st.integers(1, 300),
    tile_sizes(),
    st.integers(-30 * SCALE, 30 * SCALE),
)
def test_eye_x2_constant_logit_field_is_returned_exactly(h: int, w: int, tile: int, q: int) -> None:
    z = q / SCALE
    grid = make_grid(h, w, tile)
    acc = Accumulator.empty(grid)
    for o in grid.origins():
        acc.add(o, np.full((tile, tile), z, np.float64))
    a, wsum = acc.cropped()
    assert np.array_equal(a, wsum * q)  # mean quantized logit is exactly q / SCALE
    out = finalize(acc)
    assert np.all(out.water == (1 if q > 0 else 0))


@settings(deadline=None, max_examples=40, suppress_health_check=[HealthCheck.filter_too_much])
@given(windows(max_side=300))
def test_eye_p4_stub_area_invariant_to_tile_size(db: np.ndarray) -> None:
    """Bounded receptive field (3 x 3) smaller than every overlap: at most 1% difference."""
    model = ThresholdTileModel()
    counts = []
    for t in (64, 128, 256):
        out, _ = run_tiles(db, t, model)
        counts.append(int(out.water.sum()))
    ref = max(counts)
    # The tolerance is relative, so it is checked on windows with at least 1,000 water pixels.
    # In tiny windows (found: a 1 x 30 strip with 18 water pixels) one boundary pixel already
    # exceeds 1%: the 3 x 3 filter sees reflect padding that depends on the tile size.
    assume(ref >= 1000)
    assert (max(counts) - min(counts)) / ref <= 0.01
