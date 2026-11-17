"""Sen1Floods11 hand-labeled dataset for training (design 3.2, task 1).

Chips are loaded once into memory (252 train chips x 512 x 512 x 2 float32 is about 0.5 GB).
Samples are random crops with flips, 90-degree rotations, a per-band dB offset, Gaussian noise
and the demo-scene uint8 quantization. Label -1 (no data) and pixels whose S1 value is not
finite are ignored by the loss.

Quantization comes from ``stitch_eyes.core.preprocess`` (one copy shared with the organ).
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from stitch_eyes.core.preprocess import (  # noqa: E402
    QUANT_HI,
    QUANT_LO,
    fill_invalid_db,
    quantize_roundtrip,
)

SPLIT_FILES = {
    "train": "flood_train_data.csv",
    "valid": "flood_valid_data.csv",
    "test": "flood_test_data.csv",
    "bolivia": "flood_bolivia_data.csv",
}


@dataclass
class Chip:
    chip_id: str
    s1: npt.NDArray[np.float32]  # (2, H, W) dB, NaN filled with the band median
    label: npt.NDArray[np.int16]  # (H, W): -1 ignore, 0 not water, 1 water
    jrc: npt.NDArray[np.uint8] | None = None


def split_ids(root: Path, split: str) -> list[str]:
    path = root / "splits" / SPLIT_FILES[split]
    out: list[str] = []
    with path.open(newline="") as f:
        for row in csv.reader(f):
            if row and row[0].strip():
                out.append(row[0].strip().replace("_S1Hand.tif", ""))
    return out


def load_chip(root: Path, chip_id: str, with_jrc: bool = False) -> Chip:
    import rasterio

    with rasterio.open(root / "S1Hand" / f"{chip_id}_S1Hand.tif") as r:
        s1 = r.read().astype(np.float32)
    with rasterio.open(root / "LabelHand" / f"{chip_id}_LabelHand.tif") as r:
        label = r.read(1).astype(np.int16)
    s1, valid = fill_invalid_db(s1)
    label = np.where(valid, label, -1).astype(np.int16)
    jrc = None
    if with_jrc:
        with rasterio.open(root / "JRCWaterHand" / f"{chip_id}_JRCWaterHand.tif") as r:
            jrc = (r.read(1) > 0).astype(np.uint8)
    return Chip(chip_id, s1, label, jrc)


def load_split(root: Path, split: str, max_chips: int = 0, with_jrc: bool = False) -> list[Chip]:
    ids = split_ids(root, split)
    if max_chips:
        ids = ids[:max_chips]
    return [load_chip(root, cid, with_jrc) for cid in ids]


def channel_stats(chips: list[Chip]) -> tuple[list[float], list[float]]:
    """Mean and std of (VV, VH, VV-VH) after clipping, over labelled pixels of ``chips``."""
    sums = np.zeros(3)
    sq = np.zeros(3)
    n = 0
    for c in chips:
        keep = c.label != -1
        x = np.clip(quantize_roundtrip(c.s1), QUANT_LO, QUANT_HI).astype(np.float64)
        ch = np.stack([x[0], x[1], x[0] - x[1]])[:, keep]
        sums += ch.sum(axis=1)
        sq += (ch**2).sum(axis=1)
        n += ch.shape[1]
    mean = sums / n
    std = np.sqrt(sq / n - mean**2)
    return [float(v) for v in mean], [float(v) for v in std]


def augment(
    rng: np.random.Generator,
    s1: npt.NDArray[np.float32],
    label: npt.NDArray[np.int16],
    bias_db: float,
    noise_db: float,
    flips: bool,
    rot90: bool,
    quantize: bool,
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.int16]]:
    x = s1.copy()
    y = label.copy()
    if flips and rng.random() < 0.5:
        x, y = x[:, :, ::-1], y[:, ::-1]
    if flips and rng.random() < 0.5:
        x, y = x[:, ::-1, :], y[::-1, :]
    if rot90:
        k = int(rng.integers(0, 4))
        x, y = np.rot90(x, k, axes=(1, 2)), np.rot90(y, k)
    if bias_db:
        x = x + rng.uniform(-bias_db, bias_db, size=(x.shape[0], 1, 1)).astype(np.float32)
    if noise_db:
        x = x + rng.normal(0.0, noise_db, size=x.shape).astype(np.float32)
    if quantize:
        x = quantize_roundtrip(x)
    return np.ascontiguousarray(x, dtype=np.float32), np.ascontiguousarray(y)


def random_crop(
    rng: np.random.Generator, chip: Chip, size: int, tries: int = 10
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.int16]] | None:
    """A crop with at least one labelled pixel, or None after ``tries`` attempts."""
    _, h, w = chip.s1.shape
    for _ in range(tries):
        y0 = int(rng.integers(0, h - size + 1))
        x0 = int(rng.integers(0, w - size + 1))
        lab = chip.label[y0 : y0 + size, x0 : x0 + size]
        if np.any(lab != -1):
            return chip.s1[:, y0 : y0 + size, x0 : x0 + size], lab
    return None


def epoch_samples(
    rng: np.random.Generator,
    chips: list[Chip],
    crop: int,
    crops_per_chip: int,
    aug: dict[str, object],
) -> list[tuple[npt.NDArray[np.float32], npt.NDArray[np.int16]]]:
    """One epoch of augmented crops in a shuffled order (deterministic for a given rng)."""
    out: list[tuple[npt.NDArray[np.float32], npt.NDArray[np.int16]]] = []
    for chip in chips:
        for _ in range(crops_per_chip):
            got = random_crop(rng, chip, crop)
            if got is None:
                continue
            out.append(
                augment(
                    rng,
                    got[0],
                    got[1],
                    float(aug.get("bias_db", 0.0)),  # type: ignore[arg-type]
                    float(aug.get("noise_db", 0.0)),  # type: ignore[arg-type]
                    bool(aug.get("flips", True)),
                    bool(aug.get("rot90", True)),
                    bool(aug.get("quantize", True)),
                )
            )
    order = rng.permutation(len(out))
    return [out[i] for i in order]
