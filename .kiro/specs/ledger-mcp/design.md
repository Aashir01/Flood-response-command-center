# ledger-mcp: Design

Implements `requirements.md` (LED-R1..R11). Contract: `mcp-contracts.md` §6, §8b (v0.3).

## 1. Overview

The Ledger turns district-level facts (reachable population, severity, supply, cost) into an allocation by solving a linear program (LP), or a mixed-integer program (MIP) when `integer = true`. It derives cost-benefit, shadow prices, and an equity trade-off curve. It never sends supplies where trucks cannot go without saying so.

All economics live in `core/` as pure functions on plain dataclasses. The MCP layer validates, calls core, and wraps results in the `ToolResult` envelope. Core is fast to property-test and has no I/O.

```
organs/ledger/src/stitch_ledger/
  core/
    problem.py      Problem dataclass, normalize(): access modes, reachable pop, needs, weights, shares
    formulate.py    build the OR-Tools model from a Problem
    solve.py        run GLOP (LP) or SCIP (MIP); return raw Solution
    postprocess.py  clamp, repair float error, coverage, cost-benefit, access flags
    floors.py       max_feasible_floor (closed form for LP, bisection for MIP), relax/error policy
    sensitivity.py  LP-relaxation duals, reduced costs, binding flags
    tradeoff.py     equity sweep and equity_cost
    baseline.py     proportional-share allocation (evals and properties)
  data/loader.py    committed district dataset (Parquet)
  store.py          RunStore (DuckDB): input + output by run_id, TTL
  server.py         MCP tools and resource, envelope, error mapping
  http.py           /healthz
  settings.py       env config
tests/{unit,property,contract}/   strategies.py holds shared Hypothesis strategies
```

## 2. Mathematical model

### 2.1 Sets and parameters
- Districts `d ∈ D`, commodities `k ∈ K`, both sorted by id for deterministic construction.
- Per district: `pop_d`, severity `s_d ∈ [0,1]`, road access `a_d ∈ [0,1]`, air/boat fraction `alt_d ∈ [0,1]` (default 0), cost multiplier `m_d > 0` (default 1).
- Per commodity: unit cost `c_k ≥ 0`, need per person `n_k > 0`, supply `S_k ≥ 0`.
- Optional budget `B`, equity floor `φ ∈ [0,1]` (default 0), usable-access threshold `τ` (default 0.1).

### 2.2 Access modes and derived quantities (`normalize`)
1. **Usable road access** `ā_d = a_d` if `a_d ≥ τ`, else 0.
2. **Reachable fraction** `ρ^reach_d = min(1, ā_d + alt_d)`. Reachable population `r_d = pop_d · ρ^reach_d`.
3. **Access mode**: `road` if `a_d ≥ τ`; `air_boat` if `a_d < τ` and `alt_d > 0`; `unreachable` if `a_d < τ`, `alt_d = 0`, and `pop_d > 0`.
4. **Unreached people** `u_d = pop_d − r_d`, reported per district and summarized in `warnings`.
5. **Need** `R_dk = r_d · n_k`. **Weight** `w_d = r_d · s_d`. **Commodity weight** `λ_k = 1/|K|`.
6. Districts with `r_d = 0` get no variables, zero coverage, and (if `pop_d > 0`) an `unreachable` flag. This is how the solver is prevented from sending supplies where nothing can be delivered.
7. **Supply ratio** `ρ_k = min(1, S_k / Σ_d R_dk)` (1 when total need is 0). **Proportional share** `share_dk = ρ_k · R_dk`.

### 2.3 Decision variables
`x_dk ≥ 0` units of k sent to d (integer when `integer = true`). `f_dk ∈ [0,1]` coverage of d's need for k.

