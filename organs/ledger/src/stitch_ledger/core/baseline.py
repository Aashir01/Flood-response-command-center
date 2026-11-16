"""Proportional (pro-rata) baseline allocation used by the evals and by LED-P13.

``x_dk = share_dk``, scaled down uniformly when the budget cannot pay for it. It always respects
supply (``sum_d share_dk = min(S_k, need)``). In integer mode each quantity is rounded down so it
stays feasible.
"""

from __future__ import annotations

import math

from stitch_ledger.core.postprocess import Allocation, Evaluation, cost_of, evaluate
from stitch_ledger.core.problem import Problem


def proportional_allocation(problem: Problem) -> Allocation:
    x: Allocation = {
        (d, k): problem.share[d][k] for d in problem.active for k in range(len(problem.commodities))
    }
    if problem.budget is not None:
        cost = cost_of(problem, x)
        if cost > problem.budget:
            factor = problem.budget / cost if cost > 0 else 0.0
            x = {key: q * factor for key, q in x.items()}
    if problem.integer:
        x = {key: float(math.floor(q + 1e-9)) for key, q in x.items()}
    return x


def proportional_baseline(problem: Problem) -> Evaluation:
    """Coverage, cost and people covered of the proportional allocation."""
    return evaluate(problem, proportional_allocation(problem))
