# Ledger model

How `ledger-mcp` turns district facts into an aid allocation, and what its numbers mean. The spec is `.kiro/specs/ledger-mcp/` (requirements LED-R1 to R11, design sections 2 to 4). The code is `organs/ledger/src/stitch_ledger/core/`. Contract: `.kiro/steering/mcp-contracts.md` section 6 (v0.4).

Stitch is a decision-support demo. The allocation is a model result on demo data with illustrative severity and costs, not an operational plan.

## 1. Inputs

Per district `d`: affected population `pop_d`, severity `s_d` in [0, 1], road access `a_d` in [0, 1], air/boat share `alt_d` in [0, 1] (default 0), cost multiplier `m_d > 0` (default 1).

Per commodity `k`: unit cost `c_k >= 0`, need per person `n_k > 0`, supply `S_k >= 0`. A commodity with no `supply` entry has supply 0 (with a warning).

Optional: budget `B`, equity floor `phi` in [0, 1] (default 0), road-access threshold `tau` (default 0.1).

When the caller omits `districts`, they come from `data/demo/ledger/districts.parquet` for the scenario (22 Sindh districts: WorldPop population, OSM road-density proxy for access, illustrative air/boat shares and a severity prior; see `data/demo/MANIFEST.md`).

## 2. Derived quantities (`core/problem.py`, `normalize`)

1. Usable road access: `a'_d = a_d` if `a_d >= tau`, else 0.
2. Reachable fraction `min(1, a'_d + alt_d)`; reachable population `r_d = pop_d * min(1, a'_d + alt_d)`.
3. Access mode: `road` if `a_d >= tau`; `air_boat` if `a_d < tau` and `alt_d > 0`; `unreachable` if `a_d < tau`, `alt_d = 0` and `pop_d > 0`.
4. Unreached people `u_d = pop_d - r_d`, reported per district and in `warnings`.
5. Need `R_dk = r_d * n_k`. District weight `w_d = r_d * s_d`. Commodity weight `lambda_k = 1 / |K|`.
6. Districts with `r_d = 0` get no variables and zero allocation. The solver cannot send supplies where nothing can be delivered.
7. Supply ratio `rho_k = min(1, S_k / sum_d R_dk)` (1 if the total need is 0). Proportional share `share_dk = rho_k * R_dk`.

## 3. Optimisation model (`core/formulate.py`)

Variables: `x_dk >= 0` units sent (integer when `integer = true`), `f_dk` in [0, 1] coverage of the need.

```
maximize   sum_d sum_k  w_d * lambda_k * f_dk                    (total_coverage)

s.t.   R_dk * f_dk <= x_dk <= U_dk          for all d, k      U = R (LP), ceil(R) (MIP)
       sum_d x_dk <= S_k                    for all k         (supply:<k>)
       sum_dk c_k * m_d * x_dk <= B                           (budget, if given)
       f_dk >= phi * rho_k                  for all d, k      (equity floor)
```

`total_coverage` is in coverage-weighted people: a district counts its reachable people times its severity times the average coverage over commodities. `people_covered = sum_d r_d * cov_d` with `cov_d = sum_k lambda_k f_dk`.

The LP is solved in the substituted form `x = R f`: variables `f_dk` in `[phi * rho_k, 1]`, supply rows `sum_d R_dk f_dk <= S_k`, budget row `sum_dk c_k m_d R_dk f_dk <= B`. It has the same feasible set and objective, and every variable lies in [0, 1] whatever the size of `R`. The floor is then an exact variable bound. Rows and the objective are divided by their largest coefficient. The property tests found that the unscaled form misbehaved for tiny needs, tiny floors and subnormal severities (named regression tests in `tests/unit/test_regressions.py`).

The MIP (SCIP) keeps `x` integer in `[ceil(phi * share_dk - 1e-9), ceil(R_dk)]` and ties `f` to it by `R f <= x`. Up to one unit of over-delivery per district and commodity is allowed by `U = ceil(R)`; coverage stays at most 1 through `f <= 1`.

### Worked consequences

- The marginal value of one unit of `k` at `d` is `w_d * lambda_k / R_dk = s_d * lambda_k / n_k`. Population cancels. With one commodity, no budget and no floor, the LP is greedy by severity (property LED-P12 checks this against an independent greedy).
- `phi = 0` is pure efficiency. `phi = 1` with no budget is the proportional allocation (`x = share`, LED-P16).
- The total floor demand for `k` is `phi * min(S_k, sum_d R_dk) <= S_k`, so supply never makes a floor infeasible. Only the budget can. LP: `max_feasible_floor = min(1, B / sum_dk c_k m_d share_dk)`. MIP: the same check with integer ceilings, found by 40-step bisection on `phi` (no solver).
- A floor above `max_feasible_floor` is relaxed to it by default (`on_infeasible_floor = "relax"`, with a warning), or returns `status = "infeasible"` with a reason under `"error"`.

## 4. Post-processing (`core/postprocess.py`)

Solver noise below `1e-12 * R` is clamped. Integer quantities are rounded. If the rounded plan exceeds a supply or the budget, units are removed where they are worth least (per unit for supply, per currency unit for the budget), never below the integer floor `ceil(phi * share)`. Coverage, totals, `access_mode` and `unreached_people` are then recomputed from the final `x`, so every number in the output comes from the same formulas.

Floors are accepted within `1e-9 * B` of the budget, so a plan that sits exactly at its integer floors may exceed `B` by at most that (0.05 currency units on a budget of 45 million).

### MIP guard

