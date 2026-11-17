"""Scene quantization, dequantization and nodata handling (design 4.3, 6.1).

The committed demo scene stores Sentinel-1 sigma0 in dB as uint8: ``0`` is nodata and
``v = 1 + rint((clip(dB, LO, HI) - LO) / (HI - LO) * 254)``. The step is 40/254 = 0.157 dB, so
the round-trip error is at most half a step (0.079 dB, EYE-X7). Training applies the same
quantization to every input so the model sees the committed format.

Pure NumPy, no I/O. The training scripts import this module directly (one source of truth).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

QUANT_LO = -35.0
QUANT_HI = 5.0
NODATA = 0
LEVELS = 254
STEP_DB = (QUANT_HI - QUANT_LO) / LEVELS

F32 = npt.NDArray[np.float32]
U8 = npt.NDArray[np.uint8]
Bool = npt.NDArray[np.bool_]


def quantize_db(db: npt.ArrayLike) -> U8:
    """dB to uint8 codes 1..255; non-finite values become ``NODATA`` (0)."""
    a = np.asarray(db, dtype=np.float64)
    finite = np.isfinite(a)
    clipped = np.clip(np.where(finite, a, QUANT_LO), QUANT_LO, QUANT_HI)
    codes = 1.0 + np.rint((clipped - QUANT_LO) / (QUANT_HI - QUANT_LO) * LEVELS)
    return np.where(finite, codes, NODATA).astype(np.uint8)


def dequantize_db(codes: npt.ArrayLike) -> F32:
    """uint8 codes to dB (float32); ``NODATA`` becomes NaN."""
    c = np.asarray(codes)
    db = QUANT_LO + (c.astype(np.float64) - 1.0) * STEP_DB
    return np.where(c == NODATA, np.nan, db).astype(np.float32)


def quantize_roundtrip(db: npt.ArrayLike) -> F32:
    """``dequantize_db(quantize_db(db))``: what the model sees for a dB input."""
    return dequantize_db(quantize_db(db))


@dataclass(frozen=True)
class Prepared:
    """Model-ready window: dB with nodata filled, the validity mask, and its share."""

    db: F32  # (bands, H, W), finite everywhere
    valid: Bool  # (H, W), True where every band had data
    valid_fraction: float


def prepare(codes: npt.NDArray[np.uint8]) -> Prepared:
    """Dequantize a (bands, H, W) uint8 window and fill nodata with each band's valid median.

    A pixel is valid when every band has data. Raises ``ValueError`` if no pixel is valid.
    The fill avoids a cliff at the swath edge; the caller forces filled pixels to "not water".
    """
    c = np.asarray(codes)
    if c.ndim != 3 or c.dtype != np.uint8:
        raise ValueError("expected a (bands, H, W) uint8 array")
    valid = np.all(c != NODATA, axis=0)
    n_valid = int(valid.sum())
    if n_valid == 0:
        raise ValueError("no valid data in the window")
    db = dequantize_db(c)
    for b in range(db.shape[0]):
        band = db[b]
        med = np.float32(np.median(band[valid]))
        band[~valid] = med
    return Prepared(db=db, valid=valid, valid_fraction=n_valid / valid.size)


def fill_invalid_db(db: npt.ArrayLike) -> tuple[F32, Bool]:
    """Fill non-finite dB values with each band's median of the valid pixels (training/eval).

    Returns the filled array and the validity mask. An all-invalid input is filled with ``LO``.
    """
    a = np.array(db, dtype=np.float32, copy=True)
    valid = np.all(np.isfinite(a), axis=0)
    for b in range(a.shape[0]):
        band = a[b]
        fill = np.float32(np.median(band[valid])) if valid.any() else np.float32(QUANT_LO)
        band[~valid] = fill
    return a, valid
