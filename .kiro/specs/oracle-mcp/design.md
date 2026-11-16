# oracle-mcp: Design

Implements `requirements.md` (ORA-R1..R11, ORA-P1..P8). Contract: `mcp-contracts.md` §4 (v0.3).

## 1. Overview

The Oracle forecasts **modeled** river discharge (GloFAS via Open-Meteo, never "gauge" or "observed") at named river points for 1 to 14 days ahead. It returns p10/p50/p90 quantiles, conformally calibrated intervals for a requested coverage, exceedance probabilities against a danger threshold, and an explanation of the main drivers.

Model: LightGBM quantile regression, one model per (quantile, lead day), pooled across stations on a scale-free target, followed by split conformal calibration (CQR) per station and lead. The model is a statistical post-model of the GloFAS reanalysis series. It does not re-run or replace the GloFAS forecast, and the docs say so.

All logic lives in `core/` as pure functions on arrays and small dataclasses. The MCP layer validates, calls core, and wraps results in the `ToolResult` envelope.

```
organs/oracle/
  src/stitch_oracle/
    core/
      stations.py     Station catalog models (id, name, cell coords, upstream links, threshold)
      features.py     build_features(frames, station, as_of): the ONLY place that reads history; slices <= as_of first
      splits.py       chronological split definitions + purge guard
      bundle.py       ModelBundle: load LightGBM text models, verify SHA-256 manifest, predict raw quantiles
      quantiles.py    sort-based monotone repair, returns correction flags
      conformal.py    CQR scores, quantile-of-scores lookup, nested interval adjustment
      exceedance.py   piecewise CDF from quantile knots, p_exceed(threshold)
      ood.py          out-of-range feature check
      explain.py      pred_contrib -> drivers (m3/s), feature-label dictionary, narrative templates
      baselines.py    persistence, climatology (evals)
      metrics.py      pinball, quantile-approximated CRPS, coverage, width
    data/loader.py    committed Parquet (discharge, rain) + stations.json, schema validation
    live.py           Open-Meteo client + DuckDB cache (optional, mode=live)
    store.py          RunStore (DuckDB): run_id -> station, as_of, features, output
    server.py         MCP tools, envelope, error mapping
    http.py           /healthz
    settings.py       env config
  models/             lgbm/<q>_<lead>.txt, manifest.json (sha256 per file + root hash), conformity.parquet, model_card.md
  training/           train_gbm.py, config.yaml, oracle_train.ipynb, train_mlp.py (stretch), README.md
  tests/{unit,property,contract}/   strategies.py holds shared Hypothesis strategies
data/demo/oracle/     stations.json, discharge_daily.parquet, rain_daily.parquet, MANIFEST.md
scripts/build_oracle_demo.py     (network, dev-time only)
evals/oracle/                    eval harness
```

## 2. Verified external facts (Open-Meteo)

