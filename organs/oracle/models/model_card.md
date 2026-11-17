# Model card: `lightgbm-cqr` 0.1.0 (oracle-mcp)

## What it predicts
Quantiles (0.1, 0.5, 0.9) of **modeled** river discharge, GloFAS v4 via the Open-Meteo Flood API,
1 to 14 days after a forecast origin `as_of`, at the GloFAS grid cell nearest to five named
places on the Indus system (Chenab near Trimmu, Indus near Taunsa, Guddu, Sukkur, Kotri). The
target is a model output (a hydrological reanalysis and its forecast continuation). It is not a
gauge record, and this model is a statistical post-model of that series. It does not re-run or
replace GloFAS.

Target per lead `h`: `y_h = ln(Q[t+h] + 1) - ln(Q[t] + 1)`. Back-transform
`Q = (Q[t] + 1) exp(y) - 1`, clipped at 0.

## Model
- 42 LightGBM boosters (3 quantiles x 14 leads), `objective = quantile`, pooled over the five
  stations with `station` as a categorical feature. Hyperparameters in
  `training/config.yaml` (design section 4.2): 15 leaves, learning rate 0.05, at most 400
  trees with early stopping (30 rounds) on train_val, min 50 samples per leaf, feature and
  bagging fraction 0.8, L2 1, seed 0, deterministic, single thread.
- 28 features, all computed from data dated on or before `as_of` (`core/features.py`): level
  and 1/3/7/14/30-day changes of modeled discharge, 7-day max and min, up to two upstream
  modeled stations (relative level and 1/3/7-day changes), ERA5 basin rainfall sums over 4
  points (1/3/7/14/30 days, plus the wettest point's 7-day sum), ERA5 upper-basin temperature
  (7-day mean, 14-day change), season (day-of-year sine and cosine, monsoon flag), station id.
- No rainfall forecasts are used: the archive of forecast rainfall starts in 2021, so using
  realised future rain in training would be leakage and train/serve skew. This limits skill
  for events driven by rain that has not yet fallen (see the 2022 stress result).
- Artifacts: LightGBM text model files, gzip with mtime 0 (`lgbm/q<qq>_l<hh>.txt.gz`), sorted
  conformity scores (`conformity.parquet`) and `manifest.json` with the SHA-256 of every file
  and a root hash (the provenance `model.sha256`). No pickle. The loader refuses to load on any
  hash mismatch.

## Data and splits
Committed demo data `data/demo/oracle/` (1997-01-01 to 2023-12-31; the Flood API returns no
values before 1997 at these cells). Rows need a 30-day history.

| Split | as_of | Use |
|---|---|---|
| train_fit | 1997-2008 | fit with early stopping |
| train_val | 2009-2011 | tree count per booster |
| refit | 1997-2011 | final boosters |
| calibration | 2012-2016 | CQR conformity scores (about 1,800 per station and lead) |
| test | 2017-2023 | every reported metric |
| stress | 2022-06-01 to 2022-10-31 | 2022 flood season, inside test |

Purge: a row belongs to a split only if `as_of + h` is in the same split. Valid forecast origins
start on 2017-01-01, so no data used by the model or its calibration postdates `as_of`.

## Calibration
Split conformal (CQR) per (station, lead), scores in log-ratio space, interval adjusted to the
requested coverage (0.5 to 0.99, default 0.8). Higher coverage never gives a narrower interval
(exact nesting, ORA-P3). Below 500 calibration points the pooled scores are used and widened.

Caveats: daily series are autocorrelated, so the exchangeability behind the conformal guarantee
does not strictly hold, and coverage is marginal over seasons, not conditional on flood
conditions.

## Evaluation
`uv run python -m evals.run --organ oracle --seed 0` (details and by-lead tables in
`docs/oracle-model.md`). Test split 2017-2023, five stations, m3/s of modeled discharge;
CRPS is the quantile approximation over tau 0.1/0.5/0.9.

| | Test 2017-2023 | 2022 flood season (stress) |
|---|---|---|
| CRPS, this model | 220 | 793 |
| CRPS, probabilistic persistence | 420 | 1105 |
| CRPS, day-of-year climatology | 488 | 1103 |
| Coverage of the 0.5 / 0.8 / 0.9 interval | 0.538 / 0.790 / 0.897 | 0.528 / 0.706 / 0.797 |

Test coverage meets nominal within 0.05 (ORA-P7). The 2022 season is under-covered (0.706 for a
nominal 0.8); nothing was tuned on it. At lead 14 in the stress season the model is worse than
climatology (CRPS 1359 vs 1130). The danger threshold is rarely crossed in the test years, and
the exceedance Brier score is worse than climatology's, so exceedance probabilities are indicative
only. No observed (gauge) validation was performed.

Not shipped, compared in the eval: a Mondrian (monsoon/non-monsoon) CQR variant (0.8 coverage
0.794 test, 0.741 stress) and a PyTorch quantile MLP (`training/train_mlp.py`; CRPS 234 test,
760 stress).

## Reproducibility
`uv run python organs/oracle/training/train_gbm.py` (about 4 minutes on an i5 laptop CPU, no GPU).
Model files are byte-identical across reruns on the same data.

## Danger threshold (assumption)
Modeled 5-year return level (Weibull plotting position over the 1997-2016 annual maxima of the
modeled series). Not an official warning level.
