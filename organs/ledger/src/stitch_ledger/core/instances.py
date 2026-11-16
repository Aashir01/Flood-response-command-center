"""Seeded random allocation instances for the benchmark (LED-R7) and the eval harness (LED-R9).

Pure: ``random_spec(seed, ...)`` is a deterministic function of its arguments (``random.Random``
with the given seed, no global state). Instances are synthetic and are never presented as data.

Shape of an instance:

* populations log-uniform in [1e3, 2e6]; severity uniform in [0, 1];
* road access uniform in [0, 1], with about 10 % of districts below the 0.1 threshold, half of
  those with an air/boat share in [0.05, 0.4] and half unreachable;
* cost multipliers uniform in [0.8, 2.0];
* per commodity: unit cost in [0.05, 20], need per person in [0.5, 20], supply a fraction
  ``scarcity`` (uniform in [0.2, 1.2]) of the total reachable need;
* budget (when ``with_budget``) a fraction in [0.2, 1.0] of the cost of the full proportional
  share, so the budget binds in most instances and the equity floor is sometimes capped.
"""

from __future__ import annotations

import math
import random

from stitch_ledger.core.problem import (
    DEFAULT_MIN_ROAD_ACCESS,
    CommoditySpec,
    DistrictSpec,
    ProblemSpec,
    normalize,
)


def random_spec(
    seed: int,
    n_districts: int = 20,
    n_commodities: int = 3,
    *,
    with_budget: bool = True,
    equity_floor: float = 0.0,
    integer: bool = False,
    solver_time_limit_s: float = 10.0,
) -> ProblemSpec:
    rng = random.Random(seed)
    districts: list[DistrictSpec] = []
    for i in range(n_districts):
        pop = float(round(math.exp(rng.uniform(math.log(1e3), math.log(2e6)))))
        severity = rng.random()
        access = rng.random()
        alt = 0.0
        if rng.random() < 0.10:
            access = rng.uniform(0.0, DEFAULT_MIN_ROAD_ACCESS * 0.99)
            alt = rng.uniform(0.05, 0.4) if rng.random() < 0.5 else 0.0
        districts.append(
            DistrictSpec(
                district_id=f"d{i:03d}",
                population=pop,
                severity=severity,
                road_access=access,
                alt_delivery_fraction=alt,
                cost_multiplier=rng.uniform(0.8, 2.0),
            )
        )
    raw = [
        (f"k{j:02d}", rng.uniform(0.05, 20.0), rng.uniform(0.5, 20.0), rng.uniform(0.2, 1.2))
        for j in range(n_commodities)
    ]
    # Supply as a fraction of the reachable need: normalise once without supply to get needs.
    probe = normalize(
        ProblemSpec(
            districts=tuple(districts),
            commodities=tuple(CommoditySpec(c, cost, need, 0.0) for c, cost, need, _ in raw),
        )
    )
    commodities = []
    for k, (cid, cost, need, scarcity) in enumerate(raw):
        total_need = sum(row[k] for row in probe.need)
        commodities.append(CommoditySpec(cid, cost, need, float(math.floor(scarcity * total_need))))
    spec = ProblemSpec(
        districts=tuple(districts),
        commodities=tuple(commodities),
        equity_floor=equity_floor,
        integer=integer,
        solver_time_limit_s=solver_time_limit_s,
    )
    if with_budget:
        problem = normalize(spec)
        full = sum(
            problem.unit_cost(d, k) * problem.share[d][k]
            for d in range(len(problem.districts))
            for k in range(len(problem.commodities))
        )
        spec = ProblemSpec(
            districts=spec.districts,
            commodities=spec.commodities,
            budget=rng.uniform(0.2, 1.0) * full,
            equity_floor=equity_floor,
            integer=integer,
            solver_time_limit_s=solver_time_limit_s,
        )
    return spec
