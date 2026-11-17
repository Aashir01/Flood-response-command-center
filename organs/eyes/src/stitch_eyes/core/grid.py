"""Tile grid for a window (design 4.1). Depends only on (H, W, tile_size), never on order.

Overlap ``O = T // 8``, stride ``S = T - O``. ``n = ceil((L - T) / S) + 1`` tiles per axis when
``L > T``, else 1. The window is reflect-padded (edge padding when a side is shorter than the
reflect limit) to ``((n - 1) * S + T)`` per axis; padded pixels never enter the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

MIN_TILE = 64
MAX_TILE = 1024


def valid_tile_size(t: int) -> bool:
    return MIN_TILE <= t <= MAX_TILE and (t & (t - 1)) == 0


@dataclass(frozen=True)
class TileGrid:
    height: int
    width: int
    tile: int
    overlap: int
    stride: int
    n_y: int
    n_x: int

    @property
    def padded_shape(self) -> tuple[int, int]:
        return (
            (self.n_y - 1) * self.stride + self.tile,
            (self.n_x - 1) * self.stride + self.tile,
        )

    @property
    def n_tiles(self) -> int:
        return self.n_y * self.n_x

    def origins(self) -> list[tuple[int, int]]:
        """Top-left corners of every tile in the padded window, row-major."""
        return [
            (i * self.stride, j * self.stride) for i in range(self.n_y) for j in range(self.n_x)
        ]


def _count(length: int, tile: int, stride: int) -> int:
    return 1 if length <= tile else math.ceil((length - tile) / stride) + 1


def make_grid(height: int, width: int, tile: int) -> TileGrid:
    if height < 1 or width < 1:
        raise ValueError("window must be at least 1 x 1")
    if not valid_tile_size(tile):
        raise ValueError("tile_size must be a power of two in 64..1024")
    overlap = tile // 8
    stride = tile - overlap
    return TileGrid(
        height,
        width,
        tile,
        overlap,
        stride,
        _count(height, tile, stride),
        _count(width, tile, stride),
    )


def pad_window(arr: npt.NDArray[np.float32], grid: TileGrid) -> npt.NDArray[np.float32]:
    """Pad a (bands, H, W) array to the grid's padded shape (reflect, edge when too short)."""
    ph, pw = grid.padded_shape
    dy, dx = ph - grid.height, pw - grid.width
    out = arr
    # numpy's reflect needs pad < length; pad in steps so any size works deterministically.
    while dy > 0 or dx > 0:
        h, w = out.shape[-2:]
        sy = min(dy, h - 1) if h > 1 else 0
        sx = min(dx, w - 1) if w > 1 else 0
        if sy == 0 and sx == 0:
            out = np.pad(out, ((0, 0), (0, dy), (0, dx)), mode="edge")
            break
        out = np.pad(out, ((0, 0), (0, sy), (0, sx)), mode="reflect")
        dy -= sy
        dx -= sx
    return out


def weight_1d(tile: int, overlap: int) -> npt.NDArray[np.int64]:
    """Integer ramp ``w(i) = min(min(i, T-1-i) + 1, O)``: never zero, at most ``O``."""
    i = np.arange(tile)
    return np.minimum(np.minimum(i, tile - 1 - i) + 1, overlap).astype(np.int64)


def weight_2d(tile: int, overlap: int) -> npt.NDArray[np.int64]:
    w = weight_1d(tile, overlap)
    return np.outer(w, w)
