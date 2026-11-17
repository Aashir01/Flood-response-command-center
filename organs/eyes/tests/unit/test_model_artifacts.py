"""Committed model and scene artifacts (design 3.5, task 4, 14): EYE-P5, EYE-X10."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from stitch_common.organs.eyes import ModelVariant
from stitch_eyes.core.infer import file_sha256
from stitch_eyes.settings import ORGAN_DIR, REPO

MODELS = ORGAN_DIR / "models"
CHECK = json.loads((MODELS / "export_check.json").read_text(encoding="utf-8"))
SIZE_LIMIT = 50_000_000
SCENE_LIMIT = 25 * 1024 * 1024


def test_export_check_hash_matches_the_committed_model() -> None:
    path = MODELS / CHECK["file"]
    assert path.stat().st_size == CHECK["bytes"]
    assert file_sha256(path) == CHECK["sha256"]


def test_eye_x10_model_and_scene_sizes() -> None:
    assert (MODELS / CHECK["file"]).stat().st_size < SIZE_LIMIT
    cat = json.loads((REPO / "data" / "demo" / "eyes" / "catalog.json").read_text("utf-8"))
    for s in cat["scenes"]:
        p = REPO / "data" / "demo" / "eyes" / s["file"]
        assert p.stat().st_size < SCENE_LIMIT
        assert file_sha256(p) == s["sha256"]
        perm = REPO / "data" / "demo" / "eyes" / s["perm_water"]["file"]
        assert perm.stat().st_size < 1_000_000 and file_sha256(perm) == s["perm_water"]["sha256"]


def test_eye_p5_export_tolerances() -> None:
    """fp32: max abs logit difference <= 1e-4. fp16/int8: mask agreement >= 99.5% and the
    validation IoU difference <= 1.0 point (design 3.5)."""
    if CHECK["variant"] == "fp32":
        assert CHECK["max_abs_logit_diff"] <= 1e-4
    else:
        assert CHECK["mask_agreement"] >= 0.995
        assert CHECK["val_iou_diff_points"] <= 1.0
    assert CHECK["n_tiles"] >= 16 and CHECK["opset"] == 17


def test_shipped_variant_has_a_contract_label() -> None:
    from typing import get_args

    assert CHECK["model_variant"] in get_args(ModelVariant)


def test_preprocess_constants_come_from_the_full_train_split() -> None:
    pre = json.loads((MODELS / "preprocess.json").read_text("utf-8"))
    assert pre["clip_db"] == [-35.0, 5.0] and pre["channels"] == ["VV", "VH", "VV-VH"]
    assert "(252 chips)" in pre["computed_on"]


def test_training_run_log_is_committed_and_matches_the_export() -> None:
    runs = sorted((ORGAN_DIR / "training" / "runs").glob("*.json"))
    assert runs, "training/runs/<profile>.json is missing"
    logs = [json.loads(p.read_text("utf-8")) for p in runs]
    # The shipped run is the log whose best epoch is the exported checkpoint and whose best
    # validation IoU equals the PyTorch validation IoU the export recomputed (same code, same
    # 89 chips), so an older log with the same best epoch cannot match by accident.
    shipped = [
        g
        for g in logs
        if g.get("best_epoch") == CHECK["checkpoint_epoch"]
        and abs(g["best_val_iou"] - CHECK["torch_val_iou"]) <= 1e-6
    ]
    assert len(shipped) == 1, "exactly one run log must match the exported checkpoint"
    log = shipped[0]
    assert log["n_train_chips"] == 252 and log["n_valid_chips"] == 89
    assert all("val_iou" in h for h in log["history"] if h["epoch"] == log["best_epoch"])


@pytest.mark.skipif(
    not os.environ.get("STITCH_EYES_CKPT"), reason="set STITCH_EYES_CKPT to a best.pt to recompute"
)
def test_eye_p5_recompute_against_pytorch() -> None:  # pragma: no cover - training env only
    import numpy as np

    torch = pytest.importorskip("torch")
    import sys

    sys.path.insert(0, str(ORGAN_DIR / "training"))
    import yaml
    from model import build  # type: ignore[import-not-found]

    from stitch_eyes.core.infer import OnnxTileModel

    cfg = yaml.safe_load((ORGAN_DIR / "training" / "config.yaml").read_text())
    pre = json.loads((MODELS / "preprocess.json").read_text("utf-8"))
    m = build(cfg, pre["mean"], pre["std"], pretrained=False)
    ck = torch.load(Path(os.environ["STITCH_EYES_CKPT"]), map_location="cpu", weights_only=False)
    m.load_state_dict(ck["model"])
    m.eval()
    onnx = OnnxTileModel(MODELS / CHECK["file"], CHECK["sha256"], CHECK["model_variant"], "t")
    rng = np.random.default_rng(0)
    x = rng.uniform(-25, -5, size=(2, 256, 256)).astype(np.float32)
    with torch.no_grad():
        zt = m(torch.from_numpy(x)[None])[0, 0].numpy()
    zo = onnx.predict_logits(x)
    assert float(((zt > 0) == (zo > 0)).mean()) >= 0.995
