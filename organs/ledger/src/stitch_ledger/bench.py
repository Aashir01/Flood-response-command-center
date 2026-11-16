"""Benchmark of the Ledger at 200 districts x 10 commodities (LED-R7, ledger task 13).

    python -m stitch_ledger.bench [--seed 0] [--repeat 3] [--out bench.json]

Measures wall time (median of ``--repeat`` runs) of:

* ``lp``: ``optimize`` with ``integer = false`` and an equity floor of 0.3;
* ``mip``: the same with ``integer = true`` (SCIP, 10 s limit), reporting status and gap;
* ``sensitivity``: duals at the applied floor (``analyze``);
* ``ranges``: allowable ranges of the priced supply and budget constraints;
* ``sweep``: the equity trade-off with the default 11 floor steps;
* ``sweep_no_budget``: the same without a budget, so every floor is feasible and solved (the
  worst case of the sweep: 11 LP solves).

The budget (LED-R7) is 10 s for ``optimize_allocation`` on 2 vCPU. The test in
``tests/perf/test_benchmark.py`` asserts a margin on the same instance.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from stitch_ledger.core.instances import random_spec
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import ProblemSpec, normalize
from stitch_ledger.core.ranges import allowable_ranges
from stitch_ledger.core.sensitivity import analyze
from stitch_ledger.core.tradeoff import lp_f_max, sweep

N_DISTRICTS = 200
N_COMMODITIES = 10
BUDGET_S = 10.0


def bench_spec(seed: int = 0, *, integer: bool = False) -> ProblemSpec:
    return random_spec(
        seed, N_DISTRICTS, N_COMMODITIES, equity_floor=0.3, integer=integer,
        solver_time_limit_s=BUDGET_S,
    )  # fmt: skip


def _timed(fn: Callable[[], Any], repeat: int) -> tuple[float, Any]:
    times: list[float] = []
    out: Any = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), out


def run(seed: int = 0, repeat: int = 3) -> dict[str, Any]:
    lp_spec = bench_spec(seed)
    mip_spec = bench_spec(seed, integer=True)
    problem = normalize(lp_spec)
    applied = min(lp_spec.equity_floor, lp_f_max(problem))

    lp_s, lp = _timed(lambda: optimize(lp_spec), repeat)
    mip_s, mip = _timed(lambda: optimize(mip_spec), 1 if repeat < 2 else 2)
    sens_s, sens = _timed(lambda: analyze(problem, applied), repeat)
    priced = {
        s.constraint: s.value
        for s in sens.shadow_prices
        if s.binding and s.value > 0 and s.constraint.startswith(("supply", "budget"))
    }
    ranges_s, ranged = _timed(lambda: allowable_ranges(problem, applied, priced), repeat)
    sweep_s, curve = _timed(lambda: sweep(problem, 11, applied), repeat)
    free = normalize(random_spec(seed, N_DISTRICTS, N_COMMODITIES, with_budget=False))
    free_s, free_curve = _timed(lambda: sweep(free, 11, 0.3), repeat)
    return {
        "instance": {
            "seed": seed,
            "districts": N_DISTRICTS,
            "commodities": N_COMMODITIES,
            "equity_floor": lp_spec.equity_floor,
            "variables": 2 * len(problem.active) * N_COMMODITIES,
        },
        "budget_s": BUDGET_S,
        "lp": {"wall_s": lp_s, "status": lp.status, "gap": lp.optimality_gap},
        "mip": {"wall_s": mip_s, "status": mip.status, "gap": mip.optimality_gap},
        "sensitivity": {"wall_s": sens_s},
        "ranges": {"wall_s": ranges_s, "ranged": len(ranged.lines), "skipped": len(ranged.skipped)},
        "sweep": {"wall_s": sweep_s, "solves": curve.solves, "points": len(curve.points)},
        "sweep_no_budget": {"wall_s": free_s, "solves": free_curve.solves},
        "host": {"python": platform.python_version(), "machine": platform.machine()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stitch_ledger.bench")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = run(args.seed, args.repeat)
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
