# ledger-mcp: Design

Implements `requirements.md` (LED-R1..R11). Contract: `mcp-contracts.md` §6 (v0.2) plus one proposed addition in §9 below.

## 1. Overview

The Ledger turns district-level facts (reachable population, severity, supply, cost) into an allocation by solving a linear program (LP), or a mixed-integer program (MIP) when `integer = true`. It then derives cost-benefit, shadow prices, and an equity trade-off curve.

Principle: all economics live in `core/` as pure functions on plain dataclasses. The MCP layer only validates, calls core, and wraps the result in the `ToolResult` envelope. Core is therefore fast to property-test and has no I/O.

```
organs/ledger/src/stitch_ledger/
  core/
    problem.py      Problem dataclass, normalize(): reachable pop, needs, weights
    formulate.py    build the OR-Tools model from a Problem
    solve.py        run GLOP (LP) or SCIP (MIP); return raw Solution
    postprocess.py  clamp, repair supply float error, coverage, cost-benefit
    diagnose.py     analytic infeasibility reasons, f_max
    sensitivity.py  LP-relaxation duals, reduced costs, binding flags
    tradeoff.py     equity sweep and equity_cost
    baseline.py     proportional water-filling baseline (evals and a property)
  data/loader.py    committed district dataset (Parquet) -> district facts
  store.py          RunStore (DuckDB): input + output by run_id, TTL
  server.py         MCP tools and resource, envelope, error mapping
  http.py           /healthz
  settings.py       env config
tests/{unit,property,contract}/   strategies.py holds shared Hypothesis strategies
```

## 2. Mathematical model

### 2.1 Sets and parameters
- Districts `d ∈ D`, commodities `k ∈ K`. Both sorted by id for deterministic model construction.
- Per district: `pop_d` (affected population), `s_d ∈ [0,1]` severity, `a_d ∈ [0,1]` road access, `m_d > 0` cost multiplier (default 1).
- Per commodity: `c_k ≥ 0` unit cost, `n_k > 0` need per person (units/person), `S_k ≥ 0` supply.
- Optional budget `B`, optional equity floor `φ ∈ [0,1]`.

### 2.2 Derived quantities (`normalize`)
- **Reachable population** `r_d = pop_d · a_d`. Road access scales the population the aid can physically reach by road. People beyond road access are reported in `warnings` as unreached (no airdrop modeling).
- **Need** `R_dk = r_d · n_k` (units of k that fully cover district d).
- **Weight** `w_d = r_d · s_d` (severity-weighted reachable people).
- **Commodity weight** `λ_k = 1/|K|`.
- Districts with `r_d = 0` get no variables and zero coverage (a warning is added).

### 2.3 Decision variables
- `x_dk ≥ 0`: units of k sent to d. Integer when `integer = true`.
- `f_dk ∈ [0,1]`: coverage of d's need for k.

### 2.4 Model
```
maximize   Σ_d Σ_k  w_d · λ_k · f_dk                         (total_coverage)

s.t.   R_dk · f_dk ≤ x_dk                  ∀ d,k            (coverage needs delivered units)
       x_dk ≤ U_dk                         ∀ d,k            (no over-delivery; U = R_dk for LP, ceil(R_dk) for MIP)
       Σ_d x_dk ≤ S_k                      ∀ k              (supply:<k>)
       Σ_d Σ_k c_k · m_d · x_dk ≤ B                         (budget, if given)
       f_dk ≥ φ                            ∀ d,k            (min_coverage:<d>, if φ > 0)
```
Reported district coverage `cov_d = Σ_k λ_k f_dk ∈ [0,1]`.

### 2.5 Consequences worth stating
- Marginal value of one unit of k at d is `w_d λ_k / R_dk = s_d λ_k / n_k`. Population cancels, so with one commodity and no budget or floor the LP is greedy by severity. This gives an independent oracle for a differential test (LED-P12).
- Road access only matters through `r_d`, so low-access districts both need less and weigh less. Users who want access to act as a cost can set `unit_cost_multiplier`.
- The floor applies to every commodity in every district. Without a budget, the largest feasible uniform floor has a closed form:
  `f_max = min(1, min_k S_k / Σ_d R_dk, B / Σ_d Σ_k c_k m_d R_dk)`.
  This avoids bisection and gives exact infeasibility diagnoses.
- Integer mode: `U_dk = ceil(R_dk)` lets the last unit exceed need by under one unit. This is the only allowed over-delivery (LED-R1.3 refined). Coverage is still capped at 1 by `f ≤ 1`.

## 3. Solver choice

OR-Tools `pywraplp`: **GLOP** for LP, **SCIP** for MIP.

