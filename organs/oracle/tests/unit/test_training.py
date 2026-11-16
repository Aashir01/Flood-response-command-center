"""Training determinism, manifest verification (ORA-X3) and the size budget (task 4)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from oracle_strategies import make_catalog, make_frames

from stitch_oracle.core.bundle import MANIFEST, BundleError, ModelBundle
from stitch_oracle.core.dataset import design_matrix
from stitch_oracle.core.features import to_wide
from stitch_oracle.core.splits import Split

ORGAN = Path(__file__).resolve().parents[2]
MODELS = ORGAN / "models"


def _train_module() -> ModuleType:
    name = "oracle_train_gbm"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ORGAN / "training" / "train_gbm.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tiny(tmp: Path, resume: bool = False) -> dict[str, Any]:
    tg = _train_module()
    frames = make_frames(3, 2, 4 * 365, start=date(2000, 1, 1))
    cat = make_catalog(2)
    ids = cat.forecast_ids
    codes = {s: i for i, s in enumerate(ids)}
    config = {
        "model_name": "tiny",
        "model_version": "0",
        "seed": 0,
        "quantiles": [0.1, 0.5, 0.9],
        "leads": [1, 2],
        "min_cal": 100,
        "lightgbm": {
            "num_leaves": 7,
            "learning_rate": 0.1,
            "min_child_samples": 20,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "deterministic": True,
            "force_row_wise": True,
            "num_threads": 1,
            "verbosity": -1,
        },
        "n_estimators_max": 15,
        "early_stopping_rounds": 5,
    }
    d = design_matrix(to_wide(frames), cat, ids, codes, config["leads"])
    sp = tg.Splits(
        fit=Split("train_fit", date(2000, 1, 1), date(2001, 12, 31)),
        val=Split("train_val", date(2002, 1, 1), date(2002, 6, 30)),
        refit=Split("refit", date(2000, 1, 1), date(2002, 6, 30)),
        cal=Split("calibration", date(2002, 7, 1), date(2003, 12, 31)),
    )
    manifest: dict[str, Any] = tg.train(
        d,
        ids,
        codes,
        config,
        tmp,
        sp=sp,
        state_path=tmp / "state.json",
        resume=resume,
        log=lambda *_: None,
    )
    return manifest


def test_training_twice_writes_identical_files(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    ma, mb = _tiny(a), _tiny(b)
    assert ma["files"] == mb["files"]
    for name in ma["files"]:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    bundle = ModelBundle.load(a)
    assert bundle.leads == (1, 2) and bundle.sha256 == ma["root_sha256"]


def test_resume_skips_finished_boosters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = _tiny(tmp_path)
    tg = _train_module()
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert len(state["done"]) == 6

    def boom(*_: object) -> None:
        raise AssertionError("a finished booster was refitted")

    monkeypatch.setattr(tg, "fit_booster", boom)
    again = _tiny(tmp_path, resume=True)
    assert again["files"] == first["files"]
    assert tg.config_hash({"a": 1}, {}) != tg.config_hash({"a": 2}, {})


def _copy_bundle(dst: Path) -> Path:
    shutil.copytree(MODELS, dst, ignore=shutil.ignore_patterns("*.md"))
    return dst


def test_committed_bundle_verifies() -> None:
    b = ModelBundle.load(MODELS)
    assert b.leads == tuple(range(1, 15))
    manifest = json.loads((MODELS / MANIFEST).read_text(encoding="utf-8"))
    assert b.sha256 == manifest["root_sha256"]
    assert manifest["target_kind"] == "modeled_glofas"
    assert set(manifest["feature_ranges"]) <= set(manifest["features"])


def test_ora_x3_flipped_byte_refuses_to_load(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path / "m")
    target = root / "lgbm" / "q50_l07.txt.gz"
    data = bytearray(target.read_bytes())
    data[100] ^= 0x01
    target.write_bytes(bytes(data))
    with pytest.raises(BundleError, match="hash mismatch"):
        ModelBundle.load(root)


def test_ora_x3_tampered_manifest_refuses_to_load(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path / "m")
    mpath = root / MANIFEST
    m = json.loads(mpath.read_text(encoding="utf-8"))
    first = sorted(m["files"])[0]
    m["files"][first] = "0" * 64
    mpath.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(BundleError, match="root hash"):
        ModelBundle.load(root)


def test_missing_file_refuses_to_load(tmp_path: Path) -> None:
    root = _copy_bundle(tmp_path / "m")
    (root / "conformity.parquet").unlink()
    with pytest.raises(BundleError, match="missing"):
        ModelBundle.load(root)


def test_bundle_size_budget() -> None:
    files = json.loads((MODELS / MANIFEST).read_text(encoding="utf-8"))["files"]
    sizes = {n: (MODELS / n).stat().st_size for n in files}
    assert sum(sizes.values()) < 10_000_000
    assert max(sizes.values()) < 10_000_000
    assert not list(MODELS.rglob("*.pkl")) and not list(MODELS.rglob("*.pickle"))
