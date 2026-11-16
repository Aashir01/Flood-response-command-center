"""Smoke test: start the server over stdio, list tools, call both, read the stations resource."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from stitch_common.envelope import ToolResult
from stitch_common.organs.oracle import StationInfo
from stitch_oracle.models import TOOL_NAMES

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "stitch_oracle.server", "--stdio"],
        env={"PYTHONPATH": SRC, "STITCH_MODE": "demo"},
    )


async def test_stdio_lists_tools_calls_both_and_reads_stations() -> None:
    async with Client(_params(), read_timeout_seconds=120) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        for t in listed.tools:
            text = (t.description or "").lower()
            assert "gauge" not in text and "observed" not in text
        res = await client.call_tool(
            "forecast_river",
            {"station_id": "indus-sukkur", "horizon_days": 7, "as_of": "2022-08-20"},
        )
        env = ToolResult[dict[str, object]].model_validate(res.structured_content)
        assert env.ok and env.data is not None
        assert env.data["target_kind"] == "modeled_glofas"
        assert env.provenance.organ == "oracle" and env.provenance.mode == "demo"
        res2 = await client.call_tool("explain_forecast", {"run_id": env.provenance.run_id})
        env2 = ToolResult[dict[str, object]].model_validate(res2.structured_content)
        assert env2.ok, env2.error
        resource = await client.read_resource("oracle://stations")
    contents = resource.contents[0]
    rows = json.loads(getattr(contents, "text", "[]"))
    assert {StationInfo.model_validate(r).station_id for r in rows} >= {"indus-sukkur"}
