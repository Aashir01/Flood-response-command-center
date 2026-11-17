"""Eyes evals (EYE-R7.1, design 3.4): ``python -m evals.run --organ eyes --seed 0 [--fast]``.

Headline: water-class IoU, F1, precision and recall on the Sen1Floods11 **hand-labeled test
split** (90 chips), pixels labelled -1 ignored, pooled over chips, with a 95% bootstrap CI over
chips (1,000 resamples, seeded). The Bolivia split (15 chips, a held-out event) is reported
separately. Sen1Floods11 class 1 is *water* (flood plus permanent), so the metric is "water-class
IoU on flood-event chips". The Sindh demo scene is never part of these numbers (EYE-R7.2).

What is evaluated is the shipped artifact as served: each chip is quantized to the demo-scene
uint8 codes, nodata is median-filled and forced to "not water", and the ONNX model runs through
the organ's own tiling and integer blending (``run_tiles``, tile 256, overlap 32).

Rows on the same chips and pixels:
* ``unet``: the shipped ONNX model (``organs/eyes/models``).
* ``otsu``: Otsu threshold on VH per chip (what the dataset's Otsu labels do).
* ``global_vh``: one VH threshold fitted on the train split (pooled IoU, 0.1 dB grid). The full
  run writes it to ``evals/eyes/fitted_threshold.json``; ``--fast`` reads that file.
* ``vh_fallback``: the organ's fallback ``ThresholdTileModel`` (3 x 3 mean, -20 dB).

Data:
* full (default): the raw dataset from ``STITCH_SEN1FLOODS11_DIR``, else
  ``data/raw/sen1floods11`` (fetch with ``organs/eyes/training/fetch_sen1floods11.py``; on the
  Vultr box the path is ``/srv/data/sen1floods11``). If neither exists, the run falls back to the
  committed sample and says so in every metric's notes.
* ``--fast``: ``evals/eyes/data/sen1floods11_test_sample8.npz``, 8 test chips (3.1 MB, CC BY
  4.0), finishes in seconds. Its numbers are a smoke check, not the headline.

The full run also writes ``evals/results/eyes_report.json`` (per-chip counts, CIs, model SHA,
split names). Checks with targets: the model's test IoU must beat Otsu (gain >= 0) and the
export check's mask agreement must be >= 0.995 (EYE-P5).
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from evals.models import MetricResult

EVALS_EYES = Path(__file__).resolve().parent
REPO = EVALS_EYES.parents[1]
RESULTS_DIR = REPO / "evals" / "results"
SAMPLE = EVALS_EYES / "data" / "sen1floods11_test_sample8.npz"
FITTED = EVALS_EYES / "fitted_threshold.json"
MODEL_DIR = REPO / "organs" / "eyes" / "models"
TILE = 256
BOOT = 1000
SPLIT_FILES = {
    "train": "flood_train_data.csv",
    "test": "flood_test_data.csv",
    "bolivia": "flood_bolivia_data.csv",
}
NOTE = (
    "Sen1Floods11 hand-labeled chips, water class (flood plus permanent), label -1 ignored; "
    "the Sindh demo scene is not part of this number. "
)

U8 = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Chip:
    chip_id: str
    codes: U8  # (2, H, W) demo-scene uint8 codes, 0 = nodata
    label: npt.NDArray[np.int16]  # -1 ignore, 0, 1


def data_root() -> Path | None:
    env = os.environ.get("STITCH_SEN1FLOODS11_DIR")
    for cand in ([Path(env)] if env else []) + [REPO / "data" / "raw" / "sen1floods11"]:
        if (cand / "splits" / SPLIT_FILES["test"]).exists() and (cand / "S1Hand").is_dir():
            return cand
    return None


def split_ids(root: Path, split: str) -> list[str]:
    with (root / "splits" / SPLIT_FILES[split]).open(newline="") as f:
        return [r[0].strip().replace("_S1Hand.tif", "") for r in csv.reader(f) if r]


def load_raw(root: Path, split: str) -> Iterator[Chip]:
    import rasterio

    from stitch_eyes.core.preprocess import quantize_db

    for cid in split_ids(root, split):
        with rasterio.open(root / "S1Hand" / f"{cid}_S1Hand.tif") as r:
            codes = quantize_db(r.read().astype(np.float32))
        with rasterio.open(root / "LabelHand" / f"{cid}_LabelHand.tif") as r:
            label = r.read(1).astype(np.int16)
        yield Chip(cid, codes, label)


def load_sample() -> list[Chip]:
    z = np.load(SAMPLE)
    out = []
    for cid, codes, lab in zip(z["chip_ids"], z["codes"], z["labels"], strict=True):
        lab16 = lab.astype(np.int16)
        label = np.where(lab16 == 255, -1, lab16).astype(np.int16)
        out.append(Chip(str(cid), codes.astype(np.uint8), label))
    return out


def shipped_model() -> tuple[Any, dict[str, Any]]:
    from stitch_eyes.core.infer import OnnxTileModel
    from stitch_eyes.service import MODEL_VERSION

    check = json.loads((MODEL_DIR / "export_check.json").read_text(encoding="utf-8"))
    model = OnnxTileModel(
        MODEL_DIR / check["file"],
        expected_sha256=check["sha256"],
        variant=check["model_variant"],
        version=MODEL_VERSION,
        threads=2,
    )
    return model, check


Predictor = Callable[[Chip], npt.NDArray[np.bool_]]


def predictors(model: Any, global_vh_db: float) -> dict[str, Predictor]:
    from stitch_eyes.core.baseline import otsu_mask
    from stitch_eyes.core.infer import ThresholdTileModel, run_tiles
    from stitch_eyes.core.preprocess import prepare

    fallback = ThresholdTileModel()

    def tiled(m: Any) -> Predictor:
        def f(c: Chip) -> npt.NDArray[np.bool_]:
            p = prepare(c.codes)
            out, _ = run_tiles(p.db, TILE, m)
            res: npt.NDArray[np.bool_] = (out.water > 0) & p.valid
            return res

        return f

    def otsu(c: Chip) -> npt.NDArray[np.bool_]:
        p = prepare(c.codes)
        return otsu_mask(p.db[1], p.valid) & p.valid

    def global_vh(c: Chip) -> npt.NDArray[np.bool_]:
        p = prepare(c.codes)
        res: npt.NDArray[np.bool_] = (p.db[1] < global_vh_db) & p.valid
        return res

    return {
        "unet": tiled(model),
        "otsu": otsu,
        "global_vh": global_vh,
        "vh_fallback": tiled(fallback),
    }


def fit_threshold(root: Path) -> float:
    from stitch_eyes.core.baseline import fit_global_threshold
    from stitch_eyes.core.preprocess import prepare

    vh, labels = [], []
    for c in load_raw(root, "train"):
        try:
            p = prepare(c.codes)
        except ValueError:
            continue
        vh.append(p.db[1])
        labels.append(np.where(p.valid, c.label, -1))
    return fit_global_threshold(vh, labels)


def score(chips: list[Chip], preds: dict[str, Predictor]) -> tuple[dict[str, list[Any]], list[str]]:
    """Per-chip confusion counts per predictor, and the ids of the scored chips.

    Pixels where the S1 chip has no data are ignored for every row; a chip without any valid
    S1 pixel is skipped (it would be all-ignored anyway).
    """
    from stitch_eyes.core.metrics import counts

    out: dict[str, list[Any]] = {k: [] for k in preds}
    ids: list[str] = []
    for c in chips:
        nodata = np.any(c.codes == 0, axis=0)
        if nodata.all():
            continue
        for name, f in preds.items():
            out[name].append(counts(f(c), c.label, extra_ignore=nodata))
        ids.append(c.chip_id)
    return out, ids


def _git_sha() -> str:
    from evals.run import git_sha

    return git_sha()


def run(fast: bool, seed: int) -> list[MetricResult]:
    from stitch_eyes.core.metrics import bootstrap_ci, mean_chip_iou, pooled

    now = datetime.now(UTC)
    sha = _git_sha()
    model, check = shipped_model()
    root = None if fast else data_root()
    fallback_note = ""
    if fast:
        splits: dict[str, list[Chip]] = {"test": load_sample()}
        dataset = {"test": "sen1floods11_test_sample8"}
    elif root is None:
        splits = {"test": load_sample()}
        dataset = {"test": "sen1floods11_test_sample8"}
        fallback_note = (
            "FALLBACK: raw Sen1Floods11 not found (STITCH_SEN1FLOODS11_DIR or "
            "data/raw/sen1floods11); scored on the committed 8-chip sample. "
        )
    else:
        splits = {s: list(load_raw(root, s)) for s in ("test", "bolivia")}
        dataset = {"test": "sen1floods11_test", "bolivia": "sen1floods11_bolivia"}

    if root is not None:
        thr = fit_threshold(root)
        FITTED.write_text(
            json.dumps(
                {
                    "vh_threshold_db": thr,
                    "fitted_on": "sen1floods11 hand-labeled train "
                    "split, pooled water IoU, 0.1 dB grid in -30..-10 dB",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif FITTED.exists():
        thr = float(json.loads(FITTED.read_text(encoding="utf-8"))["vh_threshold_db"])
    else:
        thr = -20.0

    preds = predictors(model, thr)
    metrics: list[MetricResult] = []
    report: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "git_sha": sha,
        "seed": seed,
        "model": {"file": check["file"], "sha256": model.sha256, "variant": model.variant},
        "tile_size": TILE,
        "global_vh_threshold_db": thr,
        "splits": {},
    }

    def add(mid: str, label: str, value: float, ds: str, notes: str = "", **kw: Any) -> None:
        metrics.append(
            MetricResult(
                id=mid,
                label=label,
                value=float(value),
                dataset=ds,
                mode="demo",
                timestamp=now,
                git_sha=sha,
                seed=seed,
                notes=fallback_note + NOTE + notes,
                **kw,
            )
        )

    for split, chips in splits.items():
        ds = dataset[split]
        scored, ids = score(chips, preds)
        rep: dict[str, Any] = {
            "dataset": ds,
            "n_chips": len(chips),
            "n_scored": len(ids),
            "rows": {},
        }
        for name, per_chip in scored.items():
            tot = pooled(per_chip)
            lo, hi = bootstrap_ci(per_chip, "iou", n=BOOT, seed=seed)
            vals = tot.as_dict()
            for k in ("iou", "f1", "precision", "recall"):
                add(
                    f"eyes.{split}.{name}.{k}",
                    f"{split} {name} water {k}",
                    vals[k],
                    ds,
                    f"pooled over {len(per_chip)} chips"
                    + (f"; IoU 95% CI [{lo:.3f}, {hi:.3f}]" if k == "iou" else ""),
                    direction="higher",
                )
            add(
                f"eyes.{split}.{name}.mean_chip_iou",
                f"{split} {name} mean per-chip IoU",
                mean_chip_iou(per_chip),
                ds,
                direction="higher",
            )
            rep["rows"][name] = {
                **vals,
                "iou_ci95": [lo, hi],
                "mean_chip_iou": mean_chip_iou(per_chip),
                "per_chip": [
                    {"chip_id": cid, "tp": k.tp, "fp": k.fp, "fn": k.fn, "tn": k.tn}
                    for cid, k in zip(ids, per_chip, strict=True)
                ],
            }
        if split == "test":
            gain = pooled(scored["unet"]).iou - pooled(scored["otsu"]).iou
            add(
                "eyes.test.unet_minus_otsu.iou",
                "test IoU gain of the shipped model over per-chip Otsu",
                gain,
                ds,
                "check: the shipped model must not be worse than the Otsu baseline",
                target=0.0,
                direction="higher",
            )
        report["splits"][split] = rep

    add(
        "eyes.export.mask_agreement",
        "ONNX vs PyTorch mask agreement (export check, EYE-P5)",
        float(check["mask_agreement"]),
        "sen1floods11_valid_tiles16",
        f"variant {check['variant']}, max abs logit diff {check['max_abs_logit_diff']:.4f}",
        target=0.995,
        direction="higher",
    )
    if not fast and root is not None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / "eyes_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    return metrics
