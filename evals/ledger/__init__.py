"""Ledger evals (LED-R9): ``python -m evals.run --organ ledger --seed 0 [--fast]``.

Synthetic part (``mode = "synthetic"``): seeded random instances from
``stitch_ledger.core.instances.random_spec``. For each instance the solver result is checked
against its constraints independently of the solver (supply, budget, non-negativity, coverage
<= 1, applied floor), and compared with the proportional baseline (``core/baseline.py``):

* feasibility rate: share of instances whose returned plan passes the independent check;
* MIP optimality gap distribution (p50, p90, max) at the 10 s time limit;
* solve time distribution (p50, p95, max) for LP and MIP;
* coverage uplift: ``(opt - baseline) / baseline`` of ``total_coverage`` (mean and minimum).

Demo part (``mode = "demo"``): the equity curve of the committed ``demo-sindh-2022`` dataset with
the reference request of ``brain/config/scenarios.yaml`` (copied here; evals do not import the
Brain). Coverage values are reported as a fraction of the coverage at floor 0.

Every value except the solve times is a deterministic function of ``seed``. Per-instance rows go
to ``evals/results/ledger_instances.parquet`` and the curve to ``ledger_equity_curve.json``
(both git-ignored).
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from evals.models import MetricResult

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
TOL = 1e-6
DEMO_SCENARIO = "demo-sindh-2022"
PERIOD_DAYS = 7
# (id, unit_cost, per_person_need, supply): mirrors brain/config/scenarios.yaml demo-sindh-2022.
DEMO_COMMODITIES = (
    ("food", 0.8, 0.5 * PERIOD_DAYS, 12_000_000.0),
    ("shelter", 35.0, 0.2, 600_000.0),
    ("water", 0.02, 15.0 * PERIOD_DAYS, 400_000_000.0),
)


@dataclass(frozen=True)
class Row:
    seed: int
    districts: int
    commodities: int
    integer: bool
    floor: float
    status: str
    feasible: bool
    gap: float | None
    wall_s: float
    coverage: float
    baseline: float


def _check(spec: object, result: object) -> bool:
    """Independent constraint check of a returned plan (no solver)."""
    from stitch_ledger.core.postprocess import Result
    from stitch_ledger.core.problem import ProblemSpec, normalize

    assert isinstance(spec, ProblemSpec) and isinstance(result, Result)
    if result.status == "infeasible":
        return False
    problem = normalize(spec)
    q = {(d, k): v for d, k, v in result.allocation}
    if any(v < -TOL for v in q.values()):
        return False
    for k, c in enumerate(problem.commodities):
        sent = sum(q.get((d.district_id, c.commodity_id), 0.0) for d in problem.districts)
        if sent > c.supply * (1 + TOL) + TOL:
            return False
        for i, d in enumerate(problem.districts):
            x = q.get((d.district_id, c.commodity_id), 0.0)
            need = problem.need[i][k]
            if need == 0 and x > TOL:
                return False
            floor = result.floor_applied * problem.share[i][k]
            if spec.integer:
                floor = max(0.0, float(math.ceil(floor - 1e-9)))
            if x < floor * (1 - TOL) - TOL:
                return False
    cost = sum(
        problem.unit_cost(i, k) * q.get((d.district_id, c.commodity_id), 0.0)
        for i, d in enumerate(problem.districts)
        for k, c in enumerate(problem.commodities)
    )
    if spec.budget is not None and cost > spec.budget * (1 + TOL) + TOL:
        return False
    return all(cv.fraction <= 1 + TOL for cv in result.coverage)


def _instances(fast: bool, seed: int) -> list[tuple[int, int, int, bool, float]]:
    import random

    rng = random.Random(seed)
    n = 24 if fast else 200
    out = []
    for i in range(n):
        districts = rng.choice((5, 10, 20, 50) if fast else (5, 10, 20, 50, 100, 200))
        commodities = rng.randint(1, 4 if fast else 10)
        integer = i % 4 == 0
        floor = rng.choice((0.0, 0.0, 0.25, 0.5, 0.75, 1.0))
        out.append((seed * 100_003 + i, districts, commodities, integer, floor))
    return out


def run_instances(fast: bool, seed: int) -> list[Row]:
    from stitch_ledger.core.baseline import proportional_baseline
    from stitch_ledger.core.instances import random_spec
    from stitch_ledger.core.optimize import optimize
    from stitch_ledger.core.problem import normalize

    rows: list[Row] = []
    for s, nd, nk, integer, floor in _instances(fast, seed):
        spec = random_spec(s, nd, nk, equity_floor=floor, integer=integer)
        t0 = time.perf_counter()
        result = optimize(spec)
        wall = time.perf_counter() - t0
        base = proportional_baseline(normalize(spec))
        rows.append(
            Row(
                seed=s,
                districts=nd,
                commodities=nk,
                integer=integer,
                floor=floor,
                status=result.status,
                feasible=_check(spec, result),
                gap=result.optimality_gap,
                wall_s=wall,
                coverage=result.total_coverage,
                baseline=base.total_coverage,
            )
        )
    return rows


def demo_curve(steps: int = 11) -> list[dict[str, float | str | None]]:
    from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize
    from stitch_ledger.core.tradeoff import sweep
    from stitch_ledger.data.loader import load_scenario

    scenario = load_scenario(DEMO_SCENARIO)
    spec = ProblemSpec(
        districts=tuple(
            DistrictSpec(
                r.district_id,
                float(r.population),
                r.default_severity,
                r.road_access,
                r.alt_delivery_fraction,
            )
            for r in scenario.districts
        ),
        commodities=tuple(CommoditySpec(c, cost, need, s) for c, cost, need, s in DEMO_COMMODITIES),
    )
    t = sweep(normalize(spec), steps, 0.0)
    top = t.points[0].total_coverage or 0.0
    return [
        {
            "floor": p.floor,
            "status": p.status,
            "total_coverage": p.total_coverage,
            "people_covered": p.people_covered,
            "coverage_vs_floor0": (p.total_coverage / top) if p.total_coverage and top else None,
        }
        for p in t.points
    ]


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def _write_details(rows: list[Row], curve: list[dict[str, float | str | None]]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "ledger_equity_curve.json").write_text(
        json.dumps(curve, indent=2) + "\n", encoding="utf-8"
    )
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:  # pragma: no cover - pyarrow is a ledger dependency
        return
    table = pa.Table.from_pylist([r.__dict__ for r in rows])
    pq.write_table(table, RESULTS_DIR / "ledger_instances.parquet")


def run(fast: bool = False, seed: int = 0, write_details: bool = True) -> list[MetricResult]:
    from evals.run import git_sha

    rows = run_instances(fast, seed)
    curve = demo_curve()
    if write_details:
        _write_details(rows, curve)

    now = datetime.now(UTC)
    sha = git_sha()
    synth = f"ledger-synthetic-{'fast' if fast else 'full'}-{len(rows)}"

    def m(
        id_: str,
        label: str,
        value: float,
        *,
        direction: Literal["higher", "lower"],
        target: float | None = None,
        unit: str = "",
        dataset: str = synth,
        mode: Literal["demo", "live", "synthetic"] = "synthetic",
        notes: str = "",
    ) -> MetricResult:
        return MetricResult(
            id=id_,
            label=label,
            value=value,
            target=target,
            unit=unit,
            direction=direction,
            dataset=dataset,
            mode=mode,
            timestamp=now,
            git_sha=sha,
            seed=seed,
            notes=notes,
        )

    mip = [r for r in rows if r.integer]
    gaps = [r.gap for r in mip if r.gap is not None]
    uplift = [(r.coverage - r.baseline) / r.baseline for r in rows if r.baseline > 1e-9]
    lp_t = [r.wall_s for r in rows if not r.integer]
    mip_t = [r.wall_s for r in mip]
    metrics = [
        m(
            "ledger.feasibility_rate",
            "Plans passing an independent constraint check",
            sum(r.feasible for r in rows) / len(rows),
            direction="higher",
            target=1.0,
            notes="supply, budget, non-negativity, coverage <= 1 and the applied floor",
        ),
        m(
            "ledger.mip_gap_p50",
            "MIP optimality gap, median",
            _quantile(gaps, 0.5),
            direction="lower",
        ),
        m(
            "ledger.mip_gap_p90",
            "MIP optimality gap, 90th percentile",
            _quantile(gaps, 0.9),
            direction="lower",
            target=0.01,
            notes=f"{len(mip)} integer instances, 10 s limit",
        ),
        m(
            "ledger.mip_gap_max",
            "MIP optimality gap, max",
            max(gaps, default=0.0),
            direction="lower",
        ),
        m(
            "ledger.lp_solve_time_p95_s",
            "LP solve time, 95th percentile",
            _quantile(lp_t, 0.95),
            direction="lower",
            target=10.0,
            unit="s",
            notes="wall time on the eval host; not deterministic",
        ),
        m(
            "ledger.mip_solve_time_p95_s",
            "MIP solve time, 95th percentile",
            _quantile(mip_t, 0.95),
            direction="lower",
            target=10.0,
            unit="s",
            notes="wall time on the eval host; not deterministic",
        ),
        m(
            "ledger.solve_time_max_s",
            "Solve time, max",
            max(lp_t + mip_t, default=0.0),
            direction="lower",
            unit="s",
            notes="wall time on the eval host; not deterministic",
        ),
        m(
            "ledger.coverage_uplift_mean",
            "Coverage uplift over the proportional baseline, mean",
            statistics.fmean(uplift) if uplift else 0.0,
            direction="higher",
            unit="fraction",
        ),
        m(
            "ledger.coverage_uplift_min",
            "Coverage uplift over the proportional baseline, min",
            min(uplift, default=0.0),
            direction="higher",
            target=-1e-6,
            unit="fraction",
            notes="LED-P13: the optimum is never below the baseline",
        ),
    ]
    feasible = [p for p in curve if p["status"] != "infeasible"]
    for p in curve:
        floor = float(p["floor"])  # type: ignore[arg-type]
        ratio = p["coverage_vs_floor0"]
        if ratio is None or abs(floor * 10 - round(floor * 10)) > 1e-9:
            continue
        metrics.append(
            m(
                f"ledger.demo.equity_curve.floor_{floor:.1f}",
                f"Demo equity curve: coverage at floor {floor:.1f} vs floor 0",
                float(ratio),
                direction="higher",
                unit="fraction",
                dataset=DEMO_SCENARIO,
                mode="demo",
                notes="demo dataset with illustrative severity and the Brain's reference request",
            )
        )
    last = feasible[-1] if feasible else None
    metrics.append(
        m(
            "ledger.demo.equity_cost_full_floor",
            "Demo: coverage given up at the highest feasible floor",
            1.0 - float(last["coverage_vs_floor0"] or 0.0) if last else 0.0,
            direction="lower",
            unit="fraction",
            dataset=DEMO_SCENARIO,
            mode="demo",
        )
    )
    return metrics


__all__ = ["Row", "demo_curve", "run", "run_instances"]
