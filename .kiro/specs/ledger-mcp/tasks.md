# ledger-mcp: Tasks

Tags: `core` (must ship), `stretch`. Each task lists the requirements and properties it satisfies and the tests that prove it. Ordered by dependency. Commit after each task (`feat(ledger): ...`).

Blocked by the **bootstrap** spec: `stitch_common` models and envelope, the `surgeon` agent, hooks, and shared test helpers.

- [x] **1. Scaffold the organ with `surgeon`** `core`
  - Generate `organs/ledger/` from the surgeon template (pyproject, `src/stitch_ledger`, `tests/{unit,property,contract}`, README).
  - Confirm the `no_network` fixture is on by default, Hypothesis profiles `dev` and `ci` are available, ruff and mypy config applies.
  - Verify the OR-Tools wheel (GLOP and SCIP) imports in the target Docker base image.
  - Done when: `uv run pytest` passes on the skeleton.

- [x] **2. Problem model, validation, access modes** `core`
  - `core/problem.py`: input models (from `stitch_common`), validation, `normalize()` with usable access, reachable population, access modes, unreached people, needs, weights, `ρ_k`, shares, zero-reach warnings.
  - `tests/strategies.py`: `valid_problems()` and `invalid_problems()` with edge cases.
  - Tests: unit tests per validation rule; access-mode table tests at the threshold boundary. Refs: LED-R1.4 to R1.6, R2.1, R2.2.
  - Done when: every invalid class returns `INVALID_INPUT` with no model built, and access modes match the table.

- [x] **3. LP formulation and solve** `core`
  - `core/formulate.py`, `core/solve.py` (GLOP, one thread), model per §2.4 including the equity floor `f ≥ φρ`.
  - Tests: three hand-solved instances (single commodity; two commodities with budget; floor binding), derivations in docstrings. Differential test against greedy-by-severity. Refs: LED-R1.1 to R1.3, R3.1. P12, P16.
  - Done when: hand-solved, greedy, and `φ = 1` proportional checks pass.

- [x] **4. Postprocess, safety invariants, cost-benefit** `core`
  - `core/postprocess.py`: clamp, repair, recompute `f`, `cov_d`, totals, cost per person with null on zero, `access_mode` and `unreached_people`.
  - Property tests: P1, P2, P4, P5, P17, P18. Unit test: zero people covered. Refs: LED-R4, R5.
  - Done when: all pass under `ci`.

- [x] **5. Floors: `max_feasible_floor` and relax/error policy** `core`
  - `core/floors.py`: closed form (LP), bisection (MIP), policy, reason text, `equity` block.
  - Property tests: P15, P19. Unit tests for both policies and reason text. Refs: LED-R3.2 to R3.4.
  - Done when: a floor above `max_feasible_floor` returns the relaxed allocation by default and `infeasible` under `error`.

- [x] **6. Integer mode, time limit, gap, determinism** `core`
  - SCIP path with `U = ceil(R)` and integer floors, time limit, gap from `BestBound`, status mapping, fixed seed.
  - Property tests: P14, P9. Unit test: tiny time limit returns `feasible` with a gap, or `TIMEOUT` with no incumbent. Refs: LED-R1.1, R3.5 to R3.7, R4.3.
  - Done when: integrality and determinism hold and time-limit behavior is covered.

- [x] **7. Monotonicity, symmetry, scale, baseline properties** `core`
  - `core/baseline.py` (proportional share). Property tests P3 (as stated in the design), P7, P8, P13.
  - Done when: all pass under `ci`. Any failing example becomes a named regression test.

- [x] **8. RunStore** `core`
  - `store.py`: DuckDB table, TTL (24 h minimum, purge at 48 h), 1,000-row cap, lock, in-memory fallback.
  - Tests: round-trip, expiry with an injected clock, cap eviction, concurrent writes. Refs: LED-R8.2, R6.4.
  - Done when: a restart keeps runs within the TTL (file mode).

- [x] **9. Sensitivity report** `core`
  - `core/sensitivity.py`: LP-relaxation duals, reduced costs, `binding`, per-district and aggregate floor duals, units, `basis`, notes.
  - Property test P6. Unit tests against hand-derived duals from task 3. Refs: LED-R6.
  - Done when: P6 passes and duals match hand-derived values.

- [x] **10. Equity trade-off** `core`
  - `core/tradeoff.py`: grid plus `max_feasible_floor`, LP re-solves, analytic infeasible tail, `equity_cost`, 10 s budget with partial result and warning.
  - Property tests P10, P11. Unit tests for the grid and the tail. Refs: LED-R10.
  - Done when: P10 and P11 pass and the infeasible tail is returned without solves.

- [x] **11. Demo dataset and loader** `core`
  - `scripts/build_ledger_demo.py` (WorldPop per-district sums, OSM road density to `road_access`, `alt_delivery_fraction` demo values, `default_severity` prior). Commit the Parquet, `MANIFEST.md`, and `THIRD_PARTY.md` rows (WorldPop, OSM, OR-Tools).
  - `data/loader.py` with schema validation. Tests: schema, ranges in [0,1], unique ids. Refs: LED-R2.3, R11.1.
  - Done when: the loader reads committed files offline and the manifest lists source and license.
  - Note: if the real build is blocked by data size or time, ship a smaller committed dataset with fewer districts, clearly labeled, and keep the build script.

- [x] **12. MCP server, envelope, resource, health** `core`
  - `server.py`: `optimize_allocation` (optional `districts`), `sensitivity_report`, resource `ledger://scenario/{id}/districts`, error mapping, provenance, `/healthz`, stdio and HTTP.
  - Contract tests: real output validates against schemas with `additionalProperties: false`. Smoke test: start, list tools and resources, call both tools.
  - Refs: LED-R2.4, R2.5, R8.1. Done when: the contract hook passes.

- [x] **13. Performance and offline checks** `core`
  - Benchmark 200 × 10 and the equity sweep. Run the whole suite with sockets disabled. Refs: LED-R7, R11.
  - Done when: under budget with margin.

- [x] **14. Eval harness** `core`
  - `evals/ledger/`: seeded instance generator, solver vs proportional baseline, feasibility rate, gap distribution, solve time, coverage uplift, and the equity curve for the demo scenario. Write results in the dashboard schema. Refs: LED-R9.
  - Done when: `python -m evals.run --organ ledger --seed 0` is reproducible.

- [x] **15. Documentation** `core`
  - `organs/ledger/README.md`, `docs/ledger-model.md` (formulation, assumptions, shadow price meaning, efficiency-equity trade-off, limitations). Add the property-testing story to `docs/kiro-writeup.md`.
  - Done when: a reader can reproduce §2 from the doc.

- [x] **16. Allowable ranges by parametric re-solve** `stretch`
  - For binding supply and budget constraints, find the RHS interval where the dual is constant. Refs: LED-R6.3.

- [ ] **17. Commodity priority weights** `stretch`
  - Optional `priority_weight` in the contract, replacing `λ_k = 1/|K|`. Extend properties.

## Traceability

| Requirement | Tasks |
|---|---|
| LED-R1 | 2, 3, 6 |
| LED-R2 | 2, 11, 12 |
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
| P1, P2, P4, P5, P17, P18 | 4 | P10, P11 | 10 |
| P3, P7, P8, P13 | 7 | P12, P16 | 3 |
| P6 | 9 | P14, P9 | 6 |
| P15, P19 | 5 | | |

## Status (final audit)

All core tasks are done. Open:
- 17 (commodity priority weights, `stretch`): not done. It needs a contract change (`priority_weight`); the solver keeps equal weights `λ_k = 1/|K|`.
