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


REAL_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("search_guidance", {"query": "How much water per person per day?", "top_k": 3}),
    ("search_guidance", {"query": "پینے کا پانی", "lang": "ur", "filters": {"lang": ["ur"]}}),
    ("answer_with_citations", {"query": "How much water per person per day?"}),
    ("answer_with_citations", {"query": "How much water per person per day?", "answer_lang": "ur"}),
    ("answer_with_citations", {"query": "Who won the cricket world cup in 1992?"}),
    ("answer_with_citations", {"query": "What food ration should displaced families receive?"}),
]


@pytest.mark.parametrize(("tool", "args"), REAL_CALLS)
def test_real_tool_output_validates_against_exported_output_schema(
    tool: str, args: dict[str, Any], load_schema: Callable[[str], dict[str, Any]]
) -> None:
    """Real outputs (answered and refused) of the committed pack validate against the exported
    output JSON Schema, which carries ``additionalProperties: false``."""
    import asyncio

    from stitch_common.tooling import run_tool
    from stitch_library.core import CORES

    env = asyncio.run(run_tool("library", tool, "test", CORES[tool], args))
    dumped = env.model_dump(mode="json")
    assert dumped["ok"], dumped["error"]
    Draft202012Validator(load_schema(f"library.{tool}.out.json")).validate(dumped["data"])
