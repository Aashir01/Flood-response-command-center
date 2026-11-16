# ledger-mcp

The Ledger organ of Stitch: an aid allocation optimiser. It allocates relief commodities across districts to maximise severity- and access-weighted coverage under supply, budget and an equity floor, and reports cost-benefit, the solver gap, shadow prices with allowable ranges, and the efficiency-equity trade-off. The model is documented in `docs/ledger-model.md`.

Stitch is a decision-support demo. Ledger output on the `demo-sindh-2022` dataset uses illustrative severity, air/boat shares and costs; it is not an operational plan.

## Tools and resource (contract v0.4, `.kiro/steering/mcp-contracts.md` sections 6 and 8b)

- `optimize_allocation`: LP (GLOP) or, with `integer = true` (default), MIP (SCIP). Omit `districts` to use the committed dataset for `scenario_id`; pass `districts` to override it (no merging). Optional `mode` (v0.4): the Ledger never uses the network, so with the dataset the result is `mode = demo` and a `live` request adds a `MODE_FALLBACK: ...` warning; with caller-supplied districts the result carries the requested mode. The `provenance.run_id` of the result is the key for `sensitivity_report`.
- `sensitivity_report`: shadow prices, reduced costs, allowable ranges of binding supply and budget constraints, and the equity trade-off curve for a prior `run_id`, all from the LP relaxation (`basis = "lp_relaxation"`). Runs are kept at least 24 h.
- Resource `ledger://scenario/{scenario_id}/districts`: the dataset rows (population, road access, air/boat share, default severity). An unknown scenario is an MCP resource error whose message starts with `NOT_FOUND:`.

Errors (envelope `ok: false`): `INVALID_INPUT` (validation, at most 500 districts and 20 commodities), `NOT_FOUND` (unknown scenario or expired run), `INFEASIBLE` (sensitivity of an infeasible run), `TIMEOUT` (MIP time limit with no incumbent, retryable), `INTERNAL` (solver failure; details are logged, not returned). A floor above `max_feasible_floor` is relaxed with a warning, or gives `status = "infeasible"` with `on_infeasible_floor = "error"`.

## Layout

```
src/stitch_ledger/
  core/          pure logic, no I/O: problem, formulate, solve, postprocess, floors, optimize,
                 sensitivity, ranges, tradeoff, baseline, instances (seeded generator)
  data/loader.py committed dataset (data/demo/ledger/districts.parquet), schema-checked
  store.py       RunStore (DuckDB file or memory): run inputs and outputs by run_id, TTL 24-48 h
  service.py     tool implementations: dataset or override, error mapping, provenance, mode
  server.py      MCP server (stdio and streamable HTTP) with the resource and GET /healthz
  bench.py       200 x 10 benchmark
tests/
  unit/ property/ contract/ perf/   (no network; Hypothesis profiles dev and ci)
  test_smoke_stdio.py               server over stdio: tools, resource, both calls; /healthz
```

## Run

```
uv sync --all-packages
uv run python -m stitch_ledger.server --stdio                       # Kiro, Brain
uv run python -m stitch_ledger.server --http --host 0.0.0.0 --port 8000
curl http://127.0.0.1:8000/healthz      # 200 {"status":"ok","checks":{"solver","dataset","store"}}, 503 if a check fails
```

Environment: `STITCH_MODE` (`demo` default), `STITCH_LEDGER_DB` (DuckDB file for the run store; unset keeps runs in memory, lost on restart), `STITCH_DEMO_DIR` (dataset root, default `data/demo`), `STITCH_HOST`, `STITCH_PORT`.

## Tests, benchmark, eval

```
uv run pytest organs/ledger -q --hypothesis-profile=ci     # about 180 tests, 2 min
uv run python -m stitch_ledger.bench --repeat 3            # JSON timings
uv run python -m evals.run --organ ledger --seed 0 [--fast]
```

Benchmark on the dev laptop (i5, 200 districts x 10 commodities, seed 0, floor 0.3, budget binding): LP 0.014 s, MIP 0.10 s (optimal), duals 0.016 s, ranges 0.037 s, trade-off sweep 0.12 s (4 solves), sweep without budget 0.14 s (11 solves). Budget (LED-R7): 10 s on 2 vCPU; `tests/perf` asserts under 5 s.

Eval (seed 0, 200 seeded synthetic instances of 5 to 200 districts and 1 to 10 commodities, 50 of them integer): feasibility rate 1.0 by an independent constraint check, MIP gap p90 0 and max 0, LP solve time p95 0.024 s, MIP p95 0.21 s, coverage uplift over the proportional baseline mean 0.44 and min 0. Demo equity curve: coverage at floor 1 is 0.47 of the coverage at floor 0. Solve times vary by host; every other value is a function of the seed. Results go to `evals/results/ledger.json` (dashboard schema), `ledger_instances.parquet` and `ledger_equity_curve.json` (all git-ignored).

The eval found two MIP bugs that the property tests had missed (they use at most 12 districts): SCIP returning an all-zero plan as optimal, and the integer budget repair breaking the floor by one unit. Both are fixed and have regression tests.