| Option | Duals / reduced costs | MIP gap | Determinism | Verdict |
|---|---|---|---|---|
| OR-Tools GLOP + SCIP | yes (`dual_value`, `reduced_cost`) | yes (`BestBound`) | single thread, fixed seed | chosen |
| PuLP + CBC | duals via `pi`; reduced costs awkward | limited | OK | no |
| SciPy HiGHS | duals via marginals | via `milp` | OK | not named in the brief |

Settings: `SetNumThreads(1)`, SCIP `randomization/randomseedshift = 0`, time limit from `solver_time_limit_s` (cap 30 s). Allowable RHS ranges are not exposed by pywraplp, so they are a stretch task (parametric re-solve), see §6.

## 4. Algorithms and data flow

`optimize_allocation(in)`:
1. Pydantic validation (finite numbers, bounds, size caps: ≤ 500 districts, ≤ 20 commodities, unique ids). Failure returns `INVALID_INPUT` and the solver is never built.
2. `normalize` into a `Problem`. Compute `f_max`. If `φ > f_max`, return `infeasible` with a reason from `diagnose` (e.g. "floor 0.60 needs 1,200 food packs, supply is 800").
3. `formulate` and `solve` (LP, or MIP if `integer`). Map solver status: OPTIMAL to `optimal`; FEASIBLE with incumbent to `feasible` plus `optimality_gap`; INFEASIBLE to `infeasible`; anything else to `INTERNAL` error.
4. `postprocess`: clamp tiny negatives to 0 (`|x| < 1e-9`), round integers, **repair** supply and budget overshoot from float error by scaling the offending commodity down by its exact ratio, recompute `f` from final `x` (`f = min(1, x/R)`), compute `cov_d`, `total_coverage`, `total_cost`, `people_covered = Σ r_d cov_d`, and `cost_per_person_covered` (null when `people_covered = 0`).
5. Store `(run_id, canonical input, output)` in `RunStore`. Return the envelope.

Deterministic tie-breaking: ordered construction, one thread, fixed seed. Property LED-P9 compares `data` excluding `solver.wall_time_s`.

`sensitivity_report(run_id, floor_steps)`:
1. Load the stored input, else `NOT_FOUND`.
2. Re-solve the **LP relaxation** (same input, `integer = false`). Read `dual_value` per constraint and `reduced_cost` per `x`. `binding = |slack| ≤ 1e-9·max(1,|rhs|)`. Non-binding duals are set to exactly 0. Supply and budget duals are ≥ 0, floor duals are ≤ 0 (raising the floor costs coverage). Floor duals are summed over commodities per district to give `min_coverage:<d>`.
3. `tradeoff`: floors = `linspace(0, 1, floor_steps)` plus `f_max`, sorted and de-duplicated. For `f ≤ f_max`, solve the LP with floor `f`. For `f > f_max`, emit `infeasible` with null values (no solve). Trade-off is always on the LP relaxation, so `basis = "lp_relaxation"` when the run used integers. Budget of 10 s total, else return completed points plus a warning.
4. `equity_cost = cov(f=0) − cov(f=φ_run)` when the run had `φ > 0`, else null.
5. Ranges: empty list unless the stretch task lands. A note says so.

Units of shadow prices: coverage-weighted people per unit of commodity (supply), per currency unit (budget), per unit of floor (floor).

## 5. Persistence and data

**RunStore** (DuckDB file in a volume, in-memory fallback): table `runs(run_id, created_at, input_json, output_json)`. Entries live at least 24 h, purged after 48 h, capped at 1,000 rows (oldest first). A lock serializes writes.

**Demo dataset** (`data/demo/ledger/`, committed Parquet, tens of KB):
- `districts.parquet`: `district_id, name, province, population, road_access, default_severity`. Sindh districts for `demo-sindh-2022`.
- `population` is WorldPop 100 m raster summed per district (CC BY 4.0). `road_access` is a documented proxy: OSM road km per km² (primary to tertiary), divided by the 90th percentile and clipped to [0,1] (ODbL). `default_severity` is a scenario prior from the 2022 flood record, labeled as a prior.
- Built by `scripts/build_ledger_demo.py` (needs network, dev-time only, not run by the app). Source, license, and build date go in `data/demo/MANIFEST.md` and `THIRD_PARTY.md`.

Runtime never touches the network (LED-R11). Tests run with sockets disabled.

## 6. Interfaces

Tool I/O follows `mcp-contracts.md` §6 unchanged, with one addition (§9).

Error mapping:

| Condition | Code | retryable |
|---|---|---|
| validation failure, size caps | `INVALID_INPUT` | false |
| unknown or expired `run_id` | `NOT_FOUND` | false |
| floor, budget, or supply make problem infeasible | ok result with `status = infeasible` (not an error) | n/a |
| solver crash or unexpected status | `INTERNAL` | false |
| time limit with no incumbent | `TIMEOUT` | true |

