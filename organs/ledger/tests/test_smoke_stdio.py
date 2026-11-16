"""Smoke tests: start the server over stdio, list tools and resources, call both tools, read the
districts resource; and serve ``GET /healthz`` from the HTTP app. Refs: LED-R2.4, R8.1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from starlette.testclient import TestClient

from stitch_common.envelope import ToolResult
from stitch_ledger.models import TOOL_NAMES
from stitch_ledger.server import create_server
from stitch_ledger.service import LedgerService
from stitch_ledger.store import RunStore

SRC = str(Path(__file__).resolve().parents[1] / "src")

ARGS = {
    "scenario_id": "demo-sindh-2022",
    "commodities": [
        {"id": "food", "name": "Food", "unit": "pack", "unit_cost": 12.0, "per_person_need": 1.0}
    ],
    "supply": {"food": 1_000_000.0},
    "equity_floor": 0.2,
}


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "stitch_ledger.server", "--stdio"],
        env={"PYTHONPATH": SRC, "STITCH_MODE": "demo"},
    )


async def test_stdio_tools_resource_and_both_calls() -> None:
    async with Client(_params(), read_timeout_seconds=90) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        templates = await client.list_resource_templates()
        assert [t.uri_template for t in templates.resource_templates] == [
            "ledger://scenario/{scenario_id}/districts"
        ]
        opt = await client.call_tool("optimize_allocation", ARGS)
        env = ToolResult[dict[str, object]].model_validate(opt.structured_content)
        assert env.ok and env.provenance.organ == "ledger" and env.provenance.mode == "demo"
        rep = await client.call_tool(
            "sensitivity_report", {"run_id": env.provenance.run_id, "floor_steps": 3}
        )
        rep_env = ToolResult[dict[str, object]].model_validate(rep.structured_content)
        assert rep_env.ok and rep_env.data is not None
        assert rep_env.data["basis"] == "lp_relaxation"
        res = await client.read_resource("ledger://scenario/demo-sindh-2022/districts")
        rows = json.loads(res.contents[0].text)  # type: ignore[union-attr]
        assert len(rows) == 22


def test_healthz_reports_checks() -> None:
    server = create_server(LedgerService(store=RunStore(None)))
    r = TestClient(server.streamable_http_app()).get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["organ"] == "ledger"
    assert body["checks"] == {"solver": True, "dataset": True, "store": True}
    assert body["contract_version"] == "0.4"
