"""Brain drives the real Ledger over stdio under ``no_network`` (pipes only). Task 8/29."""

from __future__ import annotations

import importlib.util
import sys

import pytest

from stitch_brain.config import OrganEndpoint, load_scenarios
from stitch_brain.core.plans import ledger_fallback_args
from stitch_brain.runtime.mcp_client import McpOrganClient
from stitch_brain.runtime.organs import CallContext

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        importlib.util.find_spec("stitch_ledger") is None, reason="ledger organ not installed"
    ),
]

EP = OrganEndpoint(
    transport="stdio", command=[sys.executable, "-m", "stitch_ledger.server", "--stdio"]
)


async def test_real_ledger_lists_tools_and_answers_both_tools() -> None:
    c = McpOrganClient("ledger", EP)
    await c.start()
    try:
        if not await c.wait_connected(90):
            pytest.skip(f"ledger server did not start: {c.health().last_error}")
        assert c.health().compat == "compatible", c.health().reason
        assert {"optimize_allocation", "sensitivity_report"} <= set(await c.list_tools())
        args = ledger_fallback_args(load_scenarios()["demo-sindh-2022"], "demo")
        ctx = CallContext("b", "ledger.optimize", 1, "demo-sindh-2022")
        out = await c.call_tool("optimize_allocation", args, timeout_s=120, ctx=ctx)
        assert out.result is not None, out.transport_error
        assert out.result["ok"] and out.result["data"]["status"] in ("optimal", "feasible")
        run_id = out.result["provenance"]["run_id"]
        sens = await c.call_tool("sensitivity_report", {"run_id": run_id}, timeout_s=120, ctx=ctx)
        assert sens.result is not None and sens.result["ok"], sens
    finally:
        await c.close()