After SCIP, the LP plan is rounded down to whole units and repaired. That plan is integer-feasible, so a SCIP plan worth more than `1e-3` (relative) less is wrong or stopped early. The Ledger eval found one: with needs around 1.9e7, SCIP upgraded `R f - x <= 0` to varbound constraints and reported an all-zero plan as optimal on a problem worth 1.6e6. In that case SCIP is re-run without the varbound upgrade within the remaining time limit, and the better of the two plans is returned with a warning. The upgrade stays on otherwise, because turning it off made other instances 100 times slower. The LP optimum bounds the MIP (any MIP plan gives an LP plan `f = min(1, x / R)` that is at least as good), so it also bounds the reported gap of the rounded plan.

## 5. Shadow prices and reduced costs (`core/sensitivity.py`)

`sensitivity_report` re-solves the LP relaxation at the floor the run applied, also for integer runs (`basis = "lp_relaxation"`; for integer runs the numbers are approximations). Units:

| Constraint | Meaning of the shadow price | Sign |
|---|---|---|
| `supply:<k>` | extra coverage-weighted people per extra unit of `k` | `>= 0` |
| `budget` | extra coverage-weighted people per extra currency unit | `>= 0` |
| `min_coverage:<d>` | coverage lost per unit of extra floor on district `d` (sum of the floor-bound reduced costs) | `<= 0` |
| `equity_floor` | coverage lost per unit of the uniform floor `phi` | `<= 0` |

A non-binding constraint has a shadow price of exactly 0 (LED-P6). A supply at or above its total need is never scarce. Reduced costs are per unit of commodity: positive at full coverage (an extra unit would have been worth that much), negative at the floor or at zero.

Reading a shadow price: in the demo with water, food and shelter and a budget of 3e7, `supply:food = 0.051` means one more kg of food adds 0.051 coverage-weighted people, and `budget = 0.043` means one more currency unit adds 0.043. These hold only on the allowable range below.

### Allowable ranges (`core/ranges.py`)

For each binding supply or budget constraint with a positive shadow price `y`, the range `[b - allowable_decrease, b + allowable_increase]` is where `y` stays the same, with every other constraint and the run's floor bounds fixed. pywraplp has no RHS ranging, so the Ledger finds it by parametric re-solves. The optimal value `V(b)` is piecewise linear and concave in `b`, so `y` is constant exactly where `V` follows the line `V(b) + y * delta`. A cutting-plane iteration finds the end of that piece: solve at a trial point; if the value is on the line, stop; otherwise move to where the tangent there meets the line. Each step lands on a later breakpoint, so the number of solves is at most the number of pieces. Limits: supply above total need and budget above the cost of every need add nothing; the right-hand side cannot fall below what the fixed floors use. Property LED-P20 checks that moving to either end changes an independent `optimize` by exactly `y` times the change. Floor constraints are not ranged.

## 6. Efficiency and equity

`equity_tradeoff` re-solves the LP at `floor_steps` equally spaced floors from 0 to 1 plus `max_feasible_floor`. Floors above it are reported `infeasible` with null values and are not solved. `equity_cost` is the coverage at floor 0 minus the coverage at the run's floor (null when the run has no floor). Coverage never rises with the floor (LED-P10) and floor 0 equals the unconstrained optimum (LED-P11).

In the demo eval (`evals/ledger`, the Brain's reference request: water 105 L, food 3.5 kg and 0.2 shelter kits per person, no budget) coverage falls from 1.0 at floor 0 to 0.47 at floor 1 (relative to floor 0), in equal steps of about 0.053 per 0.1 of floor. The steps are equal in this instance because the floor reserves a proportional share and the remaining supply still goes to the same most valuable districts; that is not guaranteed in general. A budget makes the curve stop at `max_feasible_floor`.

## 7. Assumptions

- Severity is a weight, not a measured quantity. The demo severity prior and air/boat shares are illustrative.
- Road access scales reachable population linearly. Below `tau` road delivery is impossible and only the air/boat share is reachable.
- Commodities have equal weight (`lambda_k = 1/|K|`). Coverage is linear in delivered units up to the need. There is no transport network, no time dimension and no warehouse location.
- Costs are in illustrative cost units, multiplied per district by `m_d`.
- Population is a modelled estimate (WorldPop), not a census of affected people.

## 8. Limitations

- GLOP works to a tolerance relative to the objective scale. Coverage below about 1e-9 of `sum_d w_d` (tiny budgets) may come back as 0. The P10 and P13 properties therefore use a tolerance relative to that scale.
- `cost_per_person_covered` is 0.0 with a warning when nobody is covered, because the contract types it as a number (LED-R5.2 asked for null).
- The MIP has a time limit (default 10 s, capped at 30 s). On a timeout with an incumbent the result is `feasible` with `optimality_gap`; without one the tool returns `TIMEOUT` (retryable).
- Shadow prices, ranges and the trade-off curve of integer runs come from the LP relaxation.
- At most 500 districts and 20 commodities.
- The Ledger never uses the network. A `live` request with the committed dataset returns `mode = demo` and a `MODE_FALLBACK` warning.

## 9. Evidence

- Properties LED-P1 to P20 in `organs/ledger/tests/property/` (Hypothesis, `ci` profile 200 examples) and hand-solved LPs in `tests/unit/test_lp_hand_solved.py` and `tests/unit/test_ranges.py`.
- Benchmark `python -m stitch_ledger.bench` (200 districts x 10 commodities) and `tests/perf/test_benchmark.py`.
- Eval `python -m evals.run --organ ledger --seed 0` (section 4 of `organs/ledger/README.md`).
