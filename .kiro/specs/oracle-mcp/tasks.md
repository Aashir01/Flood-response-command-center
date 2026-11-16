# oracle-mcp: Tasks

Tags: `core` (must ship), `stretch`. `MVP` marks the minimal viable path: demo Parquet, LightGBM, CQR, `forecast_river`, eval. Each task lists the requirements and properties it satisfies, the tests that prove it, and "Done when". Commit after each task (`feat(oracle): ...`).

Blocked by the **bootstrap** spec: `stitch_common` models and envelope, the `surgeon` agent, hooks, `no_network` fixture, eval runner. If bootstrap is late, tasks 2 and 3 (data build, training) do not depend on it and can start first.

## Schedule (Oracle window: Nov 23 to 25)

| Day | Plan |
|---|---|
| Nov 23 | Tasks 1 to 4 (scaffold, dataset, features and splits, training). Kick off Eyes training job A in parallel (see eyes-mcp tasks 1 to 4); it runs unattended on Colab. |
| Nov 24 | Tasks 5 to 10 (conformal, exceedance, bundle, tools, store, properties) |
| Nov 25 morning | Tasks 11 to 13 (eval, docs, THIRD_PARTY). Hand over to Eyes. |
| Cut first if late | 17 (MLP), 16 (Mondrian), 15 (live mode), 14 (contract change entries, if not approved), then the eval stress report detail. Never cut: 2, 3, 4, 5, 6, 8, 9, 11. |

- [ ] **1. Scaffold the organ with `surgeon`** `core` `MVP`
  - Generate `organs/oracle/` (pyproject, `src/stitch_oracle`, `tests/{unit,property,contract}`, `models/`, `training/`, README). Add dependencies: `lightgbm`, `pandas`, `pyarrow`, `duckdb`, `numpy`; `httpx` as an optional extra for live mode.
  - Confirm `no_network` is on by default, Hypothesis profiles `dev` and `ci` load, ruff and mypy apply. Verify the LightGBM wheel imports in the target Docker base image.
  - Done when: `uv run pytest` passes on the skeleton and the LightGBM import check passes in the image.

- [ ] **2. Dataset build script and committed demo data** `core` `MVP`
  - `scripts/build_oracle_demo.py`: station cell probing (5×5 offsets at 0.05°, `cell_selection=nearest`, keep the highest mean discharge, print requested vs returned coordinates), discharge fetch (`timezone=GMT`), ERA5 daily rain and temperature for 4 rain points and 1 temperature point, validation (no gaps, no negatives, 2022-06-01 to 2023-12-31 continuity, report of the reanalysis/forecast join), danger thresholds from 1985 to 2016 only, write `data/demo/oracle/{discharge_daily,rain_daily}.parquet`, `stations.json`, `MANIFEST.md` (source URLs, license CC BY 4.0, build date, content hashes).
  - Fewer than 30 requests, sleep between calls, no key.
  - `data/loader.py` with schema validation. Tests: schema, dtypes, no gaps, no negatives, unique keys, sizes under the 2 MB budget, `stations.json` fields complete. Refs: ORA-R1.2, R8.3, R11.1. THIRD_PARTY rows: Open-Meteo (CC BY 4.0), GloFAS, ERA5.
  - Done when: the loader reads committed files offline, the manifest records the returned cell coordinates, and the owner has confirmed the station table (design §12).
  - Fallback: if the post-July-2022 series is broken, record it in the manifest, restrict the stress window to the clean span, and continue.

- [ ] **3. Features, splits, no-leakage** `core` `MVP`
  - `core/features.py` (`build_features(frames, station, as_of)` slicing to `<= as_of` first), `core/splits.py` (definitions, purge, `assert_disjoint`), fixed feature schema with NaN slots for missing upstreams.
  - Tests: unit tests per feature on hand-computed tiny series; ORA-P5 (perturb future rows, features identical); ORA-X6 (row and station order); split disjointness and purge unit tests. Refs: ORA-R2.4, R1.4. P5.
  - Done when: P5 and X6 pass under `ci` and the split table in the design is reproduced by a test.

