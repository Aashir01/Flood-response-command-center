"""Unit tests for library-mcp. Replace the stub tests as each core is implemented."""

from __future__ import annotations

import asyncio

import pytest

from stitch_common.envelope import ToolResult
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_common.tooling import run_tool
from stitch_library.core import CORES
from stitch_library.models import TOOL_NAMES


def test_cores_cover_exactly_the_contract_tools() -> None:
    assert sorted(CORES) == sorted(TOOL_NAMES)


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_stub_reports_not_implemented(tool: str) -> None:
    # Delete this test for a tool once its core is implemented.
    args = TOOL_EXAMPLES[f"library.{tool}"][0]
    result = asyncio.run(run_tool("library", tool, "0.1.0", CORES[tool], args))
    assert isinstance(result, ToolResult)
    assert not result.ok
    assert result.error is not None and result.error.code == "INTERNAL"
    assert result.provenance.organ == "library" and result.provenance.tool == tool


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_invalid_input_is_reported_not_raised(tool: str) -> None:
    result = asyncio.run(run_tool("library", tool, "0.1.0", CORES[tool], {"unexpected": 1}))
    assert result.error is not None and result.error.code == "INVALID_INPUT"