### 2.4 Model
```
maximize   Σ_d Σ_k  w_d · λ_k · f_dk                         (total_coverage)

s.t.   R_dk · f_dk ≤ x_dk                  ∀ d,k            (coverage needs delivered units)
       x_dk ≤ U_dk                         ∀ d,k            (U = R_dk for LP, ceil(R_dk) for MIP)
       Σ_d x_dk ≤ S_k                      ∀ k              (supply:<k>)
       Σ_d Σ_k c_k · m_d · x_dk ≤ B                         (budget, if given)
       f_dk ≥ φ · ρ_k                      ∀ d,k            (equity floor; dual named min_coverage:<d>)
```
Because `f_dk ≥ φ ρ_k` means `x_dk ≥ φ · share_dk`. District coverage `cov_d = Σ_k λ_k f_dk`. The air/boat cap is built into `R_dk` through `r_d`, so a road-denied district can never receive more than its air/boat need.

### 2.5 Consequences worth stating
- Marginal value of a unit of k at d is `w_d λ_k / R_dk = s_d λ_k / n_k`. Population cancels. With one commodity and no budget or floor, the LP is greedy by severity. That gives an independent oracle (LED-P12).
- **`φ = 0` is pure efficiency. `φ = 1` is the proportional allocation.** Between them the floor traces the efficiency-equity trade-off. This is the economics story for the UI.
- Total floor demand for commodity k is `φ · Σ_d share_dk = φ · min(S_k, Σ_d R_dk) ≤ S_k`, so **supply never makes a floor infeasible**. Only the budget can. In LP mode:
  `max_feasible_floor = min(1, B / Σ_d Σ_k c_k m_d share_dk)` (1 when no budget, or when the denominator is 0).
- Integer mode: the floor becomes `x_dk ≥ ceil(φ · share_dk − 1e-9)`. Feasibility needs `Σ_d ceil(...) ≤ floor(S_k)` and the ceiling cost within `B`. That check is monotone in `φ`, so `max_feasible_floor` is found by bisection (40 steps, arithmetic only, no solver).
- Integer mode allows over-delivery of under one unit via `U = ceil(R)`. Coverage stays ≤ 1 through `f ≤ 1`.

## 3. Solver choice

OR-Tools `pywraplp`: **GLOP** for LP, **SCIP** for MIP.

| Option | Duals / reduced costs | MIP gap | Determinism | Verdict |
|---|---|---|---|---|
| OR-Tools GLOP + SCIP | yes (`dual_value`, `reduced_cost`) | yes (`BestBound`) | single thread, fixed seed | chosen |
| PuLP + CBC | duals via `pi`; reduced costs awkward | limited | OK | no |
| SciPy HiGHS | duals via marginals | via `milp` | OK | not named in the brief |

Settings: `SetNumThreads(1)`, fixed SCIP seed, time limit from `solver_time_limit_s` (cap 30 s). RHS ranges are not exposed by pywraplp, so they are a stretch task (parametric re-solve).

## 4. Algorithms and data flow

`optimize_allocation(in)`:
1. Resolve districts: use `in.districts` if given (no merging), else load the scenario from the dataset with default severity. Validate with Pydantic (finite numbers, bounds, unique ids, size caps: ≤ 500 districts, ≤ 20 commodities). Failure returns `INVALID_INPUT` and no model is built.
2. `normalize` into a `Problem`. Collect `unreachable` and `air_boat` districts into `warnings`.
3. `floors.max_feasible_floor(problem)`. Apply the policy:
   - `φ ≤ max_feasible_floor`: continue with `φ`.
   - `φ > max_feasible_floor` and `relax`: continue with `φ_applied = max_feasible_floor`, add a warning.
   - `φ > max_feasible_floor` and `error`: return `status = infeasible` with a reason naming the budget and the `max_feasible_floor`.
4. `formulate` and `solve`. Map status: OPTIMAL to `optimal`; FEASIBLE with incumbent to `feasible` plus `optimality_gap`; no incumbent at the time limit to `TIMEOUT`; unexpected to `INTERNAL`.
5. `postprocess`: clamp `|x| < 1e-9` to 0; round integers; **repair** float overshoot of supply and budget by scaling the offending commodity or all quantities by the exact ratio; recompute `f = min(1, x/R)`; compute `cov_d`, `total_coverage`, `total_cost`, `people_covered = Σ_d r_d · cov_d`, and cost per person (null when `people_covered = 0`); attach `access_mode` and `unreached_people` per district and the `equity` block.
6. Store `(run_id, canonical input, output)` in `RunStore`. Return the envelope.

