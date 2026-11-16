# ledger-mcp: Requirements

Organ: aid allocation optimization. Prefix `LED`. Contract: `mcp-contracts.md` §6.

## Introduction
The Ledger decides how much of each relief commodity goes to each district, given affected population, road access, flood severity, and supply limits. It reports cost-benefit and shadow prices.

## Glossary
- **Coverage** of a district: fraction of its affected population whose need is met, `min(1, delivered_need / required_need)` across commodities, as defined in design.
- **Effective weight**: `population_affected × severity × road_access` (exact form fixed in design).
- **Proportional share** of district d for commodity k: `share_dk = need_dk × min(1, supply_k / total_need_k)`. The allocation a naive pro-rata rule would give.
- **Equity floor** `φ ∈ [0,1]`: each district must receive at least `φ × share_dk` of every commodity. `φ = 0` is pure efficiency, `φ = 1` is the proportional allocation.
- **Road-denied district**: `road_access` below the usable-access threshold (default 0.1). Trucks cannot be relied on. Only air or boat delivery can reach it.
- **Shadow price**: marginal value of one more unit of a constrained resource (from the LP relaxation).

## Requirements

### LED-R1 Model formulation
1. THE Ledger SHALL formulate allocation as a linear program, or a mixed-integer program when `integer = true`, using OR-Tools or PuLP.
2. THE Ledger SHALL maximize total effective-weighted coverage subject to per-commodity supply limits, an optional budget, and an optional equity floor (a fraction `equity_floor` of each district's proportional share of each commodity).
3. THE Ledger SHALL cap each district's allocation at its required need (no over-delivery beyond need).
4. THE Ledger SHALL scale each district's reachable population by its usable road access, and SHALL add the district's optional air/boat capacity `alt_delivery_fraction` (share of the population that air or boat delivery can carry, default 0).
5. WHERE a district is road-denied, THE Ledger SHALL cap its allocation at what air/boat delivery can carry. IF that capacity is zero, THEN THE Ledger SHALL mark the district `unreachable`, allocate nothing to it, and list it and its unreached people in `warnings` and in the output.
6. THE Ledger SHALL NOT allocate to a road-denied district beyond its air/boat capacity, plus at most one unit of integer rounding, under any input, and SHALL expose each district's `access_mode` (`road`, `air_boat`, `unreachable`) in the output.

### LED-R2 Inputs
1. WHEN `optimize_allocation` is called, THE Ledger SHALL validate that populations, supplies, costs, and budget are non-negative and that `severity` and `road_access` lie in [0,1].
2. IF input validation fails, THEN THE Ledger SHALL return `INVALID_INPUT` and not run the solver.
3. THE Ledger SHALL source population from WorldPop aggregates and road access from OSM-derived scores in the demo dataset, with provenance for each.
4. WHERE the caller supplies explicit district data (the optional `districts` override), THE Ledger SHALL use it instead of the dataset, with no merging, so tests and what-if runs can inject their own data.
5. THE Ledger SHALL expose the static district attributes of a scenario as the MCP resource `ledger://scenario/{scenario_id}/districts` for the Brain.

### LED-R3 Solving
1. THE Ledger SHALL return `status` as `optimal`, `feasible` (time limit reached with an incumbent), or `infeasible`.
2. THE Ledger SHALL compute `max_feasible_floor`, the highest equity floor that can be satisfied.
3. IF the requested `equity_floor` exceeds `max_feasible_floor`, THEN, by default (`on_infeasible_floor = "relax"`), THE Ledger SHALL solve at `max_feasible_floor` and return that allocation with `floor_requested`, `floor_applied`, `max_feasible_floor`, and a warning.
4. WHERE `on_infeasible_floor = "error"`, THE Ledger SHALL instead return `status = infeasible` with an `infeasibility_reason` naming the binding constraint and the `max_feasible_floor`.
5. WHEN `status = feasible`, THE Ledger SHALL report `optimality_gap` from the solver bound.
6. THE Ledger SHALL enforce `solver_time_limit_s` and return the best incumbent when the limit is reached.
7. THE Ledger SHALL produce identical output for identical input (deterministic tie-breaking).

### LED-R4 Safety constraints on output
1. THE Ledger SHALL NOT allocate more of any commodity than its supply.
2. THE Ledger SHALL NOT output negative quantities.
3. WHERE `integer = true`, THE Ledger SHALL output integral quantities.
4. THE Ledger SHALL NOT exceed the budget when one is supplied.
5. THE Ledger SHALL NOT report coverage above 1.0 for any district.

### LED-R5 Cost-benefit
1. THE Ledger SHALL report total cost, people covered, and cost per person covered.
2. IF no people are covered, THEN THE Ledger SHALL report `cost_per_person_covered = null` and not divide by zero.

### LED-R6 Sensitivity
1. WHEN `sensitivity_report` is called with a prior `run_id`, THE Ledger SHALL return shadow prices for each supply, budget, and floor constraint, with `binding` flags.
2. WHERE the original run used integers, THE Ledger SHALL compute shadow prices from the LP relaxation and say so in `basis` and `notes`.
3. THE Ledger SHALL return reduced costs and allowable ranges where the solver provides them.
4. IF the `run_id` is unknown or expired, THEN THE Ledger SHALL return `NOT_FOUND`.
5. Non-binding constraints SHALL have a shadow price of zero (within 1e-9).

### LED-R7 Performance
1. THE Ledger SHALL solve instances of up to 200 districts × 10 commodities in under 10 s on 2 vCPU.

### LED-R8 Operations
1. THE Ledger SHALL expose `GET /healthz` and a `Provenance` block listing the data sources and solver version.
2. THE Ledger SHALL keep run results in memory or DuckDB for at least 24 h to support `sensitivity_report`.

### LED-R9 Eval
1. THE Ledger eval SHALL generate randomized instances (seeded) and report feasibility rate, optimality gap distribution, solve time, and comparison with a greedy proportional baseline (coverage uplift).

### LED-R10 Equity trade-off
1. WHEN `sensitivity_report` is called, THE Ledger SHALL also return `equity_tradeoff`: for `floor_steps` equally spaced floors `f` from 0 to 1 (default 11 points) plus `f_max`, report `status`, `total_coverage`, and `people_covered`. `f_max` is the largest feasible uniform floor. Floors at or below `f_max` are re-solved; floors above it are reported `infeasible` with null values, so the UI can show where equity becomes unaffordable.
2. THE Ledger SHALL report `equity_cost`, the coverage given up in the original run by its floor: coverage at floor 0 minus coverage at the run's floor (null when the run had no floor).
3. THE trade-off points SHALL use the same solver mode as the original run, or the LP relaxation with `basis` stating so.
4. THE trade-off computation SHALL finish in under 10 s for demo scenarios, and otherwise return the points computed so far with a warning.

### LED-R11 Demo-first
1. THE Ledger SHALL run on committed district, population, and road-access data with no network calls, enforced by tests that disable sockets.

## Correctness properties (formalized in design)
- LED-P1: for every valid input, for each commodity, sum of allocations <= supply.
- LED-P2: all allocated quantities >= 0.
- LED-P3: increasing any commodity's supply (all else equal) never reduces `total_coverage` (LP mode exact; MIP mode within gap tolerance, stated in design).
- LED-P4: no district's coverage exceeds 1.
- LED-P5: total cost <= budget when given.
- LED-P6: shadow price of a non-binding constraint is 0; shadow price of a supply constraint is >= 0.
- LED-P7: permuting the order of districts does not change `total_coverage`.
- LED-P8: scaling all populations by k>0 and need accordingly yields coverage fractions unchanged (scale invariance), where applicable.
- LED-P9: output is a deterministic function of input.

- LED-P10: along the equity trade-off, `total_coverage` is non-increasing as the floor increases.
- LED-P11: the trade-off point at floor 0 equals the unconstrained optimum within solver tolerance.
- LED-P12: single commodity, no budget, no floor: the LP optimum equals the greedy-by-severity value.
- LED-P13: the optimum is at least the coverage of the proportional baseline.
- LED-P14: with `integer = true`, outputs are integral and at most `ceil(need)`.
- LED-P15: `max_feasible_floor` is tight: feasible at the value, infeasible just above it when it is below 1.
- LED-P16: with `equity_floor = 1` and no budget, the allocation equals each district's proportional share.
- LED-P17: an `unreachable` district receives zero of every commodity and appears in the output and warnings.
- LED-P18: a road-denied district never receives more than its air/boat capacity, plus at most one unit of integer rounding (none in LP mode).
- LED-P19: with `relax`, `floor_applied = min(floor_requested, max_feasible_floor)`.

## Out of scope
Vehicle routing and last-mile logistics. Multi-period dynamic allocation. Prices as real market data.

## Decisions (resolved)
1. Objective: maximize weighted coverage with an optional equity floor. The UI shows shadow prices and the coverage-versus-equity-floor trade-off.
2. Demo commodities: food packs, clean water (liters), shelter kits, and medical kits.