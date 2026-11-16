# oracle-mcp: Requirements

Organ: quantile forecasting of river discharge and rainfall. Prefix `ORA`. Contract: `mcp-contracts.md` §4.

## Introduction
The Oracle predicts river discharge at a gauge station for 1 to 14 days ahead, with p10/p50/p90 quantiles and conformally calibrated intervals, and explains the main drivers.

## Glossary
- **Station**: a river gauge or a grid-cell proxy (e.g. Indus at Guddu/Sukkur/Kotri).
- **Conformal interval**: an interval whose empirical coverage is guaranteed marginally on exchangeable data by split conformal prediction (conformalized quantile regression).
- **CRPS**: continuous ranked probability score, approximated from quantiles.

## Requirements

### ORA-R1 Data inputs
1. THE Oracle SHALL build features from Open-Meteo (forecast and flood API), ERA5 reanalysis, and gauge data where available.
2. WHERE `mode = demo`, THE Oracle SHALL read pre-cached Parquet files from `data/demo/` and make no network calls.
3. WHERE `mode = live`, THE Oracle SHALL fetch Open-Meteo data, cache it in DuckDB/Parquet, and degrade to the last cached data with a warning when the network is down.
4. IF required input data has gaps above a configured length, THEN THE Oracle SHALL return a result with a `warnings` entry or `UPSTREAM_UNAVAILABLE` and not impute silently.

### ORA-R2 Model
1. THE Oracle SHALL train a quantile model (PyTorch or gradient boosting, selected in design) for quantiles 0.1, 0.5, and 0.9 per lead day.
2. THE Oracle SHALL ship a trained demo model and a reproducible training script with a fixed seed.
3. THE Oracle SHALL enforce quantile monotonicity in output (p10 <= p50 <= p90) by construction or by sorting, and report whether a correction was applied.
4. THE Oracle SHALL not use information dated after `as_of` (no leakage) in features, training splits, or calibration.

### ORA-R3 Calibration
1. THE Oracle SHALL apply split conformal calibration (CQR) on a held-out chronological calibration set.
2. WHEN `coverage` is requested, THE Oracle SHALL adjust the interval to the nominal coverage using stored conformity scores. Default is 0.8 (the p10 to p90 band).
3. THE Oracle SHALL report calibration metadata (method, nominal coverage, `n_calibration`).
4. IF the calibration set has fewer than a configured minimum number of points for a station, THEN THE Oracle SHALL widen the interval conservatively or warn, as defined in design.

### ORA-R4 Tools
1. WHEN `forecast_river` is called with a valid `station_id` and `horizon_days`, THE Oracle SHALL return one forecast row per day with `lead_days = 1..horizon_days`.
2. THE Oracle SHALL return `exceedance_prob` for the station's danger threshold, derived from the predictive quantiles, when a threshold is known.
3. IF `station_id` is unknown, THEN THE Oracle SHALL return `NOT_FOUND` with nearby valid stations in the message.
4. IF `horizon_days` is outside 1 to 14, THEN THE Oracle SHALL return `INVALID_INPUT`.
5. WHEN `explain_forecast` is called with a prior `run_id`, THE Oracle SHALL return the top feature contributions (SHAP-like or gradient-boosting contributions) and a template-generated narrative. IF the `run_id` is unknown, THEN `NOT_FOUND`.

### ORA-R5 Uncertainty honesty
1. THE Oracle SHALL widen (never narrow) intervals as lead time grows, on average (see ORA-P3).
2. THE Oracle SHALL flag forecasts where input features lie outside the training range (out-of-distribution) with a warning.

### ORA-R6 Performance and ops
1. THE Oracle SHALL return a forecast in under 2 s p95 on CPU with cached data.
2. THE Oracle SHALL expose `GET /healthz` and a `Provenance` block listing data sources, model name, version, and SHA-256.

### ORA-R7 Eval
1. THE Oracle eval SHALL report CRPS, pinball loss per quantile, empirical interval coverage versus nominal (including on the 2022 flood season as a stress test), interval width, and a baseline (persistence and climatology) comparison, by lead day.

## Correctness properties (formalized in design)
- ORA-P1: for all outputs, p10 <= p50 <= p90 at every lead day.
- ORA-P2: all discharge values are >= 0.
- ORA-P3: higher nominal coverage never yields narrower intervals (nesting).
- ORA-P4: the forecast is a deterministic function of (station, as_of, data snapshot).
- ORA-P5: changing data dated after `as_of` does not change the forecast (no-leakage).
- ORA-P6: `exceedance_prob` is in [0,1] and non-increasing in the threshold.
- ORA-P7: on the held-out calibration protocol, empirical coverage >= nominal minus a stated tolerance (eval check, not a unit property).

## Out of scope
Hydrodynamic modeling. Real-time gauge ingestion from Pakistan WAPDA/FFD if no public API is available.

## Open questions
1. Which gauge/discharge source is acceptable? Candidates: GloFAS via Open-Meteo Flood API (modeled discharge, grid-based), or public historical gauge series. Proposal: GloFAS discharge via Open-Meteo as the "gauge" target, and be explicit that it is modeled.
2. Gradient boosting (LightGBM or sklearn HistGradientBoosting quantile) vs PyTorch? Proposal: gradient boosting + CQR as the core, with a small PyTorch quantile MLP as a stretch comparison.
