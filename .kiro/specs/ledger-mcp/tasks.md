# ledger-mcp: Tasks

Tags: `core` (must ship), `stretch`. Each task lists the requirements (R) and properties (P) it satisfies and the tests that prove it. Tasks are ordered by dependency. Commit after each task (Conventional Commits, `feat(ledger): ...`).

Blocked by repo-level bootstrap, tracked outside this spec: **B1** `stitch_common` contract models and `ToolResult` envelope, **B2** the `surgeon` agent, **B3** contract-validation hook.

- [ ] **1. Scaffold the organ with `surgeon`** `core`
  - Generate `organs/ledger/` (pyproject, `src/stitch_ledger`, `tests/{unit,property,contract}`, README) from the surgeon template.
  - Add the `no_network` fixture (sockets disabled) as an autouse default, Hypothesis profiles `dev` and `ci`, ruff and mypy config.
  - Verify the OR-Tools wheel (GLOP and SCIP) installs in the target Docker base image.
  - Done when: `uv run pytest` passes on an empty suite and the image builds.

- [ ] **2. Domain models, validation, normalization** `core`
  - `core/problem.py`: input models (from `stitch_common`), validation (finite numbers, bounds, unique ids, size caps), `normalize()` computing `r_d`, `R_dk`, `w_d`, `λ_k`, and zero-reach warnings.
  - `tests/strategies.py`: `valid_problems()` and `invalid_problems()` including edge cases.
  - Tests: unit tests for each validation rule and each edge case. Refs: LED-R2.1, R2.2.
  - Done when: every invalid class returns `INVALID_INPUT` and no solver is constructed.

- [ ] **3. LP formulation and solve** `core`
  - `core/formulate.py`, `core/solve.py` (GLOP, one thread). Variables `x`, `f`, constraints per §2.4.
  - Tests: three hand-solved instances (single commodity, two commodities with budget, floor binding) with derivations in docstrings. Differential test against greedy-by-severity. Refs: LED-R1.1 to R1.4, R3.1. P12.
  - Done when: hand-solved and greedy checks pass.

- [ ] **4. Postprocess, safety invariants, cost-benefit** `core`
  - `core/postprocess.py`: clamp, supply and budget repair, recompute `f` from `x`, `cov_d`, totals, cost per person with null on zero.
  - Property tests: P1, P2, P4, P5. Unit test for the zero-people case. Refs: LED-R4.1 to R4.5, R5.1, R5.2.
  - Done when: all four properties pass under the `ci` profile.

- [ ] **5. Infeasibility diagnosis and `f_max`** `core`
  - `core/diagnose.py`: closed-form `f_max`, reason strings naming the binding constraint (supply, budget).
  - Property tests: P15 (tightness). Unit tests for reason text. Refs: LED-R3.2.
  - Done when: floors above `f_max` return `infeasible` with a reason, without a solve.

- [ ] **6. Integer mode, time limit, gap, determinism** `core`
  - SCIP path with `U = ceil(R)`, time limit, `optimality_gap` from `BestBound`, status mapping, fixed seed.
  - Property tests: P14, P9. Unit test: tiny time limit on a large instance returns `feasible` with a gap, or `TIMEOUT` if no incumbent. Refs: LED-R1.1, R3.3 to R3.5, R4.3.
  - Done when: integrality and determinism hold, and the time-limit behavior is covered.

- [ ] **7. Monotonicity, symmetry, scale properties** `core`
  - Property tests P3 (LP strict, MIP on proven-optimal pairs), P7, P8, P13 with `core/baseline.py`.
  - Done when: all pass under the `ci` profile. Any failing example is distilled into a named regression test.

- [ ] **8. RunStore** `core`
  - `store.py`: DuckDB table, TTL (24 h minimum, purge at 48 h), 1,000-row cap, lock, in-memory fallback.
  - Tests: round-trip, expiry with an injected clock, cap eviction, concurrent writes. Refs: LED-R8.2, R6.4.
  - Done when: a restart keeps runs within the TTL (file mode).

