"""Tool-level tests of ledger-mcp through ``run_tool`` (envelope, error mapping, provenance, mode,
run store). Refs: LED-R2.4, R2.5, R8.1, R8.2; design section 6 error table."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stitch_common.envelope import ToolResult
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_common.tooling import run_tool
from stitch_ledger import service as service_mod
from stitch_ledger.core.solve import SolverError, SolverTimeout
from stitch_ledger.models import TOOL_NAMES
from stitch_ledger.service import MODE_FALLBACK_WARNING, LedgerService
from stitch_ledger.store import RunStore

DEMO = "demo-sindh-2022"
COMMODITIES = [
    {"id": "food", "name": "Food packs", "unit": "pack", "unit_cost": 12.0, "per_person_need": 1.0},
    {"id": "water", "name": "Water", "unit": "litre", "unit_cost": 0.1, "per_person_need": 15.0},
]


def demo_args(**extra: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "scenario_id": DEMO,
        "commodities": COMMODITIES,
        "supply": {"food": 2_000_000.0, "water": 30_000_000.0},
        "budget": 25_000_000.0,
        "equity_floor": 0.3,
        "integer": False,
    }
    args.update(extra)
    return args


@pytest.fixture
def svc() -> LedgerService:
    return LedgerService(store=RunStore(None))


def call(svc: LedgerService, tool: str, args: dict[str, Any]) -> ToolResult[Any]:
    return asyncio.run(run_tool("ledger", tool, "test", svc.cores()[tool], args))


def test_cores_cover_exactly_the_contract_tools(svc: LedgerService) -> None:
    assert sorted(svc.cores()) == sorted(TOOL_NAMES) == sorted(ORGAN_TOOLS["ledger"])


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_invalid_input_is_reported_not_raised(svc: LedgerService, tool: str) -> None:
    result = call(svc, tool, {"unexpected": 1})
    assert result.error is not None and result.error.code == "INVALID_INPUT"


def test_demo_dataset_run_has_provenance_and_demo_mode(svc: LedgerService) -> None:
    r = call(svc, "optimize_allocation", demo_args())
    assert r.ok and r.data is not None
    assert r.data.status == "optimal"
    assert len(r.data.coverage) == 22
    p = r.provenance
    assert p.organ == "ledger" and p.mode == "demo"
    assert {s.id for s in p.data_sources}  # WorldPop, OSM, geoBoundaries
    assert p.model is not None and "GLOP" in p.model.name
    assert any("demo scenario data" in w for w in r.warnings)


def test_override_districts_skip_dataset(svc: LedgerService) -> None:
    r = call(svc, "optimize_allocation", TOOL_EXAMPLES["ledger.optimize_allocation"][0])
    assert r.ok and r.data is not None
    assert [c.district_id for c in r.data.coverage] == ["d1"]
    assert r.provenance.data_sources == []
    assert any("supplied by the caller" in w for w in r.warnings)


def test_unknown_scenario_is_not_found(svc: LedgerService) -> None:
    r = call(svc, "optimize_allocation", demo_args(scenario_id="nowhere"))
    assert r.error is not None and r.error.code == "NOT_FOUND" and not r.error.retryable


def test_size_cap_is_invalid_input(svc: LedgerService) -> None:
    many = [
        {"district_id": f"d{i}", "population_affected": 10, "severity": 0.5, "road_access": 1.0}
        for i in range(501)
    ]
    r = call(svc, "optimize_allocation", demo_args(districts=many))
    assert r.error is not None and r.error.code == "INVALID_INPUT"


def test_missing_supply_entry_is_zero_with_warning(svc: LedgerService) -> None:
    r = call(svc, "optimize_allocation", demo_args(supply={"food": 1000.0}, equity_floor=None))
    assert r.ok and r.data is not None
    assert any("no supply given for water" in w for w in r.warnings)
    assert all(a.quantity == 0 for a in r.data.allocation if a.commodity_id == "water")


def test_live_request_on_dataset_falls_back_to_demo(
    svc: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STITCH_MODE", "live")
    r = call(svc, "optimize_allocation", demo_args(mode="live"))
    assert r.ok and r.provenance.mode == "demo"
    assert r.warnings[0] == MODE_FALLBACK_WARNING


def test_override_districts_carry_requested_mode(svc: LedgerService) -> None:
    args = dict(TOOL_EXAMPLES["ledger.optimize_allocation"][0], mode="live")
    r = call(svc, "optimize_allocation", args)
    assert r.ok and r.provenance.mode == "live"
    assert MODE_FALLBACK_WARNING not in r.warnings


def test_sensitivity_uses_the_optimize_run_id(svc: LedgerService) -> None:
    first = call(svc, "optimize_allocation", demo_args())
    assert first.ok
    rep = call(svc, "sensitivity_report", {"run_id": first.provenance.run_id, "floor_steps": 5})
    assert rep.ok and rep.data is not None
    assert rep.data.basis == "lp_relaxation"
    assert rep.data.shadow_prices and rep.data.equity_tradeoff
    assert rep.provenance.mode == "demo"


def test_sensitivity_unknown_run_is_not_found(svc: LedgerService) -> None:
    r = call(svc, "sensitivity_report", {"run_id": "no-such-run"})
    assert r.error is not None and r.error.code == "NOT_FOUND"


def test_floor_above_max_with_error_policy(svc: LedgerService) -> None:
    args = demo_args(budget=1000.0, equity_floor=1.0, on_infeasible_floor="error")
    r = call(svc, "optimize_allocation", args)
    assert r.ok and r.data is not None
    assert r.data.status == "infeasible" and r.data.infeasibility_reason
    rep = call(svc, "sensitivity_report", {"run_id": r.provenance.run_id})
    assert rep.error is not None and rep.error.code == "INFEASIBLE"


def test_floor_above_max_relaxes_by_default(svc: LedgerService) -> None:
    r = call(svc, "optimize_allocation", demo_args(budget=1000.0, equity_floor=1.0))
    assert r.ok and r.data is not None
    assert r.data.equity.floor_applied < r.data.equity.floor_requested
    assert r.data.equity.floor_applied == pytest.approx(r.data.equity.max_feasible_floor)


def test_timeout_maps_to_retryable_timeout(
    svc: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_spec: object) -> object:
        raise SolverTimeout("no feasible solution within 1 s")

    monkeypatch.setattr(service_mod, "optimize", boom)
    r = call(svc, "optimize_allocation", demo_args())
    assert r.error is not None and r.error.code == "TIMEOUT" and r.error.retryable


def test_solver_error_maps_to_internal(svc: LedgerService, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_spec: object) -> object:
        raise SolverError("status ABNORMAL")

    monkeypatch.setattr(service_mod, "optimize", boom)
    r = call(svc, "optimize_allocation", demo_args())
    assert r.error is not None and r.error.code == "INTERNAL" and not r.error.retryable
    assert "ABNORMAL" not in r.error.message


def test_scenario_districts_resource_rows(svc: LedgerService) -> None:
    rows = svc.scenario_districts(DEMO)
    assert len(rows) == 22 and rows[0].district_id.startswith("pk-sindh-")


def test_health_checks_all_pass(svc: LedgerService) -> None:
    assert svc.health() == {"solver": True, "dataset": True, "store": True}


def test_zero_coverage_reports_zero_cost_with_warning(svc: LedgerService) -> None:
    r = call(svc, "optimize_allocation", demo_args(supply={}, equity_floor=None, budget=None))
    assert r.ok and r.data is not None
    assert r.data.cost_benefit.people_covered == 0
    assert r.data.cost_benefit.cost_per_person_covered == 0
    assert any("do not read it as a cost" in w for w in r.warnings)
