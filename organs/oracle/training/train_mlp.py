"""Stretch comparison (oracle task 17): a small PyTorch quantile MLP on the same features, splits
and target as the shipped LightGBM model. The MLP is **not shipped**; its scores go to the eval
table only (``mlp_results.json``, read by ``evals/oracle``).

    uv run --with torch python organs/oracle/training/train_mlp.py --seed 0

CPU only, about 1 to 3 minutes on the laptop (no GPU needed; also runs on the free Colab CPU
runtime). Protocol:

* Inputs: the 40 features of ``core.features``; NaN slots (missing upstream, short history) are set
  to 0 with a missing-indicator column; standardised with train_fit statistics; the station code
  is one-hot.
* Output: 14 leads x 3 quantiles of the log-ratio target, pinball loss, Adam, early stopping on
  train_val. Unlike the GBM there is no refit on train_fit + train_val (stated in the results).
* Calibration: the same CQR as the GBM (scores on 2012-2016 per station and lead), then the same
  repair and back-transform (``core.forecast.calibrate_batch``).
* Scores on test (2017-2023) and the 2022 stress season for both models on identical rows.

The target is modeled river discharge (GloFAS via Open-Meteo), never a gauge record.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ORGAN = HERE.parent
sys.path.insert(0, str(ORGAN / "src"))

from stitch_oracle.core import conformal  # noqa: E402
from stitch_oracle.core import metrics as m  # noqa: E402
from stitch_oracle.core.bundle import ModelBundle  # noqa: E402
from stitch_oracle.core.dataset import Design, design_matrix  # noqa: E402
from stitch_oracle.core.features import FEATURES, STATION_FEATURE, to_wide  # noqa: E402
from stitch_oracle.core.forecast import calibrate_batch  # noqa: E402
from stitch_oracle.core.quantiles import repair  # noqa: E402
from stitch_oracle.core.splits import CALIBRATION, STRESS, TEST, TRAIN_FIT, TRAIN_VAL  # noqa: E402
from stitch_oracle.data.loader import load_demo  # noqa: E402

OUT = HERE / "mlp_results.json"
TAUS = (0.1, 0.5, 0.9)


def _inputs(d: Design, mean: np.ndarray, std: np.ndarray, n_st: int) -> np.ndarray:
    si = FEATURES.index(STATION_FEATURE)
    x = np.delete(d.x, si, axis=1)
    miss = ~np.isfinite(x)
    z = np.where(miss, 0.0, (np.nan_to_num(x) - mean) / std)
    onehot = np.eye(n_st)[d.x[:, si].astype(int)]
    return np.hstack([z, miss.astype("float64"), onehot]).astype("float32")


def _all_leads(d: Design, split: Any) -> np.ndarray:
    mask = np.ones(len(d), dtype=bool)
    for h in d.leads:
        mask &= d.split_mask(split, h)
    return mask


def main(argv: list[str] | None = None) -> int:
    import torch

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--patience", type=int, default=15)
    args = ap.parse_args(argv)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)

    data = load_demo()
    bundle = ModelBundle.load(ORGAN / "models")
    stations = tuple(bundle.manifest["stations"])
    d = design_matrix(
        to_wide(data.frames), data.catalog, stations, bundle.station_codes, bundle.leads
    )
    m_fit, m_val = _all_leads(d, TRAIN_FIT), _all_leads(d, TRAIN_VAL)
    si = FEATURES.index(STATION_FEATURE)
    xf = np.delete(d.x[m_fit], si, axis=1)
    mean = np.nanmean(xf, axis=0)
    std = np.nanstd(xf, axis=0)
    std = np.where(np.isfinite(std) & (std > 0), std, 1.0)
    mean = np.where(np.isfinite(mean), mean, 0.0)
    x_all = _inputs(d, mean, std, len(stations))
    y_all = d.y.astype("float32")
    n_in, n_out = x_all.shape[1], len(d.leads) * 3

    net = torch.nn.Sequential(
        torch.nn.Linear(n_in, 128),
        torch.nn.ReLU(),
        torch.nn.Linear(128, 64),
        torch.nn.ReLU(),
        torch.nn.Linear(64, n_out),
    )
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    taus = torch.tensor(TAUS, dtype=torch.float32).repeat(len(d.leads))

    def loss_fn(x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        pred = net(x)
        target = y.repeat_interleave(3, dim=1)
        diff = target - pred
        return torch.mean(torch.maximum(taus * diff, (taus - 1.0) * diff))

    xt, yt = torch.from_numpy(x_all[m_fit]), torch.from_numpy(y_all[m_fit])
    xv, yv = torch.from_numpy(x_all[m_val]), torch.from_numpy(y_all[m_val])
    gen = torch.Generator().manual_seed(args.seed)
    best, best_state, stale, epochs = float("inf"), None, 0, 0
    t0 = time.perf_counter()
    for epoch in range(args.epochs):
        net.train()
        perm = torch.randperm(xt.shape[0], generator=gen)
        for i in range(0, xt.shape[0], 512):
            idx = perm[i : i + 512]
            opt.zero_grad()
            loss = loss_fn(xt[idx], yt[idx])
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            val = float(loss_fn(xv, yv))
        if val < best - 1e-6:
            best, stale, epochs = val, 0, epoch + 1
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            stale += 1
            if stale >= args.patience:
                break
    assert best_state is not None
    net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        raw_mlp = net(torch.from_numpy(x_all)).numpy().astype("float64")
    raw_mlp = raw_mlp.reshape(len(d), len(d.leads), 3)
    train_s = time.perf_counter() - t0

    def calibrated(raw: np.ndarray) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        acc: dict[str, dict[str, list[np.ndarray]]] = {}
        for j, h in enumerate(d.leads):
            mc = d.split_mask(CALIBRATION, h)
            rep, _ = repair(raw[mc, j, :])
            sc = conformal.scores(d.y[mc, j], rep[:, 0], rep[:, 2])
            qh = {
                s: conformal.qhat(np.sort(sc[d.station_ids[mc] == s]), 0.8).value for s in stations
            }
            for split in (TEST, STRESS):
                ms = d.split_mask(split, h)
                sids = d.station_ids[ms]
                q = calibrate_batch(raw[ms, j, :], d.q_t[ms], np.array([qh[s] for s in sids]))
                y = np.expm1(np.log1p(d.q_t[ms]) + d.y[ms, j])
                a = acc.setdefault(split.name, {"y": [], "q": []})
                a["y"].append(y)
                a["q"].append(q)
        for name, a in acc.items():
            y, q = np.concatenate(a["y"]), np.vstack(a["q"])
            out[name] = {
                "crps": float(np.mean(m.crps_q(y, q[:, 0], q[:, 1], q[:, 2]))),
                "coverage_80": m.coverage(y, q[:, 0], q[:, 2]),
                "width_80_m3s": m.width(q[:, 0], q[:, 2]),
                "n": int(y.size),
            }
        return out

    raw_gbm = bundle.predict(d.x)
    res_mlp, res_gbm = calibrated(raw_mlp), calibrated(raw_gbm)
    doc = {
        "target_kind": "modeled_glofas",
        "target_label": "Modeled river discharge (GloFAS via Open-Meteo)",
        "shipped": False,
        "seed": args.seed,
        "torch_version": torch.__version__,
        "architecture": f"MLP {n_in}-128-64-{n_out}, ReLU, pinball loss, Adam lr 1e-3, batch 512",
        "epochs_selected": epochs,
        "train_seconds": round(train_s, 1),
        "protocol_note": (
            "trained on train_fit (1997-2008), early stopping on train_val (2009-2011), no refit; "
            "CQR on 2012-2016 per station and lead with the 0.8 band (station's own scores); "
            "scored on identical rows for both models; CRPS is the quantile approximation"
        ),
        "results": {
            split: {
                "mlp": res_mlp[split],
                "gbm": res_gbm[split],
                "crps_skill_mlp_vs_gbm": 1.0 - res_mlp[split]["crps"] / res_gbm[split]["crps"],
            }
            for split in res_mlp
        },
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(doc["results"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
