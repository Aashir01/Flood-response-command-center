"""Additive helpers used by the Ledger: ``Outcome.run_id`` and ``ContractServer`` health checks."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from starlette.testclient import TestClient

from stitch_common.mcp_app import ContractServer
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_common.tooling import Outcome, run_tool


def _example_out(tool: str) -> object:
    from stitch_common.organs import ORGAN_TOOLS

    return ORGAN_TOOLS["ledger"][tool].output.model_validate(TOOL_EXAMPLES[f"ledger.{tool}"][1])


def test_outcome_run_id_becomes_the_provenance_run_id() -> None:
    chosen = str(uuid.uuid4())
    args = TOOL_EXAMPLES["ledger.sensitivity_report"][0]
    result = asyncio.run(
        run_tool(
            "ledger",
            "sensitivity_report",
            "t",
            lambda _p: Outcome(_example_out("sensitivity_report"), run_id=chosen),
            args,
        )
    )
    assert result.ok and result.provenance.run_id == chosen


def test_default_run_id_is_fresh() -> None:
    args = TOOL_EXAMPLES["ledger.sensitivity_report"][0]

    def core(_p: object) -> object:
        return _example_out("sensitivity_report")

    a = asyncio.run(run_tool("ledger", "sensitivity_report", "t", core, args))
    b = asyncio.run(run_tool("ledger", "sensitivity_report", "t", core, args))
    assert a.provenance.run_id != b.provenance.run_id


def _client(checks: dict[str, bool] | None) -> TestClient:
    cores = {"optimize_allocation": lambda p: p, "sensitivity_report": lambda p: p}
    server = ContractServer(
        "ledger", "t", cores, health_checks=(lambda: checks) if checks is not None else None
    )
    return TestClient(server.streamable_http_app())


def test_healthz_without_checks_is_unchanged() -> None:
    r = _client(None).get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok" and "checks" not in r.json()


def test_healthz_reports_checks_and_degrades_with_503() -> None:
    ok = _client({"solver": True, "store": True}).get("/healthz")
    assert ok.status_code == 200 and ok.json()["checks"] == {"solver": True, "store": True}
    bad = _client({"solver": True, "store": False}).get("/healthz")
    assert bad.status_code == 503 and bad.json()["status"] == "degraded"


def test_outcome_mode_overrides_the_env_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STITCH_MODE", "live")
    args = TOOL_EXAMPLES["ledger.sensitivity_report"][0]
    fixed = asyncio.run(
        run_tool(
            "ledger",
            "sensitivity_report",
            "t",
            lambda _p: Outcome(_example_out("sensitivity_report"), mode="demo"),
            args,
        )
    )
    default = asyncio.run(
        run_tool(
            "ledger", "sensitivity_report", "t", lambda _p: _example_out("sensitivity_report"), args
        )
    )
    assert fixed.provenance.mode == "demo" and default.provenance.mode == "live"
