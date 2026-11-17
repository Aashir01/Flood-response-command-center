"""Contract tests (v0.4): tool schemas equal the exported contract, the shared examples validate,
and real tool output (envelope, data, failure envelopes, resource rows) validates against the
exported JSON Schemas, which use ``additionalProperties: false``. Refs: ORA-R4, R6.2, R8, P8."""

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
from stitch_oracle.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_oracle.service import OracleService
from stitch_oracle.store import RunStore

Loader = Callable[[str], dict[str, Any]]


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_tool_schema_equals_exported_input_schema(tool: str, load_schema: Loader) -> None:
    assert TOOL_SCHEMAS[tool] == load_schema(f"oracle.{tool}.in.json")


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_input_validates_against_tool_schema(tool: str) -> None:
    Draft202012Validator(TOOL_SCHEMAS[tool]).validate(TOOL_EXAMPLES[f"oracle.{tool}"][0])


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_output_validates_against_contract_model(tool: str) -> None:
    ORGAN_TOOLS["oracle"][tool].output.model_validate(TOOL_EXAMPLES[f"oracle.{tool}"][1])


@pytest.fixture(scope="module")
def svc() -> OracleService:
    return OracleService(store=RunStore())


def _run(svc: OracleService, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    res = asyncio.run(run_tool("oracle", tool, "test", svc.cores()[tool], args))
    payload: dict[str, Any] = json.loads(res.model_dump_json())
    return payload


def _envelope_schema(tool: str) -> dict[str, Any]:
    out = ORGAN_TOOLS["oracle"][tool].output
    schema: dict[str, Any] = ToolResult[out].model_json_schema(mode="serialization")  # type: ignore[valid-type]
    return schema


@pytest.mark.parametrize(
    "args",
    [
        {"station_id": "indus-sukkur", "horizon_days": 14, "as_of": "2022-08-20"},
        {"station_id": "indus-kotri", "horizon_days": 1, "as_of": "2017-01-01", "coverage": 0.5},
        {"station_id": "chenab-trimmu", "horizon_days": 7, "coverage": 0.99, "mode": "demo"},
        {"station_id": "indus-guddu", "horizon_days": 5, "as_of": "2022-07-01", "mode": "live"},
    ],
)
def test_real_outputs_validate(
    svc: OracleService, args: dict[str, Any], load_schema: Loader
) -> None:
    fc = _run(svc, "forecast_river", args)
    assert fc["ok"], fc["error"]
    assert fc["data"]["target_kind"] == "modeled_glofas"
    Draft202012Validator(load_schema("oracle.forecast_river.out.json")).validate(fc["data"])
    Draft202012Validator(_envelope_schema("forecast_river")).validate(fc)
    ex = _run(svc, "explain_forecast", {"run_id": fc["provenance"]["run_id"]})
    assert ex["ok"], ex["error"]
    Draft202012Validator(load_schema("oracle.explain_forecast.out.json")).validate(ex["data"])
    Draft202012Validator(_envelope_schema("explain_forecast")).validate(ex)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("forecast_river", {"station_id": "nowhere", "horizon_days": 3}),
        ("forecast_river", {"station_id": "indus-sukkur", "horizon_days": 30}),
        ("explain_forecast", {"run_id": "missing"}),
    ],
)
def test_failure_envelopes_validate(svc: OracleService, tool: str, args: dict[str, Any]) -> None:
    bad = _run(svc, tool, args)
    assert not bad["ok"] and bad["data"] is None
    Draft202012Validator(_envelope_schema(tool)).validate(bad)
    assert bad["provenance"]["organ"] == "oracle"


def test_resource_rows_validate(svc: OracleService, load_schema: Loader) -> None:
    validator = Draft202012Validator(load_schema("oracle.resource.stations.json"))
    rows = svc.stations()
    assert rows
    for row in rows:  # the schema describes one item of the resource list
        validator.validate(json.loads(row.model_dump_json()))
