"""LED-R7: 200 districts x 10 commodities well under the 10 s budget; LED-R11: the suite runs
with sockets disabled. Thresholds keep a 2x margin (or more) for a slower 2 vCPU CI host."""

from __future__ import annotations

import asyncio
import socket
import time

import pytest

from stitch_common.testing.plugin import NetworkBlockedError
from stitch_common.tooling import run_tool
from stitch_ledger import bench
from stitch_ledger.core.instances import random_spec
from stitch_ledger.service import LedgerService
from stitch_ledger.store import RunStore

MARGIN_S = bench.BUDGET_S / 2


def test_bench_200x10_is_under_budget_with_margin() -> None:
    r = bench.run(seed=0, repeat=1)
    assert r["lp"]["status"] == "optimal"
    assert r["mip"]["status"] in ("optimal", "feasible")
    for key in ("lp", "mip", "sensitivity", "ranges", "sweep", "sweep_no_budget"):
        assert r[key]["wall_s"] < MARGIN_S, (key, r[key])
    assert r["sweep_no_budget"]["solves"] == 11
    assert r["ranges"]["skipped"] == 0


def test_instances_are_deterministic() -> None:
    assert random_spec(7, 30, 4) == random_spec(7, 30, 4)
    assert random_spec(7, 30, 4) != random_spec(8, 30, 4)


def test_tool_call_200x10_end_to_end_under_budget() -> None:
    spec = random_spec(1, 200, 10, equity_floor=0.5)
    args = {
        "scenario_id": "synthetic-bench",
        "districts": [
            {
                "district_id": d.district_id,
                "population_affected": int(d.population),
                "severity": d.severity,
                "road_access": d.road_access,
                "alt_delivery_fraction": d.alt_delivery_fraction,
                "unit_cost_multiplier": d.cost_multiplier,
            }
            for d in spec.districts
        ],
        "commodities": [
            {
                "id": c.commodity_id,
                "name": c.commodity_id,
                "unit": "unit",
                "unit_cost": c.unit_cost,
                "per_person_need": c.per_person_need,
            }
            for c in spec.commodities
        ],
        "supply": {c.commodity_id: c.supply for c in spec.commodities},
        "budget": spec.budget,
        "equity_floor": 0.5,
        "integer": True,
    }
    svc = LedgerService(store=RunStore(None))
    t0 = time.perf_counter()
    opt = asyncio.run(
        run_tool("ledger", "optimize_allocation", "t", svc.cores()["optimize_allocation"], args)
    )
    rep = asyncio.run(
        run_tool(
            "ledger", "sensitivity_report", "t", svc.cores()["sensitivity_report"],
            {"run_id": opt.provenance.run_id},
        )
    )  # fmt: skip
    elapsed = time.perf_counter() - t0
    assert opt.ok and rep.ok, (opt.error, rep.error)
    assert elapsed < bench.BUDGET_S, elapsed


def test_sockets_are_disabled_in_ledger_tests() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.5)
