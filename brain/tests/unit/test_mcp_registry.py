"""MCP client, compatibility, health states, backoff, registry startup (task 8; BRN-R1)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from stitch_brain.config import OrganEndpoint, OrgansCfg
from stitch_brain.runtime.clock import VirtualClock
from stitch_brain.runtime.mcp_client import McpOrganClient, compat_problems
from stitch_brain.runtime.organs import CallContext, health_status
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.settings import Settings
from stitch_common.mcp_app import ContractServer
from stitch_common.testing.examples import TOOL_EXAMPLES

CTX = CallContext("b", "ledger.optimize", 1, "demo-sindh-2022")
EP = OrganEndpoint(transport="stdio", command=["none"])


def _ledger_server(delay: float = 0.0) -> ContractServer:
    async def optimize(params: Any) -> Any:
        if delay:
            await asyncio.sleep(delay)
        return TOOL_EXAMPLES["ledger.optimize_allocation"][1]

    def sensitivity(params: Any) -> Any:
        return TOOL_EXAMPLES["ledger.sensitivity_report"][1]

    return ContractServer(
        "ledger", "0.0.1", {"optimize_allocation": optimize, "sensitivity_report": sensitivity}
    )


def _client(server: Any, **kw: Any) -> McpOrganClient:
    return McpOrganClient("ledger", EP, connector=lambda: Client(server, cache=None), **kw)


async def test_compatible_in_process_server_answers_through_the_client() -> None:
    c = _client(_ledger_server())
    await c.start()
    try:
        assert await c.wait_connected(10)
        assert await c.list_tools() == ["optimize_allocation", "sensitivity_report"]
        args = TOOL_EXAMPLES["ledger.optimize_allocation"][0]
        out = await c.call_tool("optimize_allocation", args, timeout_s=10, ctx=CTX)
        assert out.result is not None and out.result["ok"], out
        assert c.health().status == "ready" and c.health().compat == "compatible"
    finally:
        await c.close()


async def test_incompatible_server_is_never_called() -> None:
    srv = MCPServer(name="ledger-mcp")

    @srv.tool()
    def optimize_allocation(scenario_id: int) -> str:  # wrong schema, missing tool
        return "x"

    c = _client(srv)
    await c.start()
    try:
        assert await c.wait_connected(10)
        h = c.health()
        assert h.compat == "incompatible" and h.status == "unwell"
        out = await c.call_tool("optimize_allocation", {}, timeout_s=5, ctx=CTX)
        assert out.transport_error is not None and out.transport_error.code == "UNAVAILABLE"
    finally:
        await c.close()


async def test_slow_server_times_out() -> None:
    c = _client(_ledger_server(delay=5))
    await c.start()
    try:
        assert await c.wait_connected(10)
        args = TOOL_EXAMPLES["ledger.optimize_allocation"][0]
        out = await c.call_tool("optimize_allocation", args, timeout_s=0.2, ctx=CTX)
        assert out.transport_error is not None
        assert out.transport_error.code in ("TIMEOUT", "PROTOCOL")
    finally:
        await c.close()


async def test_flapping_connector_backs_off_in_virtual_time() -> None:
    clock = VirtualClock()
    attempts = {"n": 0}
    server = _ledger_server()

    def connector() -> Any:
        attempts["n"] += 1
        if attempts["n"] <= 4:
            raise ConnectionError("down")
        return Client(server, cache=None)

    c = McpOrganClient("ledger", EP, clock=clock, connector=connector, seed=1)
    async with clock.autojump():
        await c.start()
        assert c.health().status == "unwell"  # startup did not block
        assert await c.wait_connected(120)
    await c.close()
    assert len(c.backoffs) >= 4
    assert all(1.0 <= b / s <= 1.2 for b, s in zip(c.backoffs, [1, 2, 4, 8], strict=False))


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"disabled": True, "connected": True, "compat": "compatible", "failures": 0}, "disabled"),
        ({"disabled": False, "connected": False, "compat": "unknown", "failures": 0}, "unwell"),
        ({"disabled": False, "connected": True, "compat": "incompatible", "failures": 0}, "unwell"),
        ({"disabled": False, "connected": True, "compat": "compatible", "failures": 3}, "unwell"),
        ({"disabled": False, "connected": True, "compat": "compatible", "failures": 2}, "degraded"),
        ({"disabled": False, "connected": True, "compat": "compatible", "failures": 0}, "ready"),
    ],
)
def test_health_state_table(kw: dict[str, Any], expected: str) -> None:
    assert health_status(healthz_degraded=False, **kw) == expected


def test_compat_problems_lists_missing_tools() -> None:
    assert "missing tool sensitivity_report" in compat_problems("ledger", {})


async def test_registry_starts_with_every_organ_unreachable() -> None:
    cfg = OrgansCfg(
        organs={
            o: OrganEndpoint(command=["definitely-not-a-command-xyz"])
            for o in ("eyes", "oracle", "library", "ledger", "voice")
        }
    )
    reg = OrganRegistry.build(Settings(disabled_organs=("voice",)), cfg)
    await asyncio.wait_for(reg.start(), 2)
    try:
        h = reg.health()
        assert h["voice"].status == "disabled"
        assert all(h[o].status == "unwell" for o in ("eyes", "oracle", "library", "ledger"))
    finally:
        await reg.close()


def test_registry_recorded_selection_is_explicit() -> None:
    reg = OrganRegistry.build(Settings(recorded_organs=("eyes", "oracle")), None)
    assert reg.stub_organs() == ["eyes", "oracle"]
    assert reg.health()["ledger"].status == "disabled"  # no endpoint configured, no failover
