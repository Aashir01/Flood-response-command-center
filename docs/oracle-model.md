# Oracle model: modeled river discharge forecasts with conformal intervals

The Oracle (`organs/oracle`, MCP server `oracle-mcp`) forecasts **modeled river discharge (GloFAS via Open-Meteo)** at five places on the Indus system, 1 to 14 days ahead, with a median, a split-conformal interval, the probability of exceeding a danger threshold, and an explanation of the drivers. This page is the reference for the method, the evaluation and the limits. Spec: `.kiro/specs/oracle-mcp/`. Model card: `organs/oracle/models/model_card.md`.

## Wording rules (ORA-R8)

- The target is GloFAS v4 model output served by the Open-Meteo Flood API. Every tool result and eval record carries `target_kind = "modeled_glofas"` and the label "Modeled river discharge (GloFAS via Open-Meteo)". The UI shows "Modeled (GloFAS)".
- It is never called gauge data, an observation or a measurement. A lint test (`organs/oracle/tests/unit/test_wording.py`) scans the Oracle sources, tool descriptions, feature labels, training files, eval code, the demo manifest and this page.
- A station is "GloFAS grid cell nearest to <name>". It is not a physical gauge. The cell coordinates the API returned are in `data/demo/oracle/stations.json`, the `oracle://stations` resource and each `forecast_river` result (`station.cell_lat/cell_lon`).
- No observed (gauge) validation was performed. The eval says `observed_validation: "not performed"` (ORA-R9.2): no public, redistributable gauge readings for Guddu, Sukkur or Kotri were found at low cost.

## Data

`data/demo/oracle/`, built once by `scripts/build_oracle_demo.py` (dev time, network, fewer than 30 requests; details and hashes in `data/demo/oracle/MANIFEST.md`).

| File | Content |
|---|---|
| `discharge_daily.parquet` | modeled GloFAS v4 discharge (m³/s), 7 grid cells, daily 1997-01-01 to 2023-12-31 |
| `rain_daily.parquet` | ERA5 daily precipitation (4 upper-basin points) and mean temperature (1 point, Gilgit), same period |
| `stations.json` | requested and returned cell coordinates, role, upstream links, danger threshold and its method |

The Flood API returns null before 1997-01-01 at these cells although its docs say 1984, so the dataset starts in 1997 (`docs/decisions.md`). The series has no gaps and no negative values (loader tests). The continuity check across the July 2022 reanalysis/forecast join passed, so the 2022 stress window is the full season.

Stations: forecast at Chenab near Trimmu, Indus near Taunsa, Guddu, Sukkur and Kotri; Indus near Kalabagh and Kabul near Nowshera are feature-only upstream inputs. Kotri's real flow is regulated by barrages that GloFAS does not model; the station note says so in every Kotri result.

Licences: Open-Meteo data CC BY 4.0 ("Weather data by Open-Meteo.com"), GloFAS (Copernicus Emergency Management Service / ECMWF), ERA5 (Copernicus C3S). The free non-commercial tier was accepted by the owner for this demo.

## Target and features

Forecast origin `as_of = t`. For lead `h` in 1..14 the target is the log ratio `y_h = ln(Q[t+h] + 1) − ln(Q[t] + 1)`. It is scale-free (one model pools stations of very different size), it makes persistence the zero forecast, and the back-transform `Q = (Q[t] + 1)·exp(y) − 1`, clipped at 0, is non-negative by construction (ORA-P2).

28 features, all computed from rows dated on or before `as_of` (`core/features.py`, which slices every frame to `<= as_of` before computing):

| Family | Features |
|---|---|
| level and trend | `ln(Q_t + 1)`; changes over 1, 3, 7, 14, 30 days; 7-day max and min relative to today |
| upstream (2 slots) | upstream level relative to the station; its 1-, 3-, 7-day changes |
| basin rainfall (ERA5) | basin-mean sums over 1, 3, 7, 14, 30 days; the wettest point's 7-day sum |
| temperature (ERA5) | 7-day mean, 14-day change (snowmelt proxy) |
| season | day-of-year sine and cosine, monsoon flag (June to September) |
| identity | station code (categorical) |

