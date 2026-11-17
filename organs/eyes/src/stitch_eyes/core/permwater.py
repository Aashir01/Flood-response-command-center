"""Permanent water and new flood (design 6.2, 7).

``permanent = water & perm_mask``; ``new_flood = water & ~perm_mask``. Inside the region clip
both use the same per-pixel areas, so ``new_flood_km2 = total_water_km2 - permanent_water_km2``
holds up to float rounding and ``0 <= new_flood_km2 <= total_water_km2`` (EYE-P3).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from stitch_eyes.core.area import masked_area_km2

Bool = npt.NDArray[np.bool_]


def dilate(mask: npt.ArrayLike, radius: int) -> Bool:
    """Binary dilation with a (2r+1) x (2r+1) square, by shifted ORs (no SciPy)."""
    m = np.asarray(mask, dtype=bool)
    if radius <= 0:
        return m.copy()
    h, w = m.shape
    p = np.pad(m, radius, mode="constant", constant_values=False)
    # separable: rows then columns
    rows = np.zeros((h + 2 * radius, w), dtype=bool)
    for dx in range(2 * radius + 1):
        rows |= p[:, dx : dx + w]
    out = np.zeros((h, w), dtype=bool)
    for dy in range(2 * radius + 1):
        out |= rows[dy : dy + h, :]
    return out


@dataclass(frozen=True)
class WaterSplit:
    water: Bool
    permanent: Bool
    new_flood: Bool
    total_water_km2: float
    permanent_water_km2: float
    new_flood_km2: float


def split_water(
    water: npt.ArrayLike,
    perm_mask: npt.ArrayLike,
    clip: npt.ArrayLike,
    col_area_m2: npt.NDArray[np.float64],
) -> WaterSplit:
    """Split detected water inside ``clip`` into permanent and new flood, with areas."""
    c = np.asarray(clip, dtype=bool)
    wtr = np.asarray(water, dtype=bool) & c
    perm = wtr & np.asarray(perm_mask, dtype=bool)
    new = wtr & ~perm
    total = masked_area_km2(wtr, col_area_m2)
    perm_km2 = masked_area_km2(perm, col_area_m2)
    new_km2 = masked_area_km2(new, col_area_m2)
    return WaterSplit(wtr, perm, new, total, perm_km2, min(new_km2, total))
