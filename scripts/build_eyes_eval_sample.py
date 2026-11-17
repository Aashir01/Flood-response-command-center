"""Extract the committed Eyes eval sample: 8 chips of the Sen1Floods11 hand-labeled test split.

    uv run python scripts/build_eyes_eval_sample.py [--root data/raw/sen1floods11]

Writes ``evals/eyes/data/sen1floods11_test_sample8.npz`` with, per chip, the S1 bands as the
uint8 codes of the demo-scene quantization (what the organ reads; ``0`` = nodata) and the hand
label as uint8 (``0`` not water, ``1`` water, ``255`` no data). Chips are drawn with seed 0 from
the sorted test-split ids. Sen1Floods11 is CC BY 4.0 (Bonafilia et al. 2020); the README next to
the file carries the attribution. Reads local files only (fetch them first with
``organs/eyes/training/fetch_sen1floods11.py``).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "evals" / "eyes" / "data" / "sen1floods11_test_sample8.npz"
N_CHIPS = 8


def test_ids(root: Path) -> list[str]:
    with (root / "splits" / "flood_test_data.csv").open(newline="") as f:
        return sorted(r[0].strip().replace("_S1Hand.tif", "") for r in csv.reader(f) if r)


def main(argv: list[str] | None = None) -> int:
    import rasterio

    from stitch_eyes.core.preprocess import quantize_db

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=REPO / "data" / "raw" / "sen1floods11")
    args = ap.parse_args(argv)
    ids = test_ids(args.root)
    rng = np.random.default_rng(0)
    pick = sorted(rng.choice(len(ids), size=N_CHIPS, replace=False).tolist())
    chips = [ids[i] for i in pick]
    codes, labels = [], []
    for cid in chips:
        with rasterio.open(args.root / "S1Hand" / f"{cid}_S1Hand.tif") as r:
            codes.append(quantize_db(r.read().astype(np.float32)))
        with rasterio.open(args.root / "LabelHand" / f"{cid}_LabelHand.tif") as r:
            lab = r.read(1)
        labels.append(np.where(lab == -1, 255, lab).astype(np.uint8))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT, chip_ids=np.array(chips), codes=np.stack(codes), labels=np.stack(labels)
    )
    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"{OUT} {OUT.stat().st_size / 1e6:.2f} MB sha256 {sha}")
    print("chips:", ", ".join(chips))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