Rainfall **forecasts** are not used. The archive of forecast rainfall starts in 2021, so training on realised future rain would be leakage and train/serve skew. This is the main limit on skill for rain-driven rises (see the stress results). `forecast[].rainfall_mm` is therefore absent, which the contract allows.

## Splits

| Split | `as_of` | Use |
|---|---|---|
| train_fit | 1997-2008 | fit with early stopping |
| train_val | 2009-2011 | number of trees per booster |
| refit | 1997-2011 | final boosters |
| calibration | 2012-2016 | conformity scores |
| test | 2017-2023 | every reported metric |
| stress | 2022-06-01 to 2022-10-31 | 2022 flood season, inside test |

Purge: a row `(t, h)` belongs to a split only if `t + h` is in the same split. `splits.assert_disjoint()` runs in training and tests. The valid `as_of` window starts on 2017-01-01, so nothing the model or its calibration used postdates any allowed origin (ORA-R2.4). ORA-P5 is tested by perturbing and deleting rows after `as_of`.

## Model

42 LightGBM boosters, one per (quantile 0.1/0.5/0.9, lead 1..14), `objective = quantile`, pooled over the five stations. `organs/oracle/training/config.yaml`: 15 leaves, learning rate 0.05, at most 400 trees with 30-round early stopping, min 50 samples per leaf, feature and bagging fraction 0.8, L2 1, seed 0, deterministic, one thread. Rows need a full 30-day history.

Reproduce: `uv run python organs/oracle/training/train_gbm.py` (about 4 minutes on an i5 laptop CPU; reruns are byte-identical). Artifacts are LightGBM text files (gzip, mtime 0), `conformity.parquet` and `manifest.json` with SHA-256 per file and a root hash, which is the `model.sha256` in provenance. The loader refuses any hash mismatch (ORA-X3). No pickle.

## Calibration (CQR) and the `coverage` input

Per lead, the three raw quantiles are sorted (minimal repair; `quantile_correction_applied` and a warning report it). Conformity scores on the calibration split, per (station, lead), in log-ratio space: `E = max(q10 − y, y − q90)`. For coverage `c` (0.5 to 0.99, default 0.8): `k = ceil((n + 1)·c)`, `Q̂ = E_sorted[min(k, n) − 1]` (a warning when `k > n`), interval `[q10 − Q̂, q90 + Q̂]` with the median kept inside, then back-transformed. `Q̂` indexes a sorted array at a rank that grows with `c`, so higher coverage never gives a narrower interval (ORA-P3, exact). Below 500 calibration points a station uses the pooled scores, widened by `|Q̂|/√n` (ORA-X8). The interval bounds are returned in the historical fields `p10` and `p90`; `calibration.interval_lower_q/upper_q` give their quantile levels (0.05 and 0.95 at coverage 0.9).

## Exceedance probability

From the 0.8-calibrated knots (lower bound at F = 0.1, median at 0.5, upper bound at 0.9) in `ln(Q + 1)` space, piecewise linear, with tails extended by the adjacent slope to F = 0.01 and 0.99. `p_exceed(T) = 1 − F(ln(T + 1))`. It is in [0, 1] and non-increasing in `T` (ORA-P6). When the threshold lies outside the 0.8 band the result says the tail is extrapolated.

**Danger threshold (assumption):** the modeled 5-year return level, the 0.8 Weibull quantile of annual maxima of the modeled series over 1997-2016. It is not an official warning level, and every result says so in a warning.

## Explanations

`explain_forecast(run_id)` runs exact TreeSHAP (`pred_contrib`) on the median booster of the peak lead. Contributions are additive in log-ratio space; they are mapped to m³/s by log share so they sum to the median minus the baseline (ORA-X4). The narrative is a template, not LLM text.

## Evaluation

