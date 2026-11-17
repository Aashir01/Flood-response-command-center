"""Shared Hypothesis strategies and deterministic stub models for the Eyes tests (design 13)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from hypothesis import strategies as st

from stitch_eyes.core.infer import ThresholdTileModel

F32 = npt.NDArray[np.float32]


@dataclass
class HashFieldModel:
    """Pseudo-random logits seeded by the tile's bytes: a pure function of tile content."""

    amplitude: float = 8.0
    name: str = "hash-field-stub"
    version: str = "1"
    sha256: str = "0" * 64
    variant: str = "stub"

    def predict_logits(self, tile: F32) -> F32:
        seed = int.from_bytes(hashlib.sha256(np.ascontiguousarray(tile).tobytes()).digest()[:8])
        rng = np.random.default_rng(seed)
        out: F32 = rng.normal(0.0, self.amplitude, size=tile.shape[1:]).astype(np.float32)
        return out


@dataclass
class ConstantModel:
    value: float = -12.0
    name: str = "constant-stub"
    version: str = "1"
    sha256: str = "1" * 64
    variant: str = "stub"

    def predict_logits(self, tile: F32) -> F32:
        return np.full(tile.shape[1:], self.value, dtype=np.float32)


def stub_models() -> st.SearchStrategy[object]:
    return st.sampled_from([ThresholdTileModel(), HashFieldModel()])


def tile_sizes() -> st.SearchStrategy[int]:
    return st.sampled_from([64, 128, 256])


@st.composite
def windows(draw: st.DrawFn, max_side: int = 400) -> F32:
    """(2, H, W) dB windows, H and W in 1..max_side, smooth water blobs plus noise."""
    h = draw(st.integers(1, max_side))
    w = draw(st.integers(1, max_side))
    seed = draw(st.integers(0, 2**32 - 1))
    rng = np.random.default_rng(seed)
    base = rng.normal(-14.0, 2.0, size=(2, h, w))
    n_blobs = int(rng.integers(0, 4))
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(n_blobs):
        cy, cx = rng.uniform(0, h), rng.uniform(0, w)
        r = rng.uniform(3, max(4.0, min(h, w) / 2))
        base[:, (yy - cy) ** 2 + (xx - cx) ** 2 < r * r] -= 10.0
    return base.astype(np.float32)


@st.composite
def scenes(draw: st.DrawFn, max_side: int = 200) -> npt.NDArray[np.uint8]:
    """uint8 scene codes with random nodata blocks."""
    from stitch_eyes.core.preprocess import quantize_db

    db = draw(windows(max_side))
    codes = quantize_db(db)
    _, h, w = codes.shape
    seed = draw(st.integers(0, 2**32 - 1))
    rng = np.random.default_rng(seed)
    for _ in range(int(rng.integers(0, 3))):
        y0, x0 = int(rng.integers(0, h)), int(rng.integers(0, w))
        codes[:, y0 : y0 + int(rng.integers(1, h + 1)), x0 : x0 + int(rng.integers(1, w + 1))] = 0
    return codes


@st.composite
def water_perm_masks(
    draw: st.DrawFn,
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_], npt.NDArray[np.int32], np.ndarray]:
    """(water, perm, district index raster with -1 outside, per-column pixel areas m^2)."""
    h = draw(st.integers(1, 60))
    w = draw(st.integers(1, 60))
    seed = draw(st.integers(0, 2**32 - 1))
    rng = np.random.default_rng(seed)
    water = rng.random((h, w)) < rng.uniform(0, 1)
    perm = rng.random((h, w)) < rng.uniform(0, 1)
    n_d = int(rng.integers(1, 6))
    index = rng.integers(-1, n_d, size=(h, w)).astype(np.int32)
    areas = rng.uniform(50.0, 150.0, size=w)
    return water, perm, index, areas


@st.composite
def bboxes(draw: st.DrawFn, valid: bool) -> tuple[float, float, float, float]:
    lon = st.floats(-180, 180, allow_nan=False)
    lat = st.floats(-90, 90, allow_nan=False)
    a, b = draw(lon), draw(lon)
    c, d = draw(lat), draw(lat)
    if valid:
        from hypothesis import assume

        assume(a != b and c != d)
        return (min(a, b), min(c, d), max(a, b), max(c, d))
    # equal or reversed on at least one axis
    if draw(st.booleans()):
        return (max(a, b), min(c, d), min(a, b), max(c, d))
    return (min(a, b), max(c, d), max(a, b), min(c, d))
