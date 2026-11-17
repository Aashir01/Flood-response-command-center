"""Order-independent tile blending with integer accumulators (design 4.2, EYE-P1).

Float addition is not associative, so summing float logits in another order can flip a pixel
near zero. Each tile's logits are clipped to +-30, quantized to ``q = rint(z * 1024)`` (int32,
round half to even) and accumulated as ``A += w * q`` and ``W += w`` in int64 with integer
weights. Integer addition is associative and commutative, so ``A`` and ``W`` are bit-identical
for any tile order or batching. The mask is decided on integers (``A > 0``); the probability
``sigmoid(A / (W * 1024))`` is computed once from the final integers in float64.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from stitch_eyes.core.grid import TileGrid, weight_2d

LOGIT_CLIP = 30.0
SCALE = 1024


def quantize_logits(z: npt.ArrayLike) -> npt.NDArray[np.int32]:
    a = np.clip(np.nan_to_num(np.asarray(z, dtype=np.float64), nan=0.0), -LOGIT_CLIP, LOGIT_CLIP)
    return np.rint(a * SCALE).astype(np.int32)


@dataclass
class Accumulator:
    grid: TileGrid
    A: npt.NDArray[np.int64]
    W: npt.NDArray[np.int64]

    @classmethod
    def empty(cls, grid: TileGrid) -> Accumulator:
        shape = grid.padded_shape
        return cls(grid, np.zeros(shape, np.int64), np.zeros(shape, np.int64))

    def add(self, origin: tuple[int, int], logits: npt.ArrayLike) -> None:
        t = self.grid.tile
        q = quantize_logits(logits)
        if q.shape != (t, t):
            raise ValueError(f"tile logits must be {t} x {t}, got {q.shape}")
        w = weight_2d(t, self.grid.overlap)
        y, x = origin
        self.A[y : y + t, x : x + t] += w * q.astype(np.int64)
        self.W[y : y + t, x : x + t] += w

    def merge(self, other: Accumulator) -> None:
        """Add another accumulator over the same grid (for split or parallel processing)."""
        self.A += other.A
        self.W += other.W

    def cropped(self) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
        h, w = self.grid.height, self.grid.width
        return self.A[:h, :w], self.W[:h, :w]


def accumulate(
    grid: TileGrid, tiles: Iterable[tuple[tuple[int, int], npt.ArrayLike]]
) -> Accumulator:
    acc = Accumulator.empty(grid)
    for origin, logits in tiles:
        acc.add(origin, logits)
    return acc


@dataclass(frozen=True)
class Blended:
    water: npt.NDArray[np.uint8]  # {0, 1}, decided on integers
    prob: npt.NDArray[np.float64]  # sigmoid of the blended mean logit
    confidence: npt.NDArray[np.float64]  # max(p, 1 - p)


def finalize(acc: Accumulator) -> Blended:
    a, w = acc.cropped()
    if np.any(w <= 0):
        raise ValueError("every pixel must have positive total weight")
    mean_logit = a.astype(np.float64) / (w.astype(np.float64) * SCALE)
    prob = 1.0 / (1.0 + np.exp(-mean_logit))
    return Blended(
        water=(a > 0).astype(np.uint8),
        prob=prob,
        confidence=np.maximum(prob, 1.0 - prob),
    )


def float_blend(
    grid: TileGrid, tiles: Iterable[tuple[tuple[int, int], npt.ArrayLike]]
) -> npt.NDArray[np.float32]:
    """Naive float32 weighted-mean blend (negative control for EYE-P1; not used in serving)."""
    ph, pw = grid.padded_shape
    s = np.zeros((ph, pw), np.float32)
    ws = np.zeros((ph, pw), np.float32)
    w = weight_2d(grid.tile, grid.overlap).astype(np.float32)
    t = grid.tile
    for (y, x), z in tiles:
        s[y : y + t, x : x + t] += w * np.asarray(z, np.float32)
        ws[y : y + t, x : x + t] += w
    out: npt.NDArray[np.float32] = (s / ws)[: grid.height, : grid.width]
    return out