`uv run python -m evals.run --organ oracle --seed 0` (about 35 s; `--fast`: every 7th day, two stations, about 10 s). The report goes to `evals/results/oracle.json` (dashboard metrics) and `oracle_report.json` (full tables, git-ignored). All numbers are in m³/s of modeled discharge, on the test split (2017-2023, 5 stations, 178,395 station-lead rows) and the 2022 stress season (10,185 rows).

CRPS here is the quantile approximation `2·Σ w·pinball` over τ = 0.1/0.5/0.9 with weights 0.3/0.4/0.3. It is a coarse surrogate, comparable only between forecasts scored the same way.

| Forecast | CRPS test | CRPS stress 2022 | 0.8 coverage test | 0.8 coverage stress |
|---|---|---|---|---|
| LightGBM + CQR (shipped) | 220 | 793 | 0.790 | 0.706 |
| persistence (point) | 594 | 1497 | n/a | n/a |
| persistence, empirical log-ratio quantiles | 420 | 1105 | 0.807 | 0.597 |
| day-of-year climatology | 488 | 1103 | 0.947 | 0.868 |

CRPS skill of the shipped model on test: 0.48 vs probabilistic persistence, 0.55 vs climatology, 0.63 vs point persistence. On the stress season: 0.28, 0.28 and 0.47.

Coverage on test vs nominal (90% month-block bootstrap interval): 0.5 → 0.538 [0.504, 0.565]; 0.8 → 0.790 [0.772, 0.807]; 0.9 → 0.897 [0.881, 0.912]. ORA-P7 (coverage ≥ nominal − 0.05) holds. On the 2022 stress season coverage falls short: 0.8 → 0.706 [0.640, 0.765]; 0.9 → 0.797 [0.725, 0.868]. Nothing was tuned on it.

By lead (test): CRPS 22 / 78 / 223 / 380 at leads 1 / 3 / 7 / 14 vs 81 / 219 / 415 / 696 for probabilistic persistence and about 488 for climatology. 0.8 coverage stays between 0.78 and 0.80 at every lead. The mean 0.8 width grows from 75 to 1,547 m³/s. In the stress season the model beats climatology up to lead 10 but not at lead 14 (CRPS 1,359 vs 1,130), and 0.8 coverage drops to 0.64 at lead 14.

Lead widening (ORA-R5.1) is checked on the mean width in m³/s and on the median width relative to the median; both are non-decreasing within 5%. The mean of the relative width is reported as well and is not monotone, because dry-season rows at Kotri, with medians near 0 m³/s, dominate a mean of ratios.

Exceedance: the modeled 5-year level is rarely crossed in the test years (event rate 0.02% of rows, 0.4% in the stress season). The model's Brier score (0.00042 test, 0.0059 stress) beats persistence but is worse than climatology, which almost never exceeds and so scores the event rate. Exceedance probabilities should be read as indicative, not as calibrated warning probabilities.

Stretch comparisons (not shipped):
- Mondrian CQR with separate scores for monsoon and non-monsoon origins: 0.8 coverage 0.794 on test and 0.741 on the stress season (vs 0.790 and 0.706). It is not adopted, because no untouched period is left to select it on; choosing it now would tune on the test years.
- A PyTorch quantile MLP on the same features and splits (`training/train_mlp.py`, `training/mlp_results.json`): CRPS 234 vs 220 on test (6% worse) and 760 vs 793 on the stress season (4% better), with lower coverage (0.753 and 0.666).

## Limitations

- The forecast is a statistical post-model of the GloFAS series. It does not re-run or replace GloFAS, and its skill is measured against GloFAS itself, not against any river reading.
- Daily errors are autocorrelated, so the exchangeability behind the conformal guarantee does not strictly hold. Coverage is marginal over seasons and not conditional on flood conditions; the 2022 shortfall shows the consequence.
- Features are reanalysis-only; no rainfall forecast enters the model.
- Kotri is regulated by barrages that GloFAS does not model.
- Live mode (optional) uses the Forecast API's recent analysis for rain instead of ERA5, so live inputs can differ from the training distribution; the result says so.
- The danger threshold is an assumption (modeled 5-year return level).
