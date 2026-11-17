"""Per-pixel ground area (design 5).

UTM grids: nominal area ``res^2`` divided by ``k^2``, with the UTM point scale factor
``k = 0.9996 * (1 + (E - 500000)^2 / (2 R^2))`` at the pixel-centre easting (R = 6,371 km).
The area varies by column only. Geographic grids (Sen1Floods11 chips): cell area on the
authalic sphere, ``R_a^2 * dlon * (sin(lat2) - sin(lat1))``, varying by row only.
All km^2 numbers in the tools are pixel counts times these areas.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

R_MEAN = 6_371_000.0
R_AUTHALIC = 6_371_007.2
K0 = 0.9996
FALSE_EASTING = 500_000.0


def utm_zone(lon: float) -> int:
    return math.floor((lon + 180.0) / 6.0) % 60 + 1


def utm_epsg(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + utm_zone(lon)


def utm_scale_factor(easting: npt.ArrayLike) -> npt.NDArray[np.float64]:
    e = np.asarray(easting, dtype=np.float64) - FALSE_EASTING
    return K0 * (1.0 + e**2 / (2.0 * R_MEAN**2))


def utm_column_area_m2(x0: float, res: float, width: int) -> npt.NDArray[np.float64]:
    """Ground area (m^2) of one pixel in each column of a north-up UTM grid."""
    centres = x0 + (np.arange(width) + 0.5) * res
    k = utm_scale_factor(centres)
    out: npt.NDArray[np.float64] = (res * res) / (k * k)
    return out


def geographic_row_area_m2(
    lat_top: float, dlat: float, dlon: float, height: int
) -> npt.NDArray[np.float64]:
    """Area (m^2) of one cell in each row of a north-up lat/lon grid (degrees)."""
    tops = lat_top - np.arange(height) * dlat
    bottoms = tops - dlat
    out: npt.NDArray[np.float64] = (
        R_AUTHALIC**2
        * math.radians(dlon)
        * np.abs(np.sin(np.radians(tops)) - np.sin(np.radians(bottoms)))
    )
    return out


def masked_area_km2(mask: npt.ArrayLike, col_area_m2: npt.NDArray[np.float64]) -> float:
    """Sum of pixel areas where ``mask`` is true (per-column areas), in km^2."""
    m = np.asarray(mask, dtype=bool)
    per_col = m.sum(axis=0, dtype=np.int64).astype(np.float64)
    return float(per_col @ col_area_m2) / 1e6