Infeasible is a valid answer, not a tool failure, so the Brain can show it.

Provenance: `organ=ledger`, `tool_version`, solver name and version, `data_sources` for WorldPop and OSM when the dataset was used, `mode = demo`.

Server: MCP Python SDK (`FastMCP`), stdio and streamable HTTP, plus `GET /healthz` (solver import check, dataset loaded, store writable).

## 7. Correctness properties and how they are tested

Hypothesis strategy `valid_problems()` generates 1 to 12 districts, 1 to 4 commodities, supplies from 0 to 3× total need, optional budget, optional floor, and deliberately includes edge cases: zero population, access 0, severity 0, zero supply, floors above `f_max`. Tolerance `ε = 1e-7` relative. Profile `ci`: 200 examples with the deadline off.

| ID | Property | Test approach |
|---|---|---|
| LED-P1 | Σ_d x_dk ≤ S_k | any valid problem, LP and MIP |
| LED-P2 | x_dk ≥ 0 | same |
| LED-P3 | more supply never lowers `total_coverage` | draw problem, raise one `S_k` by δ ≥ 0; LP mode strict within ε; MIP mode only when both solves are `optimal` (gap 0) |
| LED-P4 | `cov_d ≤ 1` and every `f_dk ≤ 1` | any valid problem |
| LED-P5 | `total_cost ≤ B` | problems with a budget |
| LED-P6 | non-binding duals = 0; supply duals ≥ 0; floor duals ≤ 0 | sensitivity on LP problems |
| LED-P7 | permuting districts keeps `total_coverage` | shuffle input order |
| LED-P8 | scaling every `pop_d`, every `S_k`, and `B` by k > 0 leaves coverage fractions unchanged and scales `total_coverage` by k | scale inputs, compare outputs |
| LED-P9 | output is a deterministic function of input | solve twice, compare `data` minus wall time |
| LED-P10 | `total_coverage` is non-increasing in the floor | check the returned trade-off array |
| LED-P11 | trade-off at floor 0 equals the unconstrained solve | compare with the same problem at `φ = 0` |
| LED-P12 | single commodity, no budget, no floor: LP optimum equals greedy-by-severity value | independent reference implementation |
| LED-P13 | optimum ≥ the proportional baseline's coverage | `baseline.py` as the reference |
| LED-P14 | `integer = true` outputs are integral and ≤ `ceil(R_dk)` | MIP problems |
| LED-P15 | `f_max` is tight: floor = `f_max` is feasible, floor = `f_max + 1e-6` is not | LP problems with and without budget |

Property tests run on `core/` directly (no MCP). Contract tests validate real tool output against the JSON Schemas derived from `mcp-contracts.md`. Unit tests cover three hand-solved instances, each with a written derivation in the test docstring.

## 8. Performance

200 districts × 10 commodities gives about 4,000 LP variables, solved by GLOP in well under a second. MIP uses SCIP with the time limit. The equity sweep re-solves up to 12 LPs, each warm-cheap. Budget: `optimize_allocation` under 10 s on 2 vCPU (LED-R7), checked by a benchmark test with a generous CI margin.

## 9. Proposed contract addition (needs your approval, bumps to v0.3)

Brain needs static district attributes (population, road access, default severity) to merge with Eyes severity and call `optimize_allocation`. Add an MCP **resource**, not a tool:

```
ledger://scenario/{scenario_id}/districts
-> [ { "district_id": str, "name": str, "population": int, "road_access": number [0,1],
       "default_severity": number [0,1] } ]
```
`optimize_allocation` keeps `districts` required, so explicit caller data always wins (LED-R2.4). If you prefer to avoid a resource, the alternative is making `districts` optional so the tool fills from the dataset.

## 10. Design decisions to confirm

1. **Road access scales reachable population** (`r_d = pop·a`), not cost. Requirements said "scale deliverable quantity or cost"; this picks the first, and unreached people are warned about, not hidden.
2. **Equity floor applies to every commodity in every district** (strong form). It keeps `f_max` closed-form.
3. **Equal commodity weights** (`λ_k = 1/|K|`). Priority weights would need a contract field, so they are a stretch task.
4. **Shadow prices from the LP relaxation**, with integers noted in `basis`.
5. **Allowable ranges** are a stretch (parametric re-solve), returned empty with a note until then.

## 11. Risks

| Risk | Mitigation |
|---|---|
| SCIP wheel size or platform issues in the image | check the OR-Tools wheel in the Docker build early (task 1); fall back to CBC through `pywraplp` if needed |
| Float error breaks P1/P5 | postprocess repair step plus explicit tolerance in tests |
| MIP monotonicity (P3) is false at nonzero gap | restrict the strict check to proven-optimal pairs |
| WorldPop/OSM build is heavy for the laptop | process per-district windows, Sindh only, and commit the small Parquet result |
