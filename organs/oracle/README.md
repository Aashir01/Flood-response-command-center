# oracle-mcp

The Oracle organ of Stitch. It forecasts **modeled river discharge (GloFAS via Open-Meteo)** at the GloFAS grid cell nearest to five places on the Indus system (Chenab near Trimmu, Indus near Taunsa, Guddu, Sukkur, Kotri), 1 to 14 days after `as_of`, with a median, a split-conformal interval at the requested coverage, the probability of exceeding a danger threshold (a modeled 5-year return level, an assumption) and a TreeSHAP explanation. The target is model output, never a gauge record. Method, evaluation and limits: `docs/oracle-model.md`. Model card: `models/model_card.md`.

## Tools and resource (contract v0.4, `.kiro/steering/mcp-contracts.md` section 4)

| Name | What it does |
|---|---|
| `forecast_river` | `{station_id, horizon_days 1..14, as_of?, coverage? (0.5..0.99, default 0.8), mode?}`. One row per lead, `exceedance_prob`, `calibration` (with `interval_lower_q/upper_q`), `station` (the grid cell read), `quantile_correction_applied`, `target_kind = "modeled_glofas"`. Valid `as_of`: 2017-01-01 to 2023-12-31 in demo mode. Without `as_of` the last date in the data is used, with a warning. |
| `explain_forecast` | `{run_id}` of a prior `forecast_river` (the call's `provenance.run_id`). Top five drivers in m³/s with their family, baseline, lead explained, template narrative. |
| `oracle://stations` | station ids, grid-cell coordinates, role, danger threshold and its method, valid `as_of` window. |

Errors: `INVALID_INPUT` (horizon, coverage, `as_of` window, feature-only station), `NOT_FOUND` (unknown station, with nearby ids; unknown or expired `run_id`), `UPSTREAM_UNAVAILABLE` (live gap longer than 2 days, retryable), `INTERNAL` (model bundle hash mismatch).

## Modes

- `demo` (default): committed `data/demo/oracle/` Parquet and the committed model bundle. No network; tests run with sockets blocked.
- `live` (optional, `mode: "live"` or `STITCH_MODE=live`, and only for `as_of` after the demo data): Open-Meteo Flood API (last 92 days) and Forecast API (rain, temperature), cached as Parquet in `STITCH_ORACLE_LIVE_CACHE` (default `data/cache/oracle`). On a failed fetch the last cache is used with a warning; with no cache the result falls back to demo data with a `MODE_FALLBACK` warning and `mode = demo`.

## Layout

```
src/stitch_oracle/
  core/        pure logic: features, splits, dataset, bundle, quantiles, conformal, exceedance,
               ood, gaps, explain, forecast, metrics, baselines, stations
  data/loader.py   committed dataset with schema checks
  live.py      optional Open-Meteo client and cache
  store.py     DuckDB run store for explain_forecast (in memory unless STITCH_ORACLE_DB is set)
  service.py   contract models <-> core, provenance, errors
  server.py    thin MCP layer (stitch_common.mcp_app), oracle://stations, GET /healthz
models/        42 LightGBM text models (gzip), conformity.parquet, manifest.json, model_card.md
training/      train_gbm.py, config.yaml, oracle_train.ipynb, train_mlp.py (comparison only)
tests/         unit/ property/ contract/, fixtures/ (recorded Open-Meteo responses), stdio smoke
```

## Run

```
uv sync --all-packages
uv run python -m stitch_oracle.server --stdio                 # stdio (Kiro, Brain)
uv run python -m stitch_oracle.server --http --port 8000      # streamable HTTP, GET /healthz
uv run pytest organs/oracle -q                                # add --hypothesis-profile=ci for 200 examples
uv run python -m evals.run --organ oracle --seed 0 [--fast]
uv run python organs/oracle/training/train_gbm.py             # retrain, about 4 min on CPU
uv run python scripts/mcp_probe.py oracle-mcp --timeout 180
```

Environment: `STITCH_MODE`, `STITCH_ORACLE_DB`, `STITCH_ORACLE_MODELS`, `STITCH_DEMO_DIR`, `STITCH_ORACLE_LIVE_CACHE`.

## Attribution

Weather data by Open-Meteo.com (CC BY 4.0). GloFAS (Copernicus Emergency Management Service / ECMWF). ERA5 (Copernicus C3S). Free non-commercial tier, accepted for this demo.