- [ ] **4. Training script, config, notebook, first model** `core` `MVP`
  - `training/train_gbm.py` + `config.yaml` (§4.2 values, seed 0, single thread), `--resume` (skip finished boosters by config hash), writes `models/lgbm/<q>_<lead>.txt`, `manifest.json` (per-file SHA-256, root hash, feature list, per-feature train min and max, config hash, git commit), `model_card.md`.
  - `training/oracle_train.ipynb`: first cell pins package versions and clones the repo at a pinned commit; runs the same script; copies outputs to Drive. Works on the free Colab CPU runtime or the laptop (no GPU needed).
  - Optional random search script behind a flag (stretch).
  - Tests: determinism (train twice on a tiny fixture, identical files); manifest verification (ORA-X3); size check (all models under 10 MB). Refs: ORA-R2.1, R2.2, R10. X3.
  - Done when: `models/` is committed with a verified manifest, training takes under 10 min on the laptop, and a rerun is byte-identical.
  - Fallback if time runs out: train only leads {1, 3, 7, 14} and interpolate the three quantiles linearly in log space between them for the other leads; label this in `model_card.md` and a warning. If LightGBM fails to train usefully, ship the empirical log-ratio persistence quantiles (per lead, per month) as `model.name = "persistence-empirical"` with a clear warning.

- [ ] **5. Quantile repair and CQR** `core` `MVP`
  - `core/quantiles.py` (sort-based repair with correction flags), `core/conformal.py` (score computation, sorted storage in `conformity.parquet`, `Q̂_c` lookup with the `k > n` path, nested interval adjustment, small-calibration fallback).
  - Calibration step added to `train_gbm.py` (or `training/calibrate.py`) writing scores and extending the manifest.
  - Property tests: P1, P2, P3, X7, X8; P7 (synthetic exchangeable coverage). Refs: ORA-R2.3, R3. 
  - Done when: P1, P2, P3, P7, X7, X8 pass under `ci`.

- [ ] **6. Exceedance and thresholds** `core` `MVP`
  - `core/exceedance.py` (piecewise CDF in log space, tail extension, step handling). Threshold method and warning text. 
  - Property tests: P6, X2. Unit tests: hand-computed values at knots, tail cases, zero-width. Refs: ORA-R4.2, R5. P6.
  - Done when: P6 passes and exceedance at `p50` equals 0.5.

- [ ] **7. Model bundle, OOD, forecast pipeline** `core` `MVP`
  - `core/bundle.py` (load text models, verify hashes, predict raw quantiles), `core/ood.py`, and the `forecast` orchestration function in core (§5 steps 1 to 5) with the warning set.
  - Tests: end-to-end with the stub bundle (properties P1, P2, P4, X1, X9) and the real committed bundle (smoke: a plausible 2022-08-15 forecast for Sukkur, no NaN). X5 (OOD). Refs: ORA-R2, R4.1, R4.3, R4.4, R5.2. P4.
  - Done when: P4 and X1 pass, the real-bundle smoke test passes, and p95 latency of a 14-day forecast is under 2 s on a 2 vCPU limit (ORA-R6.1).

- [ ] **8. RunStore and `explain_forecast`** `core` `MVP`
  - `store.py` (DuckDB, TTL, cap, lock, in-memory fallback). `core/explain.py` (`pred_contrib` on the p50 booster at the peak lead, log-share allocation to m³/s, top-5 features, family grouping, label dictionary, narrative template).
  - Tests: store round-trip, expiry with an injected clock, cap eviction; X4 (additivity); narrative snapshot tests (every label contains "modeled" where a discharge is named); unknown id returns `NOT_FOUND`. Refs: ORA-R4.5.
  - Done when: X4 passes and the narrative for the demo run reads correctly in a review.

- [ ] **9. MCP server, envelope, health** `core` `MVP`
  - `server.py`: `forecast_river`, `explain_forecast`, error mapping, provenance (model root hash, data sources, mode), `/healthz`, stdio and HTTP. Constants `target_kind` and `target_label`.
  - Contract tests: real output validates against schemas with `additionalProperties: false`. P8 (random valid requests, plus the wording lint over source, templates, tool descriptions, docs). Smoke test: start the server, list tools, call both. Refs: ORA-R4, R6.2, R8. P8.
  - Done when: the contract hook passes and P8 passes.

- [ ] **10. Remaining properties and offline checks** `core`
  - Fill any property in the design table not yet covered (P1 to P8, X1 to X10). Run the full suite with sockets disabled. Add named regression tests for any failing example. X10 uses a live-mode fixture if task 15 exists, otherwise a unit test on the gap function.
  - Done when: every row of the design property table maps to a passing test.

