"""Contract tests: tool schemas equal the exported contract (v0.4) and the shared
example payloads validate against them."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from stitch_common.organs import ORGAN_TOOLS
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_library.models import TOOL_NAMES, TOOL_SCHEMAS


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_tool_schema_equals_exported_input_schema(
    tool: str, load_schema: Callable[[str], dict[str, Any]]
) -> None:
    assert TOOL_SCHEMAS[tool] == load_schema(f"library.{tool}.in.json")


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_input_validates_against_tool_schema(tool: str) -> None:
    Draft202012Validator(TOOL_SCHEMAS[tool]).validate(TOOL_EXAMPLES[f"library.{tool}"][0])


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_output_validates_against_contract_model(tool: str) -> None:
    ORGAN_TOOLS["library"][tool].output.model_validate(TOOL_EXAMPLES[f"library.{tool}"][1])
