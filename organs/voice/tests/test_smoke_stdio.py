"""Smoke test: start the server over stdio, list tools, call one, check the envelope."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from stitch_common.envelope import ToolResult
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_voice.models import TOOL_NAMES

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "stitch_voice.server", "--stdio"],
        env={"PYTHONPATH": SRC, "STITCH_MODE": "demo"},
    )


async def test_stdio_lists_tools_and_returns_an_envelope() -> None:
    async with Client(_params(), read_timeout_seconds=60) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        tool = TOOL_NAMES[0]
        res = await client.call_tool(tool, TOOL_EXAMPLES[f"voice.{tool}"][0])
    assert not res.is_error
    env = ToolResult[dict[str, object]].model_validate(res.structured_content)
    assert env.provenance.organ == "voice" and env.provenance.tool == tool
    assert env.ok == (env.data is not None and env.error is None)