Read on the day of writing from [Flood API docs](https://open-meteo.com/en/docs/flood-api), [features page](https://open-meteo.com/en/features), and [terms](https://open-meteo.com/en/terms) (via search snippet).

| Topic | Finding | Consequence |
|---|---|---|
| Endpoint, variables | `/v1/flood`, daily `river_discharge` (m³/s); ensemble stats (`mean/median/max/min/p25/p75`) exist for forecasts only | We use `river_discharge` only. |
| Source and resolution | GloFAS v4, 0.05° (~5 km) grid, daily. v3 at 0.1° exists | Station = nearest-cell lookup. The API returns the grid-cell centre `latitude/longitude`; this goes in provenance (ORA-R8.3). |
| Cell selection | The API picks the largest river within ~5 km. Docs advise varying coordinates by 0.1° to find the right river. `cell_selection` = `land` (default) / `sea` / `nearest` | The build script probes a 5×5 offset grid per station (step 0.05°) with `cell_selection=nearest`, keeps the cell with the highest mean discharge, and records requested vs returned coordinates. The owner confirms the picks (§12). |
| History | "Seamless" series from 1984-01-01 to 7 months ahead. The comparison table lists the v4 reanalysis as 1984 to July 2022 and forecasts at 30 days | **Risk**: continuity and quality of the series after July 2022 (the 2022 flood season). The build script asserts no gaps in 2022-06-01..2023-12-31 and logs how the series changes at the join (§13, R1). |
| Parameters | `start_date`, `end_date` (1984-01-01 onward), `past_days`, `forecast_days` (0..210), multiple comma-separated coordinates per call, `timezone=GMT` preserves model dates | One batched request per station group; always `timezone=GMT`. |
| Terms | Free for **non-commercial** use, no API key. Fair use: under 10,000 calls/day, 5,000/hour, 600/minute. Data licensed CC BY 4.0, attribution required. Commercial use needs an API key | A hackathon demo qualifies as non-commercial. The owner confirms (§12). The build uses fewer than 30 calls. `THIRD_PARTY.md` and the UI footer carry "Weather data by Open-Meteo.com (CC BY 4.0), GloFAS (Copernicus/ECMWF)". |
| ERA5 rainfall | Historical Weather API (`archive-api.open-meteo.com/v1/archive`), ERA5 since 1940, 9 to 25 km, daily `precipitation_sum`, `temperature_2m_mean` | Rain features for 1984+ come from this API. The archive lags real time by a few days (from memory of the docs; the build script does not depend on it). |
| Historical Forecast API | Archived forecast model output from 2021 only | Too short to train on forecast rainfall. See §3.2. |

## 3. Data

### 3.1 Stations

A **station** is a named point snapped to a GloFAS grid cell. Labelled everywhere as "GloFAS grid cell nearest to <name>". Not a physical gauge.

| station_id | Name (nearest to) | Approx. requested lat, lon | Role |
|---|---|---|---|
| `indus-guddu` | Indus near Guddu | 28.42, 68.74 | forecast |
| `indus-sukkur` | Indus near Sukkur | 27.69, 68.85 | forecast |
| `indus-kotri` | Indus near Kotri | 25.37, 68.31 | forecast |
| `indus-taunsa` | Indus near Taunsa | 30.51, 70.85 | forecast and upstream feature |
| `chenab-trimmu` | Chenab near Trimmu | 31.15, 72.15 | forecast (tributary) and upstream feature |
| `indus-kalabagh` | Indus near Kalabagh | 32.96, 71.55 | feature only |
| `kabul-nowshera` | Kabul near Nowshera | 34.00, 71.98 | feature only |

Coordinates are approximate starting points. The final cell coordinates come from the API response and are written to `stations.json`. `upstream` lists up to two feature stations per station (chain Kalabagh, Taunsa, Guddu, Sukkur, Kotri; Chenab joins above Guddu). Kotri discharge is affected by barrage regulation that GloFAS does not model; the station note says so.

`stations.json` fields: `station_id, name, river, requested_lat, requested_lon, cell_lat, cell_lon, role, upstream[], danger_threshold_m3s, threshold_method, published_warning_cusecs (null), note`.

### 3.2 Features and the no-leakage rule

Forecast origin is `as_of = t`. Daily value of day `t` is treated as available at `t`. Everything the model sees is computed from rows dated `<= t`.

Target, per lead `h` in 1..14: `y_h = ln(Q_{t+h} + 1) − ln(Q_t + 1)` (log-ratio to the current value, ε = 1 m³/s). Reasons: it is scale-free, so stations with very different flows can share one model; it makes persistence the zero forecast; back-transform `Q = (Q_t + 1)·exp(y) − 1`, clipped at 0, gives non-negative discharge by construction (ORA-P2); and trees do not have to extrapolate absolute levels.

Feature schema (fixed order; NaN where not applicable; LightGBM handles NaN natively). About 40 features:

| Group | Features |
|---|---|
| Level and trend | `lnQ_t`; `lnQ_t − lnQ_{t−k}` for k = 1, 3, 7, 14, 30; 7-day max and min of lnQ minus `lnQ_t` |
| Upstream (up to 2 slots) | `lnQ_u,t − lnQ_s,t`, `Δ1`, `Δ3`, `Δ7` of upstream station u (travel time of days makes this the strongest signal at leads 1 to 7) |
| Basin rainfall (4 ERA5 points over the upper basin) | 1-, 3-, 7-, 14-, 30-day sums of the basin mean, plus the max point 7-day sum |
| Temperature (snowmelt proxy, 1 upper-basin point) | 7-day mean, 14-day change |
| Season | `sin`, `cos` of day of year; `monsoon` flag (Jun to Sep) |
| Identity | `station` as a categorical |

**Forecast-rainfall features are not in the core model.** ERA5 gives rainfall back to 1940, but the archive of rainfall *forecasts* starts in 2021. Training on realised future rain and serving forecast rain would be train/serve skew and, in the backtest, leakage. So the core model uses only information at or before `as_of`; the `rainfall_mm` interval in the contract is omitted (optional field). A stretch task fits a rainfall-forecast variant on 2021+ data and reports it separately. This differs from the literal wording of ORA-R1.1 (§12, issue 1).

Implementation of the rule: `features.build_features(frames, station, as_of)` first slices every frame to `date <= as_of`, then computes. There is no other history read path. ORA-P5 tests this by perturbing future rows.

### 3.3 Splits (chronological, with purge)

| Split | `as_of` range | Use |
|---|---|---|
| train-fit | 1985-01-01 to 2007-12-31 | fit with early stopping |
| train-val | 2008-01-01 to 2011-12-31 | pick `n_trees`, hyperparameters (pinball) |
| refit | 1985-01-01 to 2011-12-31 | final models, `n_trees` from train-val |
| calibration | 2012-01-01 to 2016-12-31 | conformity scores |
| test | 2017-01-01 to 2023-12-31 | all reported metrics |
| stress | 2022-06-01 to 2022-10-31 (inside test) | 2022 flood season |

Purge: a row belongs to a split only if `t + h` also falls inside it. `splits.assert_disjoint()` runs in training and in tests. No 2022 row enters training or calibration, which is what allows a clean 2022 stress test and a demo `as_of` in August 2022.

**Valid `as_of` window**: `2017-01-01` to the last date in the data. An earlier `as_of` returns `INVALID_INPUT` ("before the model's calibration cutoff; a forecast would use calibration data dated after as_of"). This is how ORA-R2.4 holds for calibration too.

### 3.4 Committed demo dataset (`data/demo/oracle/`)

| File | Content | Size |
|---|---|---|
| `discharge_daily.parquet` | `date, station_id, discharge_m3s` (float32), 7 stations, 1984-01-01 to 2023-12-31, about 102k rows | about 0.6 MB |
| `rain_daily.parquet` | `date, point_id, precip_mm, temp_c` for 4 rain points and 1 temperature point | about 0.4 MB |
| `stations.json` | §3.1 | few KB |
| `MANIFEST.md` | source, license, build date, API URLs, returned cell coordinates, content SHA-256 | few KB |

Budget: under 2 MB total. It includes the whole 2022 season. Training reads the same committed Parquet, so the model is reproducible offline.

`scripts/build_oracle_demo.py` (needs network, dev-time only): probe cells (§2), fetch discharge in one call per station (past decades in a single `start_date`/`end_date` request), fetch ERA5 daily rain and temperature, validate (no gaps, no negatives, 2022 join check), compute danger thresholds from 1985 to 2016 only, write Parquet and manifest. Fewer than 30 requests; sleeps between calls.

### 3.5 Danger thresholds (assumption, flagged)

`danger_threshold_m3s` = empirical 5-year return level of the modeled series: the 0.8 quantile (Weibull plotting position) of annual maxima for 1985 to 2016. It is not an official warning level. `threshold_method = "modeled_5yr_return_level"`. If the owner supplies official Federal Flood Commission levels (cusecs; 1 cusec = 0.0283168 m³/s), `published_warning_cusecs` is filled and takes precedence, with `threshold_method = "published"`. The tool reports the method in a warning whenever the modeled level is used.

## 4. Model

### 4.1 Choice: LightGBM

| Option | Quantile loss | Artifact format | Exact TreeSHAP | CPU size | Verdict |
|---|---|---|---|---|---|
| LightGBM (MIT) | yes (`objective="quantile"`) | native text model file, no pickle | yes (`predict(pred_contrib=True)`) | wheel about 4 MB | **chosen** |
| sklearn `HistGradientBoostingRegressor(loss="quantile")` | yes | pickle, or ONNX through a converter | no built-in | already a dependency | rejected: pickle is unsafe to load, no built-in contributions |
| XGBoost | yes | JSON | yes | larger wheel | no gain over LightGBM |
| PyTorch quantile MLP | yes | ONNX | no | torch not in the container | stretch comparison only |

Artifact safety: models are LightGBM **text** files, parsed by `Booster(model_file=...)`. No pickle anywhere. `models/manifest.json` lists the SHA-256 of every model file and of `conformity.parquet`, plus a root hash (SHA-256 of the sorted `name:hash` lines). `ModelBundle.load()` recomputes and refuses to load on mismatch (`INTERNAL`, logged). The root hash is the `model.sha256` in provenance (ORA-R6.2).

### 4.2 Strategy and hyperparameters

Direct multi-horizon: 3 quantiles (0.1, 0.5, 0.9) × 14 leads = 42 boosters, each fit on pooled station rows (about 5 stations × 8,400 days ≈ 42k rows). Lead-as-feature is rejected: it weakens per-lead calibration and makes explanations mix leads.

Starting config (`training/config.yaml`): `num_leaves=15, learning_rate=0.05, n_estimators≤400 with early stopping 30, min_child_samples=50, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1, seed=0, deterministic=True, force_row_wise=True, num_threads=1`. A small random search (20 configs, selection by mean pinball on train-val) is optional. Size: about 200 trees × 15 leaves ≈ 60 to 80 KB per file, about 3 MB for all 42 (budget: 10 MB).

### 4.3 Quantile monotonicity (ORA-R2.3, ORA-P1)

Raw `q10, q50, q90` per lead are sorted ascending (`quantiles.repair`), which is the minimal L1 repair for three values. It returns a flag per lead. The tool counts corrected leads and adds the warning `quantile crossing repaired on k of H lead days` when k > 0. The same repair is applied after calibration (§4.4) as the final guarantee.

### 4.4 Conformal calibration (CQR) and the `coverage` parameter (ORA-R3, ORA-P3)

Calibration set: `as_of` in 2012 to 2016 after purge, per (station, lead), about 1,800 points. Scores in target space (log ratio), so back-transforming is monotone:

`E_i = max(q10(x_i) − y_i, y_i − q90(x_i))`

Scores are stored sorted in `conformity.parquet` (`station_id, lead, score`). For nominal coverage `c` in [0.5, 0.99]:

- `k = ceil((n + 1)·c)`; `Q̂_c = score_sorted[min(k, n) − 1]`. If `k > n`, use the maximum score and add a warning (not enough calibration points for that coverage).
- Interval in target space: `lo = q10' − Q̂_c`, `hi = q90' + Q̂_c`, with `q10' ≤ q50' ≤ q90'` after repair. Then `lo ← min(lo, q50')`, `hi ← max(hi, q50')` so the median stays inside when `Q̂_c` is negative (coverage below the raw 0.8).
- Back-transform lo, q50', hi with the anchor `Q_t`.

Nesting: `Q̂_c` is non-decreasing in `c` because it indexes a sorted array at a non-decreasing rank, so `lo` is non-increasing and `hi` is non-decreasing in `c`, and the `min`/`max` with `q50'` preserve that. Higher coverage never gives a narrower interval, exactly (ORA-P3). The default is `c = 0.8`.

Small calibration sets (ORA-R3.4): minimum `n_cal = 500` per (station, lead). Below that, the station falls back to the pooled scores of all stations for that lead, `Q̂` is inflated by a factor of `1 + 1/√n`, and a warning is added. Core data gives about 1,800 per pair, so this is a safety path with a unit test.

Honest caveats, in the model card and in warnings text: daily series are autocorrelated, so the exchangeability behind the conformal guarantee does not strictly hold. Coverage is marginal over seasons, not conditional on flood conditions. The 2022 stress test measures the consequence. A Mondrian (monsoon vs non-monsoon) variant is a stretch task, adopted only if it improves stress-season coverage on the train-val data.

`calibration` output: `method="split_conformal"`, `nominal_coverage = c`, `n_calibration = n` for the station and the median lead (the minimum over leads is also reported in a warning if it is below 500).

### 4.5 Exceedance probability (ORA-R4.2, ORA-P6)

For each lead date, build a CDF `F` of discharge from the **default-coverage** calibrated knots (0.8 interval, independent of the requested `coverage`):

- Knots `(x, F)`: `(p10_cal, 0.10), (p50, 0.50), (p90_cal, 0.90)` in `ln(Q+1)` space, with `p10_cal` and `p90_cal` the 0.8-calibrated interval ends. Treat them as the 0.1 and 0.9 quantiles.
- Tails: extend linearly in `ln(Q+1)` using the slope of the adjacent segment to pseudo-knots at `F = 0.01` and `F = 0.99` (lower end clipped at `ln(1) = 0`). Beyond them, `F` is 0 and 1.
- Equal x values (zero width) become vertical steps; this keeps `F` monotone.
- `p_exceed(T) = 1 − F(ln(T+1))`, clipped to [0, 1].

`F` is a monotone non-decreasing piecewise-linear function, so `p_exceed` is non-increasing in `T` and in [0, 1] (ORA-P6). It is an approximation with extrapolated tails; the tool states the method in `notes`-style warnings only when the threshold falls in a tail. Result is `[]` when no threshold is known.

### 4.6 Out-of-distribution flag (ORA-R5.2)

`manifest.json` stores per-feature training min and max (refit split). At forecast time a feature is "out of range" if it lies outside `[min − 5% of range, max + 5% of range]`. If any are, add `input features outside training range: <up to 3 names> (+n more); the forecast extrapolates`. The flag does not alter the numbers.

### 4.7 Explanations (ORA-R4.5)

`explain_forecast(run_id)` loads the stored feature row and recomputes with `Booster.predict(X, pred_contrib=True)` on the p50 model of the **peak lead** (the lead with the largest p50; ties to the earliest). Contributions `φ_f` and bias `φ_0` are exactly additive in target (log-ratio) space.

- `baseline_m3s = (Q_t + 1)·exp(φ_0) − 1`, the model's average prediction for this anchor.
- Contribution in m³/s: `c_f = (p50_peak − baseline_m3s) · φ_f / Σφ` (log-share allocation). It sums to the difference (up to float error). If `Σφ = 0`, all zero. Direction = sign of `c_f`.
- Features are grouped by family for the narrative (level and trend, upstream flow, basin rainfall, temperature, season). The tool returns the top 5 individual features and the narrative names the top family.
- Narrative is a template with slots (peak date, lead, p50, baseline, top three drivers with plain-language labels from a dictionary, and the interval). No LLM. Each label says "modeled".

## 5. Algorithms and data flow

`forecast_river(in)`:
1. Validate: `horizon_days` in 1..14, `coverage` in [0.5, 0.99], `as_of` within the valid window, `station_id` known and `role` includes forecast. Unknown station: `NOT_FOUND` with up to 3 nearby station ids (by cell distance). Otherwise `INVALID_INPUT`.
2. Load history through `data/loader` (demo) or `live` (live with fallback to the cache and a warning). Check gaps (§6).
3. `build_features` with `as_of`; OOD check.
4. For each lead 1..H: three raw quantiles, repair, CQR at `coverage`, back-transform. Also the 0.8-calibrated pair for exceedance.
5. Exceedance rows, `danger_threshold_m3s` (null when unknown), warnings (threshold method, repairs, OOD, small calibration, tail extrapolation).
6. Store `(run_id, station, as_of, features, bundle hash, output)` in `RunStore`. Return the envelope with `target_kind="modeled_glofas"` and `target_label` constants.

Determinism (ORA-P4): fixed seed in training; inference has no randomness; LightGBM single-thread predict; sorted outputs. `data` is byte-identical for identical inputs except envelope `run_id` and `generated_at`.

## 6. Live mode and gaps

- Live (optional): Flood API `past_days=60&forecast_days=0&timezone=GMT` for the station and its upstream stations; Forecast API `past_days` for rain of the last days plus the archive API for older days (ERA5 lags). Results cached in DuckDB; any failure falls back to the last cache with a warning, or to demo data with a warning (ORA-R11.2).
- Gaps (ORA-R1.4): a missing day inside the feature window is forward-filled when the gap is at most 2 days and a warning lists the dates. A longer gap returns `UPSTREAM_UNAVAILABLE` (retryable) in live mode. The demo dataset has no gaps; the build script fails otherwise.
- Tests run with sockets disabled; live code runs against recorded fixtures in `tests/fixtures/`.

## 7. Persistence

`RunStore` (DuckDB file in a volume, in-memory fallback): `runs(run_id, created_at, station_id, as_of, features_json, output_json)`. Kept at least 24 h, purged after 48 h, capped at 1,000 rows, writes under a lock. `explain_forecast` on an unknown or expired id returns `NOT_FOUND`.

## 8. Interfaces and errors

Tool I/O follows `mcp-contracts.md` §4.

| Condition | Result | retryable |
|---|---|---|
| horizon, coverage, `as_of`, or station role invalid | `INVALID_INPUT` | false |
| unknown station (nearby ids in the message) | `NOT_FOUND` | false |
| unknown or expired `run_id` | `NOT_FOUND` | false |
| live data gap above limit | `UPSTREAM_UNAVAILABLE` | true |
| model manifest hash mismatch, unexpected error | `INTERNAL` | false |

Provenance: `organ=oracle`, `model = {name:"lightgbm-cqr", version, sha256: root hash}`, `data_sources` for Open-Meteo Flood API (GloFAS v4, CC BY 4.0) and Open-Meteo Historical Weather API (ERA5), with `as_of` the dataset end date, `mode`. Station cell coordinates are returned in the `forecast_river` output (proposed contract change C2, since `Provenance` has no field for them).

Server: MCP Python SDK (`FastMCP`), stdio and streamable HTTP, `GET /healthz` (bundle loaded and hash-verified, dataset loaded, store writable).

## 9. Training and compute plan

Honest note on the owner's constraint: the core model needs **no GPU**. 42 LightGBM boosters on about 42k rows each train in a few minutes on the i5 laptop. Colab and Modal are used only for convenience and for the stretch MLP.

| Job | Where | Estimated time | Cost | Tier |
|---|---|---|---|---|
| Build dataset (`build_oracle_demo.py`) | laptop (network) | 5 to 10 min | 0 | core |
| Train 42 boosters, fixed hyperparameters | laptop CPU, or Colab free CPU runtime | 3 to 6 min | 0 | core |
| Optional random search, 20 configs | laptop CPU, or Colab free | 30 to 60 min | 0 | stretch |
| Calibration scores, eval | laptop | under 2 min | 0 | core |
| PyTorch quantile MLP comparison | Colab free T4 or CPU | 5 to 10 min | 0 | stretch |
| Mondrian conformal variant | laptop | under 5 min | 0 | stretch |

Checkpoint and resume: training is idempotent per booster. `train_gbm.py --resume` skips boosters whose file exists with a matching config hash, so a disconnected Colab session loses at most one booster. Notebook `oracle_train.ipynb` mounts Drive only for the output copy; the repo is cloned at a pinned commit, and package versions are pinned in the first cell. Modal is not needed (planned spend: $0). The MLP stretch, if run on Modal, is a few cents.

## 10. Evaluation (`evals/oracle/`)

`python -m evals.oracle.run --seed 0 [--fast]`, results in the dashboard schema, every record carrying `target_kind="modeled_glofas"` and the label (ORA-P8).

- Splits: all metrics on test (2017 to 2023). `--fast` uses a subsample of `as_of` dates (every 7th day) and two stations.
- Metrics by lead (1 to 14) and station: pinball loss at 0.1, 0.5, 0.9; quantile-approximated CRPS; coverage of the 0.5, 0.8, 0.9 intervals vs nominal; mean interval width (m³/s and relative to p50); exceedance Brier score for the danger threshold.
- Quantile-approximated CRPS: `CRPS ≈ 2·Σ_τ w_τ·pinball_τ` with `τ ∈ {0.1, 0.5, 0.9}` and `w = (0.3, 0.4, 0.3)`. It is a coarse surrogate, comparable only between models scored the same way, and the report says so.
- Baselines: **persistence** (point value `Q_t`, plus a probabilistic version with empirical log-ratio quantiles per lead from the train split) and **climatology** (quantiles of the same day of year ±15 days over the train years). Skill score `1 − CRPS_model / CRPS_baseline`.
- **2022 stress test** (as_of 2022-06-01 to 2022-10-31): same metrics reported separately, with empirical coverage vs nominal. ORA-P7 is checked here: coverage ≥ nominal − 0.05 over the whole test period; the stress-season coverage is reported even if lower, with no tuning on it.
- Lead widening check (ORA-R5.1): mean relative width is non-decreasing in lead on average; reported as a metric and asserted in the eval with a 5% tolerance.
- Gauge validation (stretch, ORA-R9): only if cheap, redistributable readings exist. Reported as "observed gauge validation (small n)". Otherwise the eval writes `observed_validation: "not performed"`.
- Optional MLP vs GBM comparison (stretch).

## 11. Correctness properties and how they are tested

Hypothesis strategies (`tests/strategies.py`): `quantile_triples()` (any finite floats, including crossed order, zeros, huge values), `score_arrays()` (sorted non-negative or signed, n from 1 to 3,000), `history_frames()` (1 to 3 stations, 60 to 400 days of positive discharge with gaps removed, rain and temperature), `station_catalogs()`, `valid_requests()` (station, horizon 1 to 14, as_of in window, coverage 0.5 to 0.99). A **stub bundle** (deterministic function of features, no LightGBM) runs property tests fast. A small committed fixture bundle (a few real boosters) runs smoke tests. Profile `ci`: 200 examples, deadline off. Tolerance `1e-9` unless stated.

| ID | Property | Test approach |
|---|---|---|
| ORA-P1 | p10 ≤ p50 ≤ p90 at every lead | `quantile_triples()` through `repair` and CQR for random `Q̂` and coverage; also end to end with the stub bundle for random requests |
| ORA-P2 | all discharge ≥ 0 and finite | extreme target values (±60 in log space), `Q_t` from 0 to 1e6 |
| ORA-P3 | coverage `c1 < c2` gives nested intervals (`lo2 ≤ lo1`, `hi2 ≥ hi1`) per lead | `score_arrays()`, random triples, two coverages; exact comparison |
| ORA-P4 | same (station, as_of, snapshot) gives the same `data` | run twice, and once with shuffled row order of the input frames |
| ORA-P5 | changing data after `as_of` changes nothing | perturb or delete all rows dated after `as_of` (random values, NaN rows); features and full output must be identical. Plus `splits.assert_disjoint()` and a purge test on real split definitions |
| ORA-P6 | `p_exceed` in [0, 1] and non-increasing in threshold | random knots (including equal and zero-width), sorted thresholds, strictly checked; also `p_exceed` at `p50` equals 0.5 within 1e-9 |
| ORA-P7 | empirical coverage ≥ nominal − tolerance | **unit**: exchangeable synthetic data (seeded noise model, 20k points, n_cal = 2,000), tolerance 0.03. **eval**: real test period and the 2022 stress season as reports, not unit assertions |
| ORA-P8 | `target_kind = "modeled_glofas"` and the label in every result and eval record | contract test over random valid requests; eval report schema check; lint test scanning `src/`, templates, tool descriptions, and docs for `gauge`, `observed`, `measured`, with an allowlist for the stretch label "observed gauge validation (small n)" |

Extras:

| ID | Property | Test approach |
|---|---|---|
| ORA-X1 | `lead_days = 1..H` contiguous, dates are `as_of + lead` | `valid_requests()` |
| ORA-X2 | `exceedance_prob` has one row per forecast row, and equals `[]` when no threshold | same |
| ORA-X3 | tampered model file or manifest refuses to load | unit: flip one byte; expect `INTERNAL` |
| ORA-X4 | SHAP additivity: `φ_0 + Σφ_f` equals the raw p50 prediction in target space within 1e-6; `Σ c_f` equals `p50 − baseline` | fixture bundle |
| ORA-X5 | OOD flag fires when one feature is moved beyond its range and does not fire inside | unit and Hypothesis |
| ORA-X6 | station order and frame row order do not affect features | permutation test |
| ORA-X7 | `Q̂_c` non-decreasing in `c`; `k > n` path warns and uses the max score | `score_arrays()` |
| ORA-X8 | small-calibration fallback inflates and warns | unit, n_cal = 50 |
| ORA-X9 | `as_of` outside the valid window returns `INVALID_INPUT`; unknown station returns `NOT_FOUND` with nearby ids | unit |
| ORA-X10 | gap rules: 2-day gap filled with warning; 3-day gap returns `UPSTREAM_UNAVAILABLE` (live fixture) | unit |

Contract tests validate real tool output against the JSON Schemas from `stitch_common`. Demo-mode tests run with `no_network`.

## 12. Decisions needed from the owner, and requirement issues

Owner confirmation:
1. Open-Meteo non-commercial terms accepted for a hackathon demo, with CC BY 4.0 attribution in the UI footer.
2. Station list and the cell chosen by the build script (probing picks the largest river cell; a human check of the printed table is needed).
3. Danger thresholds: modeled 5-year return level as the default (flagged), or supply official levels in cusecs.
4. Valid `as_of` window starts 2017-01-01 (calibration cutoff) so no calibration data postdates `as_of`.

Requirement issues (requirements.md is not edited):
1. **ORA-R1.1** says features come from Open-Meteo *forecast* data. Training needs history back to 1984, and rainfall forecast archives start in 2021. The core model uses reanalysis-only features available at `as_of`. Reword R1.1 or accept this design.
2. **ORA-R5.1** says widening with lead is "see ORA-P3", but ORA-P3 is coverage nesting. Add a separate property for lead widening (this design checks it in the eval).
3. **ORA-R8.2** forbids "gauge/observed" wording while **ORA-R9** needs "observed gauge validation". The design allows the phrase only in the stretch validation label.
4. **ORA-R3.2** with `coverage` ≠ 0.8: the contract names the interval fields `p10/p90`, which would be mislabeled for other coverages (see C1).

## 13. Risks

| Risk | Mitigation |
|---|---|
| R1. Open-Meteo series after July 2022 differs in source (reanalysis to forecast join) and distorts the 2022 stress test | build script reports the join; if a break is found, the stress test restricts to the clean span and the doc says so; as fallback use `forecast_days`/`past_days` archive values for the stress season only |
| R2. Cell snapping picks a tributary or canal cell | probe grid plus owner review of the printed table; coordinates recorded |
| R3. Interval coverage in the 2022 season is below nominal | report honestly; Mondrian variant as stretch; the UI shows the stress result |
| R4. Series after 2012 differ in distribution (climate trend) | calibration set is the nearest 5 years to the test period |
| R5. Free API terms change or rate limits | demo mode never calls the API; build needs under 30 calls |
| R6. LightGBM wheel issues in the image | pin version, check the import in the Docker build early; fallback is sklearn HGB with a hash-verified JSON tree export |
| R7. Model too complex for the 3-day window | minimal path in tasks.md (fixed leads 1, 3, 7, 14 and linear interpolation of quantiles is the cut-down variant) |

## 14. Proposed contract changes (not applied; steering files are not edited)

- **C1** `calibration`: add `interval_lower_q` and `interval_upper_q` (numbers), the quantile levels the `p10`/`p90` fields represent at the requested coverage (for example 0.05 and 0.95 at 0.9). Document that `Interval.p10/p90` are the lower and upper interval bounds at the requested coverage.
- **C2** `forecast_river` output: add `station: { name, river, cell_lat, cell_lon, requested_lat, requested_lon }` so cell coordinates are returned (ORA-R8.3).
- **C3** `forecast_river` output: add `quantile_correction_applied: bool` (ORA-R2.3 reporting; currently only in `warnings`).
- **C4** `explain_forecast` output: add `lead_days_explained: int` and a `feature_group` on each driver.
- **C5** New read-only resource `oracle://stations` listing station ids, names, roles, cell coordinates, threshold and its method, and the valid `as_of` window, so the Brain and UI do not hard-code them.
- **C6** `forecast_river.forecast[].rainfall_mm` stays optional and is omitted by the core model; document that absence is normal.
