"""Contract tests (v0.4): tool schemas equal the exported contract, the shared examples validate,
and real tool output (envelope, data, resource rows) validates against the exported JSON Schemas
(``additionalProperties: false``). Refs: EYE-R2.1, R3, R5.2, R6, EYE-X9."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from stitch_common.envelope import ToolResult
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_common.tooling import run_tool
from stitch_eyes.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_eyes.service import EyesService
from stitch_eyes.settings import Settings

Loader = Callable[[str], dict[str, Any]]

DEMO_ARGS = {
    "region_id": "pk-sindh",
    "date": "2022-08-27",
    "bbox": [67.62, 26.45, 67.70, 26.53],
    "mode": "demo",
}


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_tool_schema_equals_exported_input_schema(tool: str, load_schema: Loader) -> None:
    assert TOOL_SCHEMAS[tool] == load_schema(f"eyes.{tool}.in.json")


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_input_validates_against_tool_schema(tool: str) -> None:
    Draft202012Validator(TOOL_SCHEMAS[tool]).validate(TOOL_EXAMPLES[f"eyes.{tool}"][0])


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_output_validates_against_contract_model(tool: str) -> None:
    ORGAN_TOOLS["eyes"][tool].output.model_validate(TOOL_EXAMPLES[f"eyes.{tool}"][1])


def _run(svc: EyesService, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    res = asyncio.run(run_tool("eyes", tool, "test", svc.cores()[tool], args))
    payload: dict[str, Any] = json.loads(res.model_dump_json())
    return payload


def _envelope_schema(tool: str) -> dict[str, Any]:
    out = ORGAN_TOOLS["eyes"][tool].output
    schema: dict[str, Any] = ToolResult[out].model_json_schema(mode="serialization")  # type: ignore[valid-type]
    return schema


def _check(svc: EyesService, args: dict[str, Any], load_schema: Loader) -> None:
    for tool in TOOL_NAMES:
        r = _run(svc, tool, args)
        assert r["ok"], r["error"]
        Draft202012Validator(load_schema(f"eyes.{tool}.out.json")).validate(r["data"])
        Draft202012Validator(_envelope_schema(tool)).validate(r)
        prov = r["provenance"]
        assert prov["organ"] == "eyes" and prov["mode"] == "demo"
        assert prov["model"] is not None and len(prov["model"]["sha256"]) == 64


def test_synthetic_outputs_validate(synthetic_settings: Settings, load_schema: Loader) -> None:
    svc = EyesService(synthetic_settings)
    _check(svc, {"region_id": "pk-test", "date": "2022-08-27"}, load_schema)


def test_demo_scene_outputs_validate(real_service: EyesService, load_schema: Loader) -> None:
    """The shipped ONNX model on a window of the committed Sindh scene."""
    _check(real_service, DEMO_ARGS, load_schema)
    seg = _run(real_service, "segment_flood", DEMO_ARGS)["data"]
    assert seg["model_variant"].startswith("unet-resnet18-s1-")
    assert seg["validation"]["validated_for_region"] is False
    assert seg["validation"]["eval_dataset"] == "sen1floods11_test"


def test_failure_envelope_validates(real_service: EyesService) -> None:
    bad = _run(real_service, "segment_flood", {"region_id": "pk-sindh", "date": "2010-01-01"})
    assert not bad["ok"] and bad["error"]["code"] == "NOT_FOUND"
    Draft202012Validator(_envelope_schema("segment_flood")).validate(bad)


def test_resource_rows_validate(real_service: EyesService, load_schema: Loader) -> None:
    validator = Draft202012Validator(load_schema("eyes.resource.scenes.json"))
    rows = [json.loads(r.model_dump_json()) for r in real_service.scenes()]
    assert rows and rows[0]["region_id"] == "pk-sindh"
    for row in rows:
        validator.validate(row)