- [ ] **11. Eval harness** `core` `MVP`
  - `evals/oracle/`: baselines (persistence deterministic and probabilistic, climatology), metrics (pinball, quantile-approximated CRPS, coverage at 0.5, 0.8, 0.9, width, Brier for exceedance), by lead and station, the 2022 stress report, lead-widening check, skill vs baselines. `--fast` subsample. Write results in the dashboard schema, every record with `target_kind`. Include `observed_validation: "not performed"` unless task 18 lands.
  - Tests: metric unit tests on hand-computed examples; smoke run of `--fast`. Refs: ORA-R7, R8.1. P7 (eval), P8.
  - Done when: `python -m evals.run --organ oracle --seed 0` is reproducible, and the report states the test and stress coverage vs nominal whatever they are.

- [ ] **12. Documentation** `core` `MVP`
  - `organs/oracle/README.md`; `docs/oracle-model.md` (target and wording rules, features, splits, CQR and nesting, exceedance method, thresholds as assumptions, limitations: autocorrelation, reanalysis-only features, Kotri regulation); `models/model_card.md` finalised. Add the property-testing story (P1 to P8) to `docs/kiro-writeup.md`.
  - Done when: a reader can reproduce §4 from the doc and no document calls the target a gauge or observation.

- [ ] **13. THIRD_PARTY and manifest check** `core` `MVP`
  - Rows for LightGBM (MIT), Open-Meteo (CC BY 4.0, non-commercial free tier note), GloFAS, ERA5, DuckDB, pandas, pyarrow. Check `data/demo/MANIFEST.md` lists the Oracle data.
  - Done when: a new dependency check finds no unlisted package.

- [ ] **14. Station resource and contract change log entries** `core`
  - If the owner approves the proposed contract changes C1 to C5: update `mcp-contracts.md`, `stitch_common`, server, and consumers in one change; add resource `oracle://stations`. Otherwise keep the fallback (station note in `warnings`, cell coordinates in `MANIFEST.md`).
  - Done when: the contract hook passes with the approved set.

- [ ] **15. Live mode with cache and fallback** `stretch`
  - `live.py`: Flood API and rain fetch, DuckDB cache, fallback to cache then to demo data with a warning, gap rules (≤ 2 days filled with a warning, longer returns `UPSTREAM_UNAVAILABLE`). Tests against recorded fixtures with sockets disabled; one `@pytest.mark.live` test excluded from CI. Refs: ORA-R1.3, R1.4, R11.2. X10.
  - Done when: a simulated outage returns cached data with a warning.

- [ ] **16. Mondrian (monsoon) conformal variant** `stretch`
  - Scores stored per stratum; adopt only if it improves train-val stress-season coverage without breaking P3. Reports both in the eval.

- [ ] **17. PyTorch quantile MLP comparison** `stretch`
  - `training/train_mlp.py` on the same features and splits, pinball loss, Colab free (or CPU). Result goes to the eval table only; not shipped.

- [ ] **18. Observed gauge validation** `stretch`
  - Only if public readings for Guddu, Sukkur, or Kotri are redistributable and cheap. Report separately as "observed gauge validation (small n)". Otherwise skip. Refs: ORA-R9.

- [ ] **19. Rainfall-forecast features** `stretch`
  - Historical Forecast API (2021+) variant with a short training window; report separately; fill `rainfall_mm` only if shown to help.

## Traceability

| Requirement | Tasks |
|---|---|
| ORA-R1 | 2, 3, 15 |
| ORA-R2 | 3, 4, 5, 7 |
| ORA-R3 | 5, 7 |
| ORA-R4 | 6, 7, 8, 9 |
| ORA-R5 | 6, 7, 11 |
| ORA-R6 | 7, 9 |
| ORA-R7 | 11 |
| ORA-R8 | 2, 9, 11, 12 |
| ORA-R9 | 18 |
| ORA-R10 | 4, 17 |
| ORA-R11 | 2, 10, 15 |

| Property | Task | Property | Task |
|---|---|---|---|
| P1, P2, P3 | 5 | P6, X2 | 6 |
| P4, X1, X9 | 7 | P7 (unit) | 5 |
| P5, X6 | 3 | P7 (eval) | 11 |
| P8 | 9, 11 | X3 | 4 |
| X4 | 8 | X5 | 7 |
| X7, X8 | 5 | X10 | 15 |