Determinism: ordered construction, one thread, fixed seed. LED-P9 compares `data` minus `solver.wall_time_s`.

`sensitivity_report(run_id, floor_steps)`:
1. Load the stored input, else `NOT_FOUND`.
2. Re-solve the LP relaxation at the **applied** floor. Read duals and reduced costs. `binding = |slack| ≤ 1e-9·max(1,|rhs|)`. Non-binding duals are exactly 0. Supply and budget duals ≥ 0. Floor duals ≤ 0. Report `min_coverage:<d>` (sum over k of that district's floor duals) and one aggregate `equity_floor` entry (the dual with respect to `φ`, i.e. the coverage lost per unit of floor).
3. Trade-off: floors = `linspace(0, 1, floor_steps)` plus `max_feasible_floor`, sorted and de-duplicated. Floors at or below it are LP solves; floors above are `infeasible` with null values (no solve). Always the LP relaxation, so `basis = "lp_relaxation"` for integer runs. 10 s total budget, else completed points plus a warning.
4. `equity_cost = cov(φ=0) − cov(φ_applied)` when `φ_applied > 0`, else null.
5. Ranges: empty unless the stretch task lands, with a note.

Shadow-price units: coverage-weighted people per unit of commodity (supply), per currency unit (budget), per unit of floor (floor).

## 5. Persistence and data

**RunStore** (DuckDB file in a volume, in-memory fallback): table `runs(run_id, created_at, input_json, output_json)`. Kept at least 24 h, purged after 48 h, capped at 1,000 rows (oldest first), writes serialized by a lock.

**Demo dataset** (`data/demo/ledger/`, committed Parquet, tens of KB):
- `districts.parquet`: `district_id, name, province, population, road_access, alt_delivery_fraction, default_severity` for `demo-sindh-2022`.
- `population`: WorldPop 100 m raster summed per district (CC BY 4.0). `road_access`: documented proxy of OSM road km per km² (primary to tertiary) divided by the 90th percentile, clipped to [0,1] (ODbL). `alt_delivery_fraction`: 0 everywhere by default, with a small demo value for a few districts to exercise the air/boat path, labeled as an illustrative assumption. `default_severity`: scenario prior from the 2022 flood record, labeled as a prior.
- Built by `scripts/build_ledger_demo.py` (needs network, dev-time only). Source, license, and build date go in `data/demo/MANIFEST.md` and `THIRD_PARTY.md`.

Runtime never touches the network (LED-R11). Tests run with sockets disabled.

## 6. Interfaces

Tool I/O follows `mcp-contracts.md` §6 (v0.3). Resource: `ledger://scenario/{scenario_id}/districts` (§8b). An unknown `scenario_id` returns `NOT_FOUND`.

| Condition | Result | retryable |
|---|---|---|
| validation failure, size caps | `INVALID_INPUT` | false |
| unknown or expired `run_id`, unknown scenario | `NOT_FOUND` | false |
| floor above `max_feasible_floor`, policy `relax` | ok result, `floor_applied < floor_requested`, warning | n/a |
| floor above `max_feasible_floor`, policy `error` | ok result with `status = infeasible` | n/a |
| time limit with no incumbent | `TIMEOUT` | true |
| solver crash or unexpected status | `INTERNAL` | false |

Provenance: `organ=ledger`, tool version, solver name and version, `data_sources` for WorldPop and OSM when the dataset was used, `mode = demo`.

Server: MCP Python SDK (`FastMCP`), stdio and streamable HTTP, plus `GET /healthz` (solver import check, dataset loaded, store writable).

## 7. Correctness properties and how they are tested

Hypothesis strategy `valid_problems()` generates 1 to 12 districts, 1 to 4 commodities, supplies from 0 to 3× total need, optional budget, optional floor, optional `alt_delivery_fraction`, and edge cases: zero population, access 0 or just below `τ`, severity 0, zero supply, floors above `max_feasible_floor`, tiny budgets. Tolerance `ε = 1e-7` relative. Profile `ci`: 200 examples, deadline off.

| ID | Property | Test approach |
|---|---|---|
| LED-P1 | Σ_d x_dk ≤ S_k | any valid problem, LP and MIP |
| LED-P2 | x_dk ≥ 0 | same |
| LED-P3 | more supply never lowers `total_coverage` | raise one `S_k` by δ ≥ 0; LP strict within ε; MIP only on proven-optimal pairs. Floors are held fixed, and because `share` depends on `S` the test compares at `φ = 0`, and separately checks that with `φ > 0` coverage is still never below the proportional baseline |
| LED-P4 | `cov_d ≤ 1`, every `f_dk ≤ 1` | any valid problem |
| LED-P5 | `total_cost ≤ B` | problems with a budget |
| LED-P6 | non-binding duals = 0; supply duals ≥ 0; floor duals ≤ 0 | sensitivity on LP problems |
| LED-P7 | permuting districts keeps `total_coverage` | shuffle input order |
| LED-P8 | scaling every `pop_d`, `S_k`, `B` by k > 0 leaves coverage fractions unchanged and scales `total_coverage` by k | scale inputs, compare |
| LED-P9 | output is a deterministic function of input | solve twice, compare `data` minus wall time |
| LED-P10 | `total_coverage` non-increasing in the floor | trade-off array |
| LED-P11 | trade-off at floor 0 equals the unconstrained solve | same problem at `φ = 0` |
| LED-P12 | single commodity, no budget, no floor: LP optimum equals greedy-by-severity | independent reference |
| LED-P13 | optimum ≥ proportional baseline coverage | `baseline.py` |
| LED-P14 | `integer = true` gives integral `x ≤ ceil(R)` | MIP problems |
| LED-P15 | `max_feasible_floor` tight | feasible at the value; infeasible at value + 1e-6 when below 1 |
| LED-P16 | `φ = 1`, no budget: allocation equals `share_dk` | LP problems |
| LED-P17 | unreachable districts get zero of every commodity and are listed | problems with `a_d < τ`, `alt_d = 0` |
| LED-P18 | road-denied district allocation ≤ air/boat need | problems with `a_d < τ`, `alt_d > 0` |
| LED-P19 | `relax`: `floor_applied = min(requested, max_feasible_floor)` | budget-limited problems |

Property tests run on `core/` directly. Contract tests validate real tool output against the JSON Schemas generated from `stitch_common`. Unit tests cover hand-solved instances with derivations in docstrings.

## 8. Performance

200 districts × 10 commodities is about 4,000 LP variables, which GLOP solves in well under a second. MIP uses SCIP with the time limit. The equity sweep is up to 12 LPs. Target: `optimize_allocation` under 10 s on 2 vCPU (LED-R7), checked by a benchmark with a CI margin.

## 9. Decisions (resolved with the product owner)

1. Road access scales reachable population. Road-denied districts rely on air/boat capacity or are flagged unreachable, never silently supplied.
2. The equity floor is a fraction of each district's proportional share. If infeasible, the highest feasible floor is returned by default.
3. Equal commodity weights. Priority weights are a stretch task.
4. Resource `ledger://scenario/{id}/districts` approved (contract v0.3). `districts` stays as an optional override.
5. Shadow prices come from the LP relaxation, noted in `basis`. Allowable ranges are a stretch.

## 10. Risks

| Risk | Mitigation |
|---|---|
| SCIP wheel size or platform issues in the image | check the OR-Tools wheel in the Docker build early; fall back to CBC through `pywraplp` if needed |
| Float error breaks P1/P5 | postprocess repair step and explicit test tolerance |
| MIP monotonicity (P3) false at nonzero gap | strict check only on proven-optimal pairs |
| `share` depends on `S`, which complicates monotonicity with a floor | P3 is stated at `φ = 0`; floor-case behavior is covered by P13 and P16 |
| WorldPop/OSM build is heavy on the laptop | process per-district windows, Sindh only, commit the small Parquet result |
