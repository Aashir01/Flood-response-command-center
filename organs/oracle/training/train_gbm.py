"""Train the Oracle LightGBM quantile models and their CQR calibration (design sections 4, 9).

    uv run python organs/oracle/training/train_gbm.py            # train + calibrate, ~3 min CPU
    uv run python organs/oracle/training/train_gbm.py --resume   # skip boosters already done

Reads only the committed demo Parquet (``data/demo/oracle/``), so it runs offline. For each lead
``h`` in 1..14 and quantile ``q`` in (0.1, 0.5, 0.9): fit on train_fit with early stopping on
train_val (pinball loss), then refit on refit (train_fit + train_val) with the selected number
of trees. Then compute CQR conformity scores on the calibration split (2012-2016) and write:

* ``models/lgbm/q<qq>_l<hh>.txt.gz``  LightGBM text models, gzip with mtime 0 (no pickle)
* ``models/conformity.parquet``     sorted scores per (station, lead)
* ``models/manifest.json``          SHA-256 per file, root hash, features, per-feature training
                                    ranges, station codes, config hash, n_trees, git commit

Seed 0, ``deterministic=True``, one thread: a rerun on the same data writes byte-identical model
files. ``--resume`` keeps a progress file in ``data/raw/oracle/train_state.json`` (git-ignored)
keyed by the config hash, so an interrupted run (Colab disconnect) loses at most one booster.
The target is modeled GloFAS discharge; nothing here is a gauge record.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ORGAN = HERE.parent
REPO = ORGAN.parents[1]
sys.path.insert(0, str(ORGAN / "src"))

from stitch_oracle.core import conformal  # noqa: E402
from stitch_oracle.core.bundle import (  # noqa: E402
    CONFORMITY,
    MANIFEST,
    file_sha256,
    model_file,
    root_hash,
)
from stitch_oracle.core.dataset import Design, design_matrix, feature_ranges  # noqa: E402
from stitch_oracle.core.features import FEATURES, STATION_FEATURE, to_wide  # noqa: E402
from stitch_oracle.core.quantiles import repair  # noqa: E402
from stitch_oracle.core.splits import (  # noqa: E402
    CALIBRATION,
    REFIT,
    TRAIN_FIT,
    TRAIN_VAL,
    Split,
    assert_disjoint,
)
from stitch_oracle.data.loader import DISCHARGE, SUBDIR, WEATHER, demo_dir, load_demo  # noqa: E402

STATE = REPO / "data" / "raw" / "oracle" / "train_state.json"


@dataclass(frozen=True)
class Splits:
    fit: Split = TRAIN_FIT
    val: Split = TRAIN_VAL
    refit: Split = REFIT
    cal: Split = CALIBRATION


def config_hash(config: Mapping[str, Any], data_hashes: Mapping[str, str]) -> str:
    blob = json.dumps(
        {"config": config, "data": dict(data_hashes), "features": list(FEATURES)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _params(config: Mapping[str, Any], q: float) -> dict[str, Any]:
    p = dict(config["lightgbm"])
    p.update(objective="quantile", alpha=q, metric="quantile", seed=int(config["seed"]))
    p.update(
        bagging_seed=int(config["seed"]),
        feature_fraction_seed=int(config["seed"]),
        data_random_seed=int(config["seed"]),
    )
    return p


def _dataset(d: Design, j: int, mask: np.ndarray, reference: Any = None) -> lgb.Dataset:
    cat = [FEATURES.index(STATION_FEATURE)]
    return lgb.Dataset(
        d.x[mask],
        label=d.y[mask, j],
        feature_name=list(FEATURES),
        categorical_feature=cat,
        reference=reference,
        free_raw_data=False,
    )


def fit_booster(
    d: Design, lead: int, q: float, config: Mapping[str, Any], sp: Splits
) -> tuple[lgb.Booster, int, float]:
    """Early stopping on train_val, then refit on refit with the chosen tree count."""
    j = d.leads.index(lead)
    params = _params(config, q)
    m_fit, m_val = d.split_mask(sp.fit, lead), d.split_mask(sp.val, lead)
    dtrain = _dataset(d, j, m_fit)
    dval = _dataset(d, j, m_val, reference=dtrain)
    probe = lgb.train(
        params,
        dtrain,
        num_boost_round=int(config["n_estimators_max"]),
        valid_sets=[dval],
        callbacks=[lgb.early_stopping(int(config["early_stopping_rounds"]), verbose=False)],
    )
    n_trees = max(int(probe.best_iteration or config["n_estimators_max"]), 1)
    val_loss = float(probe.best_score["valid_0"]["quantile"])
    m_refit = d.split_mask(sp.refit, lead)
    final = lgb.train(params, _dataset(d, j, m_refit), num_boost_round=n_trees)
    return final, n_trees, val_loss


def calibration_scores(
    d: Design, boosters: Mapping[tuple[float, int], lgb.Booster], sp: Splits
) -> pd.DataFrame:
    """CQR scores on the calibration split per (station, lead), from repaired quantiles."""
    rows = []
    for lead in d.leads:
        j = d.leads.index(lead)
        m = d.split_mask(sp.cal, lead)
        x = d.x[m]
        raw = np.stack(
            [boosters[(q, lead)].predict(x, num_threads=1) for q in (0.1, 0.5, 0.9)], axis=-1
        )
        rep, _ = repair(raw)
        s = conformal.scores(d.y[m, j], rep[:, 0], rep[:, 2])
        for sid in sorted(set(d.station_ids[m])):
            sel = d.station_ids[m] == sid
            for v in np.sort(s[sel]):
                rows.append((sid, lead, float(v)))
    df = pd.DataFrame(rows, columns=["station_id", "lead", "score"])
    df["lead"] = df["lead"].astype("int16")
    return df


def git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
        )
        return res.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _load_state(chash: str, path: Path) -> dict[str, Any]:
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("config_hash") == chash:
            return dict(state)
    return {"config_hash": chash, "done": {}}


def train(
    d: Design,
    station_ids: Sequence[str],
    codes: Mapping[str, int],
    config: Mapping[str, Any],
    out: Path,
    *,
    sp: Splits | None = None,
    data_hashes: Mapping[str, str] | None = None,
    resume: bool = False,
    state_path: Path | None = None,
    log: Any = print,
) -> dict[str, Any]:
    """Fit every booster, write models, conformity scores and the manifest. Returns the
    manifest."""
    sp = sp or Splits()
    assert_disjoint((sp.fit, sp.val, sp.cal))
    chash = config_hash(config, data_hashes or {})
    state_file = state_path or STATE
    state: dict[str, Any] = (
        _load_state(chash, state_file) if resume else {"config_hash": chash, "done": {}}
    )
    (out / "lgbm").mkdir(parents=True, exist_ok=True)
    boosters: dict[tuple[float, int], lgb.Booster] = {}
    n_trees: dict[str, int] = {}
    val_loss: dict[str, float] = {}
    for lead in config["leads"]:
        for q in config["quantiles"]:
            name = model_file(float(q), int(lead))
            path = out / name
            done = state["done"].get(name)
            if resume and done and path.is_file() and file_sha256(path.read_bytes()) == done["sha"]:
                text = gzip.decompress(path.read_bytes()).decode("utf-8")
                boosters[(float(q), int(lead))] = lgb.Booster(model_str=text)
                n_trees[name], val_loss[name] = int(done["n_trees"]), float(done["val_loss"])
                continue
            t0 = time.perf_counter()
            b, n, loss = fit_booster(d, int(lead), float(q), config, sp)
            text = b.model_to_string()
            blob = gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)
            path.write_bytes(blob)
            boosters[(float(q), int(lead))] = lgb.Booster(model_str=text)
            n_trees[name], val_loss[name] = n, loss
            state["done"][name] = {"sha": file_sha256(blob), "n_trees": n, "val_loss": loss}
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")
            log(f"  {name}: {n} trees, val pinball {loss:.5f} ({time.perf_counter() - t0:.1f} s)")

    cf = calibration_scores(d, boosters, sp)
    cf.to_parquet(out / CONFORMITY, index=False, compression="zstd", compression_level=19)
    files = {
        str(p.relative_to(out).as_posix()): file_sha256(p.read_bytes())
        for p in sorted((out / "lgbm").glob("*.txt.gz"))
    }
    files[CONFORMITY] = file_sha256((out / CONFORMITY).read_bytes())
    m_refit = np.zeros(len(d), dtype=bool)
    for lead in config["leads"]:
        m_refit |= d.split_mask(sp.refit, int(lead))
    n_cal = cf.groupby(["station_id", "lead"]).size()
    manifest: dict[str, Any] = {
        "name": config["model_name"],
        "version": config["model_version"],
        "target": "ln(Q[t+h]+1) - ln(Q[t]+1), Q = modeled GloFAS discharge (m3/s)",
        "target_kind": "modeled_glofas",
        "quantiles": list(config["quantiles"]),
        "leads": list(config["leads"]),
        "features": list(FEATURES),
        "categorical": [STATION_FEATURE],
        "station_codes": dict(codes),
        "stations": list(station_ids),
        "feature_ranges": feature_ranges(d.x[m_refit]),
        "min_cal": int(config["min_cal"]),
        "n_calibration": {f"{s}:{h}": int(v) for (s, h), v in n_cal.items()},
        "n_trees": n_trees,
        "val_pinball": val_loss,
        "splits": {
            s.name: [s.start.isoformat(), s.end.isoformat()]
            for s in (sp.fit, sp.val, sp.refit, sp.cal)
        },
        "config_hash": chash,
        "data_sha256": dict(data_hashes or {}),
        "lightgbm_version": lgb.__version__,
        "git_commit": git_commit(),
        "files": files,
        "root_sha256": root_hash(files),
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--config", type=Path, default=HERE / "config.yaml")
    ap.add_argument("--out", type=Path, default=ORGAN / "models")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    data = load_demo()
    base = demo_dir() / SUBDIR
    hashes = {n: file_sha256((base / n).read_bytes()) for n in (DISCHARGE, WEATHER)}
    station_ids = data.catalog.forecast_ids
    codes = {sid: i for i, sid in enumerate(station_ids)}
    t0 = time.perf_counter()
    d = design_matrix(
        to_wide(data.frames),
        data.catalog,
        station_ids,
        codes,
        config["leads"],
        require=config.get("require_feature"),
    )
    print(f"design matrix: {len(d)} rows x {d.x.shape[1]} features, stations {station_ids}")
    manifest = train(
        d, station_ids, codes, config, args.out, data_hashes=hashes, resume=args.resume
    )
    size = sum((args.out / f).stat().st_size for f in manifest["files"])
    print(
        f"done in {time.perf_counter() - t0:.0f} s; bundle {size / 1e6:.2f} MB; "
        f"root {manifest['root_sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
