"""Segmentation pipeline for one scene window (design 10 steps 3 to 4).

Preprocess, tile, infer, blend, then permanent water, region clip, areas and confidence. The
result is cached by ``(scene sha, model sha, tile size, window)``; vectorization and district
aggregation are derived from the cached masks.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from stitch_eyes.core.area import utm_column_area_m2
from stitch_eyes.core.districts import District, rasterize_districts
from stitch_eyes.core.infer import TileModel, run_tiles
from stitch_eyes.core.permwater import WaterSplit, dilate, split_water
from stitch_eyes.core.preprocess import prepare
from stitch_eyes.data.scene import Scene, Window, read_codes, read_perm


@dataclass(frozen=True)
class SegResult:
    scene: Scene
    window: Window
    tile_size: int
    tiles_processed: int
    valid_fraction: float
    prob: npt.NDArray[np.float64]
    confidence: npt.NDArray[np.float64]
    split: WaterSplit
    district_index: npt.NDArray[np.int32]
    districts: list[District]
    col_area_m2: npt.NDArray[np.float64]

    @property
    def flood_confidence(self) -> float | None:
        """Mean per-pixel max(p, 1 - p) over new-flood pixels; None when there are none."""
        m = self.split.new_flood
        if not m.any():
            return None
        return float(np.clip(self.confidence[m].mean(), 0.0, 1.0))


class NoValidData(ValueError):
    pass


def segment(
    scene: Scene,
    window: Window,
    tile_size: int,
    model: TileModel,
    districts: list[District],
    perm_dilate_px: int,
) -> SegResult:
    codes = read_codes(scene, window)
    try:
        prep = prepare(codes)
    except ValueError as exc:
        raise NoValidData(str(exc)) from None
    blended, grid = run_tiles(prep.db, tile_size, model)
    water = (blended.water > 0) & prep.valid
    perm = dilate(read_perm(scene, window), perm_dilate_px)
    transform = window.transform(scene)
    index, ordered = rasterize_districts(
        districts, scene.crs, transform, (window.height, window.width)
    )
    clip = index >= 0
    col_area = utm_column_area_m2(scene.x0 + window.col0 * scene.res, scene.res, window.width)
    split = split_water(water, perm, clip, col_area)
    return SegResult(
        scene=scene,
        window=window,
        tile_size=tile_size,
        tiles_processed=grid.n_tiles,
        valid_fraction=prep.valid_fraction,
        prob=blended.prob,
        confidence=blended.confidence,
        split=split,
        district_index=index,
        districts=ordered,
        col_area_m2=col_area,
    )


class ResultCache:
    """Small thread-safe LRU of ``SegResult`` with per-key computation locks."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._data: OrderedDict[tuple[object, ...], SegResult] = OrderedDict()
        self._lock = threading.Lock()
        self._key_locks: dict[tuple[object, ...], threading.Lock] = {}

    def get_or_compute(
        self, key: tuple[object, ...], compute: Callable[[], SegResult]
    ) -> tuple[SegResult, bool]:
        with self._lock:
            hit = self._data.get(key)
            if hit is not None:
                self._data.move_to_end(key)
                return hit, True
            klock = self._key_locks.setdefault(key, threading.Lock())
        with klock:
            with self._lock:
                hit = self._data.get(key)
                if hit is not None:
                    return hit, True
            res = compute()
            with self._lock:
                self._data[key] = res
                while len(self._data) > self._size:
                    self._data.popitem(last=False)
            return res, False

    def __contains__(self, key: tuple[object, ...]) -> bool:
        with self._lock:
            return key in self._data
