"""Oracle evals (ORA-R7, ORA-P7 eval, ORA-P8): ``python -m evals.run --organ oracle --seed 0
[--fast]``.

The target is **modeled** river discharge (GloFAS via Open-Meteo), never a gauge record. Every
metric's ``notes`` starts with ``target_kind=modeled_glofas`` and the detailed report
``evals/results/oracle_report.json`` carries ``target_kind`` and ``target_label`` at the top and in
every by-lead record (ORA-P8). No observed (gauge) validation was performed (ORA-R9.2): the report
says ``observed_validation: "not performed"``.

Protocol (design section 10), committed demo data only, no network:

* Rows ``(station, as_of)`` from the same design matrix that training uses; the committed model
  bundle predicts raw quantiles, which go through the pipeline's repair, CQR and back-transform
  (``core.forecast.calibrate_batch``, equal to ``forecast_river`` up to rounding, tested).
* Test: ``as_of`` 2017-01-01..2023-12-31 with the target date inside (purge). Stress: the 2022
  flood season, ``as_of`` 2022-06-01..2022-10-31. ``--fast``: every 7th day, two stations.
* Metrics in m3/s by lead: pinball at 0.1/0.5/0.9 (the 0.8-calibrated bounds and the median),
  quantile-approximated CRPS (``2 sum w_tau pinball_tau``, a coarse surrogate), coverage of the
  0.5/0.8/0.9 intervals vs nominal, mean width (m3/s and relative to the median), Brier score of
  the danger-threshold exceedance (modeled 5-year return level, an assumption).
* Baselines: persistence (point), persistence with empirical log-ratio quantiles per lead from
  the refit split (1997-2011), and day-of-year climatology (+-15 days, refit years, per station).
* Checks: ORA-P7 (test coverage >= nominal - 0.05 for 0.5, 0.8, 0.9), lead widening (mean relative
  0.8 width non-decreasing in lead within 5%). Stress coverage is reported, not tuned on.
* Uncertainty of coverage: a month-block bootstrap (seeded by ``seed``) gives a 90% interval,
  because daily errors are autocorrelated.
* Stretch (task 16): a Mondrian variant (scores split by monsoon Jun-Sep vs the rest of the year)
  is computed for comparison only. It is not adopted: the only data not used to fit the shipped
  models are the calibration and test years, so choosing it would tune on the test period.
* Stretch (task 17): the PyTorch quantile MLP scores from the committed
  ``organs/oracle/training/mlp_results.json`` (``train_mlp.py``) are added as comparison metrics.
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from evals.models import MetricResult

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
MLP_RESULTS = (
    Path(__file__).resolve().parents[2] / "organs" / "oracle" / "training" / "mlp_results.json"
)
TARGET_KIND = "modeled_glofas"
TARGET_LABEL = "Modeled river discharge (GloFAS via Open-Meteo)"
COVERAGES = (0.5, 0.8, 0.9)
P7_TOL = 0.05
WIDEN_TOL = 0.05
FAST_STATIONS = ("indus-guddu", "indus-sukkur")
FAST_STEP = 7
BOOT = 200
KEY_LEADS = (1, 3, 7, 14)
NOTE = f"target_kind={TARGET_KIND} ({TARGET_LABEL}). "
CRPS_NOTE = (
    "CRPS is the quantile approximation 2*sum(w*pinball) over tau 0.1/0.5/0.9 with weights "
    "0.3/0.4/0.3; a coarse surrogate, comparable only between forecasts scored the same way."
)


def _git_sha() -> str:
    from evals.run import git_sha

    return git_sha()


def _metrics_block(
    y: np.ndarray, q: np.ndarray, thr: np.ndarray | None, p_exc: np.ndarray | None
) -> dict[str, float]:
    from stitch_oracle.core import metrics as m

    out = {
        "pinball_q10": float(np.mean(m.pinball(y, q[:, 0], 0.1))),
        "pinball_q50": float(np.mean(m.pinball(y, q[:, 1], 0.5))),
        "pinball_q90": float(np.mean(m.pinball(y, q[:, 2], 0.9))),
        "crps": float(np.mean(m.crps_q(y, q[:, 0], q[:, 1], q[:, 2]))),
        "coverage_80": m.coverage(y, q[:, 0], q[:, 2]),
        "width_80_m3s": m.width(q[:, 0], q[:, 2]),
        "width_80_rel": float(np.mean((q[:, 2] - q[:, 0]) / np.maximum(q[:, 1], 1.0))),
        "width_80_rel_median": float(np.median((q[:, 2] - q[:, 0]) / np.maximum(q[:, 1], 1.0))),
        "mae_p50": float(np.mean(np.abs(y - q[:, 1]))),
        "n": float(y.size),
    }
    if thr is not None and p_exc is not None:
        out["brier"] = m.brier(p_exc, y > thr)
        out["event_rate"] = float(np.mean(y > thr))
    return out


def _mlp_results() -> dict[str, Any] | None:
    """Committed output of ``organs/oracle/training/train_mlp.py`` (stretch task 17), if any."""
    if not MLP_RESULTS.is_file():
        return None
    doc: dict[str, Any] = json.loads(MLP_RESULTS.read_text(encoding="utf-8"))
    return doc


def _non_decreasing(values: list[float]) -> bool:
    """Each value is at least the previous one, within the relative tolerance."""
    return all(b >= a * (1.0 - WIDEN_TOL) for a, b in itertools.pairwise(values))


def _boot_ci(hit: np.ndarray, months: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """90% month-block bootstrap interval of a hit rate."""
    if hit.size == 0:
        return float("nan"), float("nan")
    keys, inv = np.unique(months, return_inverse=True)
    sums = np.bincount(inv, weights=hit.astype("float64"), minlength=keys.size)
    counts = np.bincount(inv, minlength=keys.size).astype("float64")
    stats = []
    for _ in range(BOOT):
        pick = rng.integers(0, keys.size, keys.size)
        stats.append(sums[pick].sum() / counts[pick].sum())
    lo, hi = np.quantile(stats, [0.05, 0.95])
    return float(lo), float(hi)


def evaluate(fast: bool, seed: int) -> dict[str, Any]:
    """Run the protocol and return the report (also used by tests)."""
    from stitch_oracle.core import baselines as bl
    from stitch_oracle.core import conformal
    from stitch_oracle.core.bundle import ModelBundle
    from stitch_oracle.core.dataset import design_matrix
    from stitch_oracle.core.exceedance import p_exceed_many
    from stitch_oracle.core.features import FEATURES, to_wide
    from stitch_oracle.core.forecast import calibrate_batch
    from stitch_oracle.core.quantiles import repair
    from stitch_oracle.core.splits import CALIBRATION, REFIT, STRESS, TEST
    from stitch_oracle.data.loader import load_demo
    from stitch_oracle.service import DEFAULT_MODELS

    rng = np.random.default_rng(seed)
    data = load_demo()
    bundle = ModelBundle.load(DEFAULT_MODELS)
    stations = tuple(FAST_STATIONS if fast else bundle.manifest["stations"])
    wide = to_wide(data.frames)
    d = design_matrix(wide, data.catalog, stations, bundle.station_codes, bundle.leads)
    ordinal = np.array([t.toordinal() for t in d.dates])
    sub = (ordinal % FAST_STEP == 0) if fast else np.ones(len(d), dtype=bool)
    in_test = np.array([TEST.start <= t <= TEST.end for t in d.dates]) & sub
    in_cal = np.array([CALIBRATION.start <= t <= CALIBRATION.end for t in d.dates])
    raw_test = np.full((len(d), len(bundle.leads), 3), np.nan)
    raw_test[in_test] = bundle.predict(d.x[in_test])
    raw_cal = np.full((len(d), len(bundle.leads), 3), np.nan)
    raw_cal[in_cal] = bundle.predict(d.x[in_cal])
    monsoon = d.x[:, FEATURES.index("monsoon")] > 0.5
    thr_by_station = {s: data.catalog.get(s).threshold()[0] for s in stations}  # type: ignore[union-attr]
    clim = {}
    for sid in stations:
        ref = [t for t in wide.q.index if REFIT.contains(t)]
        clim[sid] = bl.climatology_table(ref, wide.q.loc[ref, sid].to_numpy("float64"))

    by_lead: list[dict[str, Any]] = []
    by_station: list[dict[str, Any]] = []
    pooled: dict[str, dict[str, list[np.ndarray]]] = {}

    def add(split: str, name: str, key: str, arr: np.ndarray) -> None:
        pooled.setdefault(f"{split}:{name}", {}).setdefault(key, []).append(arr)

    for j, h in enumerate(bundle.leads):
        m_ref = d.split_mask(REFIT, h)
        qy = bl.logratio_quantiles(d.y[m_ref, j])
        # Mondrian scores (stretch): calibration rows by stratum
        m_cal = d.split_mask(CALIBRATION, h)
        rep_cal, _ = repair(raw_cal[m_cal, j, :])
        sc = conformal.scores(d.y[m_cal, j], rep_cal[:, 0], rep_cal[:, 2])
        mond = {
            (sid, flag): np.sort(sc[(d.station_ids[m_cal] == sid) & (monsoon[m_cal] == flag)])
            for sid in stations
            for flag in (False, True)
        }
        for split in (TEST, STRESS):
            m = d.split_mask(split, h) & sub
            if not m.any():
                continue
            sids = d.station_ids[m]
            q_t = d.q_t[m]
            y = np.expm1(np.log1p(q_t) + d.y[m, j])
            raw = raw_test[m, j, :]
            if np.isnan(raw).any():
                raise RuntimeError("missing test prediction")
            qhat = {c: np.empty(sids.size) for c in COVERAGES}
            qhat_mond = np.empty(sids.size)
            q_clim = np.empty((sids.size, 3))
            tdates = np.array([t + timedelta(days=h) for t in d.dates[m]], dtype=object)
            mon = monsoon[m]
            for sid in stations:
                sel = sids == sid
                for c in COVERAGES:
                    qhat[c][sel] = bundle.conformity.lookup(sid, h, c).value
                for flag in (False, True):
                    qhat_mond[sel & (mon == flag)] = conformal.qhat(mond[(sid, flag)], 0.8).value
                q_clim[sel] = bl.climatology(clim[sid], list(tdates[sel]))
            fc = {c: calibrate_batch(raw, q_t, qhat[c]) for c in COVERAGES}
            q80 = fc[0.8]
            q_mond = calibrate_batch(raw, q_t, qhat_mond)
            forecasts = {
                "model": q80,
                "persistence": bl.persistence_point(q_t),
                "persistence_prob": bl.persistence_prob(q_t, qy),
                "climatology": q_clim,
            }
            thr = np.array([thr_by_station[s] or np.inf for s in sids])
            rec: dict[str, Any] = {
                "split": split.name,
                "lead": h,
                "target_kind": TARGET_KIND,
                "target_label": TARGET_LABEL,
            }
            for name, q in forecasts.items():
                if name == "persistence":
                    p_exc = (q_t > thr).astype("float64")
                else:
                    p_exc = p_exceed_many(q[:, 0], q[:, 1], q[:, 2], thr)
                block = _metrics_block(y, q, thr, p_exc)
                rec[name] = block
                add(split.name, name, "y", y)
                add(split.name, name, "q", q)
                add(split.name, name, "p", p_exc)
                add(split.name, name, "thr", thr)
            for c in COVERAGES:
                hit = (y >= fc[c][:, 0]) & (y <= fc[c][:, 2])
                rec["model"][f"coverage_{round(c * 100)}"] = float(hit.mean())
                add(split.name, f"hit{round(c * 100)}", "hit", hit)
            add(split.name, "hit80", "month", np.array([t.year * 12 + t.month for t in d.dates[m]]))
            rec["model"]["coverage_80_mondrian"] = float(
                np.mean((y >= q_mond[:, 0]) & (y <= q_mond[:, 2]))
            )
            add(split.name, "mondrian", "hit", (y >= q_mond[:, 0]) & (y <= q_mond[:, 2]))
            by_lead.append(rec)
            for sid in stations:
                s_m = sids == sid
                if not s_m.any():
                    continue
                row: dict[str, Any] = {
                    "split": split.name,
                    "lead": h,
                    "station_id": sid,
                    "target_kind": TARGET_KIND,
                    "n": int(s_m.sum()),
                }
                for name, q in forecasts.items():
                    from stitch_oracle.core import metrics as mm

                    row[f"crps_{name}"] = float(
                        np.mean(mm.crps_q(y[s_m], q[s_m, 0], q[s_m, 1], q[s_m, 2]))
                    )
                row["coverage_80"] = float(
                    np.mean((y[s_m] >= q80[s_m, 0]) & (y[s_m] <= q80[s_m, 2]))
                )
                by_station.append(row)

    overall: dict[str, Any] = {}
    for split in (TEST, STRESS):
        blk: dict[str, Any] = {}
        for name in ("model", "persistence", "persistence_prob", "climatology"):
            parts = pooled.get(f"{split.name}:{name}")
            if not parts:
                continue
            y = np.concatenate(parts["y"])
            q = np.vstack(parts["q"])
            blk[name] = _metrics_block(
                y, q, np.concatenate(parts["thr"]), np.concatenate(parts["p"])
            )
        if not blk:
            continue
        months = np.concatenate(pooled[f"{split.name}:hit80"]["month"])
        for c in COVERAGES:
            hit = np.concatenate(pooled[f"{split.name}:hit{round(c * 100)}"]["hit"])
            blk["model"][f"coverage_{round(c * 100)}"] = float(hit.mean())
            lo, hi = _boot_ci(hit, months, rng)
            blk["model"][f"coverage_{round(c * 100)}_ci90"] = [lo, hi]
        blk["model"]["coverage_80_mondrian"] = float(
            np.concatenate(pooled[f"{split.name}:mondrian"]["hit"]).mean()
        )
        for base in ("persistence", "persistence_prob", "climatology"):
            blk["model"][f"crps_skill_vs_{base}"] = 1.0 - blk["model"]["crps"] / blk[base]["crps"]
            blk["model"][f"brier_skill_vs_{base}"] = (
                1.0 - blk["model"]["brier"] / blk[base]["brier"] if blk[base]["brier"] > 0 else None
            )
        overall[split.name] = blk

    test_leads = [r for r in by_lead if r["split"] == TEST.name]
    widening_by = {
        key: _non_decreasing([r["model"][key] for r in test_leads])
        for key in ("width_80_m3s", "width_80_rel_median", "width_80_rel")
    }
    # The check uses the mean width in m3/s and the median relative width. The mean relative width
    # is reported too, but low-flow rows (Kotri in the dry season) make the mean of a ratio
    # unstable, so it is not part of the check (docs/decisions.md).
    widening = widening_by["width_80_m3s"] and widening_by["width_80_rel_median"]
    p7 = {
        f"coverage_{round(c * 100)}": overall[TEST.name]["model"][f"coverage_{round(c * 100)}"]
        >= c - P7_TOL
        for c in COVERAGES
    }
    return {
        "organ": "oracle",
        "target_kind": TARGET_KIND,
        "target_label": TARGET_LABEL,
        "observed_validation": "not performed",
        "observed_validation_note": (
            "No public, redistributable gauge readings for Guddu, Sukkur or Kotri were found at "
            "low cost, so the modeled series is not compared with any gauge record (ORA-R9.2)."
        ),
        "seed": seed,
        "fast": fast,
        "stations": list(stations),
        "splits": {s.name: [s.start.isoformat(), s.end.isoformat()] for s in (REFIT, TEST, STRESS)},
        "model": {"name": bundle.name, "version": bundle.version, "sha256": bundle.sha256},
        "crps_note": CRPS_NOTE,
        "threshold_note": (
            "danger threshold = modeled 5-year return level of the GloFAS series (1997-2016), "
            "an assumption, not an official warning level"
        ),
        "mondrian_note": (
            "Mondrian (monsoon/non-monsoon) CQR is reported for comparison and not adopted: no "
            "untouched selection period exists, so choosing it would tune on the test years."
        ),
        "overall": overall,
        "mlp_comparison": _mlp_results(),
        "checks": {
            "ora_p7_test": p7,
            "lead_widening": widening,
            "lead_widening_by_measure": widening_by,
            "tolerance": P7_TOL,
        },
        "by_lead": test_leads + [r for r in by_lead if r["split"] == STRESS.name],
        "by_station_lead": by_station,
    }


def _metric(
    id_: str,
    label: str,
    value: float,
    *,
    unit: str = "",
    direction: Literal["higher", "lower"] = "higher",
    target: float | None = None,
    dataset: str,
    stamp: datetime,
    sha: str,
    seed: int,
    notes: str = "",
) -> MetricResult:
    return MetricResult(
        id=id_,
        label=label,
        value=round(float(value), 6),
        target=target,
        unit=unit,
        direction=direction,
        dataset=dataset,
        mode="demo",
        timestamp=stamp,
        git_sha=sha,
        seed=seed,
        notes=NOTE + notes,
    )


def to_metrics(report: dict[str, Any], seed: int) -> list[MetricResult]:
    stamp = datetime.now(UTC)
    sha = _git_sha()
    sub = " (fast subset)" if report["fast"] else ""
    ds_test = f"oracle demo test 2017-2023, modeled GloFAS{sub}"
    ds_stress = f"oracle demo 2022 flood season stress, modeled GloFAS{sub}"
    out: list[MetricResult] = []
    kw: dict[str, Any] = {"stamp": stamp, "sha": sha, "seed": seed}
    for split, ds in (("test", ds_test), ("stress_2022", ds_stress)):
        blk = report["overall"].get(split)
        if not blk:
            continue
        mdl = blk["model"]
        sfx = "test" if split == "test" else "stress2022"
        out.append(
            _metric(
                f"oracle.crps.{sfx}",
                f"CRPS (quantile approx.), {split}",
                mdl["crps"],
                unit="m3/s",
                direction="lower",
                dataset=ds,
                notes=CRPS_NOTE,
                **kw,
            )
        )
        for base in ("persistence", "persistence_prob", "climatology"):
            out.append(
                _metric(
                    f"oracle.crps_skill.{base}.{sfx}",
                    f"CRPS skill vs {base.replace('_', ' ')}, {split}",
                    mdl[f"crps_skill_vs_{base}"],
                    dataset=ds,
                    notes=f"1 - CRPS_model / CRPS_{base}; "
                    f"baseline CRPS {blk[base]['crps']:.1f} m3/s.",
                    **kw,
                )
            )
        for tau in ("q10", "q50", "q90"):
            out.append(
                _metric(
                    f"oracle.pinball.{tau}.{sfx}",
                    f"Pinball loss {tau}, {split}",
                    mdl[f"pinball_{tau}"],
                    unit="m3/s",
                    direction="lower",
                    dataset=ds,
                    **kw,
                )
            )
        for c in COVERAGES:
            key = f"coverage_{round(c * 100)}"
            lo, hi = mdl[f"{key}_ci90"]
            out.append(
                _metric(
                    f"oracle.coverage.c{round(c * 100)}.{sfx}",
                    f"Empirical coverage of the {c:g} interval, {split}",
                    mdl[key],
                    target=(c - P7_TOL) if split == "test" else None,
                    dataset=ds,
                    notes=f"nominal {c:g}; month-block bootstrap 90% interval [{lo:.3f}, {hi:.3f}]"
                    + ("" if split == "test" else "; stress season reported, not a target"),
                    **kw,
                )
            )
        out.append(
            _metric(
                f"oracle.width_rel.c80.{sfx}",
                f"Mean 0.8 interval width relative to the median, {split}",
                mdl["width_80_rel"],
                direction="lower",
                dataset=ds,
                notes=f"mean width {mdl['width_80_m3s']:.0f} m3/s",
                **kw,
            )
        )
        out.append(
            _metric(
                f"oracle.brier.{sfx}",
                f"Brier score of danger-threshold exceedance, {split}",
                mdl["brier"],
                direction="lower",
                dataset=ds,
                notes=f"event rate {mdl['event_rate']:.3f}; climatology Brier "
                f"{blk['climatology']['brier']:.4f}; " + report["threshold_note"],
                **kw,
            )
        )
        out.append(
            _metric(
                f"oracle.mondrian.coverage.c80.{sfx}",
                f"Coverage of the 0.8 interval, Mondrian variant (not shipped), {split}",
                mdl["coverage_80_mondrian"],
                dataset=ds,
                notes=report["mondrian_note"],
                **kw,
            )
        )
    for rec in report["by_lead"]:
        if rec["split"] != "test" or rec["lead"] not in KEY_LEADS:
            continue
        h = rec["lead"]
        mdl = rec["model"]
        out.append(
            _metric(
                f"oracle.coverage.c80.test.lead{h:02d}",
                f"Coverage of the 0.8 interval at lead {h} d, test",
                mdl["coverage_80"],
                dataset=ds_test,
                notes="nominal 0.8",
                **kw,
            )
        )
        out.append(
            _metric(
                f"oracle.crps_skill.persistence_prob.test.lead{h:02d}",
                f"CRPS skill vs probabilistic persistence at lead {h} d, test",
                1.0 - mdl["crps"] / rec["persistence_prob"]["crps"],
                dataset=ds_test,
                **kw,
            )
        )
    checks = report["checks"]
    out.append(
        _metric(
            "oracle.check.ora_p7",
            "ORA-P7: test coverage >= nominal - 0.05 at 0.5, 0.8 and 0.9",
            1.0 if all(checks["ora_p7_test"].values()) else 0.0,
            target=1.0,
            dataset=ds_test,
            notes=json.dumps(checks["ora_p7_test"]),
            **kw,
        )
    )
    out.append(
        _metric(
            "oracle.check.lead_widening",
            "ORA-R5.1: 0.8 interval width non-decreasing in lead (5% tolerance)",
            1.0 if checks["lead_widening"] else 0.0,
            target=1.0,
            dataset=ds_test,
            notes="checked on mean width (m3/s) and median relative width; by measure: "
            + json.dumps(checks["lead_widening_by_measure"]),
            **kw,
        )
    )
    mlp = report.get("mlp_comparison")
    if mlp:
        for split, sfx in (("test", "test"), ("stress_2022", "stress2022")):
            r = mlp["results"].get(split)
            if r is None:
                continue
            out.append(
                _metric(
                    f"oracle.mlp.crps_skill_vs_gbm.{sfx}",
                    f"Quantile MLP (not shipped) CRPS skill vs the shipped GBM, {split}",
                    r["crps_skill_mlp_vs_gbm"],
                    dataset=f"oracle demo {split}, modeled GloFAS (all rows, mlp_results.json)",
                    notes=f"MLP coverage_80 {r['mlp']['coverage_80']:.3f} vs GBM "
                    f"{r['gbm']['coverage_80']:.3f}; {mlp['protocol_note']}",
                    **kw,
                )
            )
    out.append(
        _metric(
            "oracle.observed_validation.performed",
            "Observed gauge validation (small n) performed",
            0.0,
            dataset="none",
            notes=report["observed_validation_note"],
            **kw,
        )
    )
    return out


def _clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 6)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def run(fast: bool = False, seed: int = 0) -> list[MetricResult]:
    report = evaluate(fast=fast, seed=seed)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = "oracle_report_fast.json" if fast else "oracle_report.json"
    tmp = RESULTS_DIR / f"{name}.tmp"
    tmp.write_text(json.dumps(_clean(report), indent=1) + "\n", encoding="utf-8")
    tmp.replace(RESULTS_DIR / name)
    pd.DataFrame(report["by_station_lead"]).to_parquet(
        RESULTS_DIR / ("oracle_by_station_fast.parquet" if fast else "oracle_by_station.parquet"),
        index=False,
    )
    return to_metrics(report, seed)