- [ ] **9. Sensitivity report** `core`
  - `core/sensitivity.py`: LP-relaxation duals, reduced costs, `binding`, floor duals per district, units, `basis` and notes.
  - Property test P6. Unit tests against hand-derived duals from task 3 instances. Refs: LED-R6.1 to R6.5.
  - Done when: P6 passes and duals match the hand-derived values.

- [ ] **10. Equity trade-off** `core`
  - `core/tradeoff.py`: floor grid plus `f_max`, LP re-solves, analytic infeasible tail, `equity_cost`, 10 s budget with partial result and warning.
  - Property tests: P10, P11. Unit tests for the grid and the tail. Refs: LED-R10.1 to R10.4.
  - Done when: P10 and P11 pass and the infeasible tail is returned without solves.

- [ ] **11. Demo dataset and loader** `core`
  - `scripts/build_ledger_demo.py` (WorldPop per-district sums, OSM road density to `road_access`, `default_severity` prior). Commit the Parquet, `MANIFEST.md`, and `THIRD_PARTY.md` rows (WorldPop CC BY 4.0, OSM ODbL, OR-Tools Apache-2.0).
  - `data/loader.py` with schema validation. Tests: schema, ranges, no missing ids, all values in [0,1]. Refs: LED-R2.3, R11.1.
  - Done when: the loader reads the committed files offline and the manifest lists source and license.

- [ ] **12. MCP server, envelope, resource, health** `core`
  - `server.py`: `optimize_allocation`, `sensitivity_report`, resource `ledger://scenario/{id}/districts` (once §9 is approved), error mapping, provenance, `/healthz`, stdio and HTTP transports.
  - Contract tests: real tool output validates against the `mcp-contracts.md` schemas, with `additionalProperties: false`. Smoke test: start the server, list tools, call both.
  - Refs: LED-R8.1, R3.1. Done when: the contract hook (B3) passes.

- [ ] **13. Performance and offline checks** `core`
  - Benchmark 200 × 10 (LED-R7) and the equity sweep time. Confirm the whole suite passes with sockets disabled. Refs: LED-R7.1, R11.1.
  - Done when: the benchmark is under budget with margin in CI.

- [ ] **14. Eval harness** `core`
  - `evals/ledger/`: seeded instance generator, run solver and baseline, record feasibility rate, optimality gap distribution, solve time, coverage uplift over the baseline. Write `evals/results/ledger.json` and Parquet in the dashboard schema. Refs: LED-R9.1.
  - Done when: `python -m evals.ledger --seed 0` is reproducible and the on-save eval hook picks it up.

- [ ] **15. Documentation** `core`
  - `organs/ledger/README.md`, `docs/ledger-model.md` (formulation, assumptions, what shadow prices mean, limitations). Update `docs/kiro-writeup.md` with the property-testing story (P1 to P15).
  - Done when: a reader can reproduce the §2 model from the doc.

- [ ] **16. Allowable ranges via parametric re-solve** `stretch`
  - For binding supply and budget constraints, find the interval where the dual stays constant by doubling and bisection on the RHS. Fill `ranges`. Refs: LED-R6.3.

- [ ] **17. Commodity priority weights** `stretch`
  - Add optional `priority_weight` to the contract (v0.4), replace `λ_k = 1/|K|`, extend properties.

## Traceability

| Requirement | Tasks |
|---|---|
| LED-R1 | 3, 6 |
| LED-R2 | 2, 11 |
| LED-R3 | 3, 5, 6 |
| LED-R4 | 4, 6 |
| LED-R5 | 4 |
| LED-R6 | 8, 9, 16 |
| LED-R7 | 13 |
| LED-R8 | 8, 12 |
| LED-R9 | 14 |
| LED-R10 | 10 |
| LED-R11 | 11, 13 |

| Property | Task | Property | Task |
|---|---|---|---|
| LED-P1, P2, P4, P5 | 4 | LED-P10, P11 | 10 |
| LED-P3, P7, P8, P13 | 7 | LED-P12 | 3 |
| LED-P6 | 9 | LED-P14, P9 | 6 |
| LED-P15 | 5 | | |
