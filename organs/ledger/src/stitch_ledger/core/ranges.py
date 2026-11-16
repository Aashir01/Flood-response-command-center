"""Allowable ranges of binding supply and budget constraints (LED-R6.3, ledger task 16).

For a constraint with right-hand side ``b`` and shadow price ``y > 0`` the range is the interval
``[b - allowable_decrease, b + allowable_increase]`` on which the shadow price stays ``y``, with
every other constraint (including the equity floor bounds of the run) held fixed. pywraplp does
not expose RHS ranging, so it is found by parametric re-solves of the LP relaxation.

The optimal value ``V(b)`` of an LP is piecewise linear and concave in ``b``, so the shadow price
is constant exactly where ``V`` follows the line ``V(b) + y * delta``. The end of that piece is
found by a cutting-plane iteration: solve at a trial point ``t``; if ``V(t)`` is on the line, ``t``
is the end; otherwise the tangent at ``t`` (slope = the dual there) meets the line at a point
closer to ``b``, which is the next trial. Each step lands on a later breakpoint of ``V`` or on the
end itself, so it needs at most as many solves as ``V`` has pieces between ``b`` and ``t``.

Search limits: a supply above its total need cannot add coverage (``f <= 1``), a budget above the
cost of covering every need cannot either, and the right-hand side cannot fall below what the
fixed floor bounds already use (or below 0).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ortools.linear_solver import pywraplp

from stitch_ledger.core.formulate import Model, build
from stitch_ledger.core.problem import Problem

MAX_STEPS = 60
REL_TOL = 1e-7
DEFAULT_BUDGET_S = 5.0


@dataclass(frozen=True)
class RangeLine:
    constraint: str
    allowable_increase: float
    allowable_decrease: float


@dataclass(frozen=True)
class Ranges:
    lines: tuple[RangeLine, ...]
    skipped: tuple[str, ...]  # constraints not ranged because the time budget ran out


class _Param:
    """One right-hand side of the LP relaxation, scaled as in ``formulate``."""

    def __init__(self, model: Model, row: pywraplp.Constraint, row_scale: float) -> None:
        self.model = model
        self.row = row
        self.row_scale = row_scale
        self.original_ub = row.ub()

    def value_and_dual(self, rhs: float) -> tuple[float, float] | None:
        self.row.SetUb(rhs / self.row_scale)
        code = self.model.solver.Solve()
        if code != pywraplp.Solver.OPTIMAL:
            return None
        scale = self.model.objective_scale
        value = self.model.solver.Objective().Value() * scale
        dual = max(0.0, self.row.dual_value() * scale / self.row_scale)
        return value, dual

    def restore(self) -> None:
        self.row.SetUb(self.original_ub)


def _piece_end(param: _Param, b: float, v0: float, y: float, limit: float, direction: int) -> float:
    """Largest ``s`` in ``[0, limit]`` with ``V(b + direction * s) = v0 + direction * y * s``."""
    if limit <= 0.0:
        return 0.0
    t = limit
    for _ in range(MAX_STEPS):
        res = param.value_and_dual(b + direction * t)
        if res is None:  # cannot happen inside the limits; be conservative
            t *= 0.5
            continue
        vt, yt = res
        line = v0 + direction * y * t
        if abs(vt - line) <= REL_TOL * max(1.0, abs(v0), abs(line)):
            return t
        # tangent at t: V(b + d s) ~ vt + d * yt * (s - t); meet the line v0 + d * y * s
        denom = (y - yt) if direction > 0 else (yt - y)
        if denom <= 0.0:
            return 0.0
        nxt = ((vt - yt * t - v0) / denom) if direction > 0 else ((vt + yt * t - v0) / denom)
        if not (0.0 <= nxt < t) or t - nxt <= REL_TOL * max(1.0, t):
            return max(0.0, min(nxt, t))
        t = nxt
    return t


def _lower_use(model: Model, row: pywraplp.Constraint, row_scale: float) -> float:
    """What the fixed variable lower bounds (the floors) already use of this row, unscaled."""
    used = 0.0
    for var in model.f.values():
        coef = row.GetCoefficient(var)
        if coef:
            used += coef * var.lb()
    return used * row_scale


def allowable_ranges(
    problem: Problem,
    floor: float,
    shadow: dict[str, float],
    *,
    budget_s: float = DEFAULT_BUDGET_S,
) -> Ranges:
    """Ranges for the constraints in ``shadow`` (name to shadow price) whose price is positive.

    Only ``supply:<k>`` and ``budget`` are ranged. ``floor`` is the applied floor of the run.
    """
    lp = problem.with_integer(False)
    model = build(lp, floor, integer=False)
    model.solver.SetNumThreads(1)
    base = model.solver.Solve()
    if base != pywraplp.Solver.OPTIMAL:
        return Ranges((), tuple(n for n, v in shadow.items() if v > 0))
    v0 = model.solver.Objective().Value() * model.objective_scale
    start = time.perf_counter()
    lines: list[RangeLine] = []
    skipped: list[str] = []
    targets: list[tuple[str, pywraplp.Constraint, float, float, float]] = []
    for k, c in enumerate(lp.commodities):
        name = f"supply:{c.commodity_id}"
        if shadow.get(name, 0.0) > 0.0 and k in model.supply_rows:
            targets.append((name, model.supply_rows[k], model.supply_scale[k], c.supply,
                            c.total_need))  # fmt: skip
    if lp.budget is not None and model.budget_row is not None and shadow.get("budget", 0.0) > 0:
        full = math.fsum(
            lp.unit_cost(d, k) * lp.need[d][k]
            for d in lp.active
            for k in range(len(lp.commodities))
        )
        targets.append(("budget", model.budget_row, model.budget_scale, lp.budget, full))
    for name, row, row_scale, b, top in targets:
        if time.perf_counter() - start > budget_s:
            skipped.append(name)
            continue
        y = shadow[name]
        param = _Param(model, row, row_scale)
        try:
            inc = _piece_end(param, b, v0, y, max(0.0, top - b), +1)
            low = max(0.0, _lower_use(model, row, row_scale))
            dec = _piece_end(param, b, v0, y, max(0.0, b - low), -1)
        finally:
            param.restore()
        lines.append(RangeLine(name, inc, dec))
    return Ranges(tuple(lines), tuple(skipped))
