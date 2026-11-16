"""Contract tests (v0.4): tool schemas equal the exported contract, the shared examples validate,
and real tool output (envelope, data, resource rows) validates against the exported JSON Schemas,
which use ``additionalProperties: false``."""

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
from stitch_ledger.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_ledger.service import LedgerService
from stitch_ledger.store import RunStore

Loader = Callable[[str], dict[str, Any]]


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_tool_schema_equals_exported_input_schema(tool: str, load_schema: Loader) -> None:
    assert TOOL_SCHEMAS[tool] == load_schema(f"ledger.{tool}.in.json")


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_input_validates_against_tool_schema(tool: str) -> None:
    Draft202012Validator(TOOL_SCHEMAS[tool]).validate(TOOL_EXAMPLES[f"ledger.{tool}"][0])


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_output_validates_against_contract_model(tool: str) -> None:
    ORGAN_TOOLS["ledger"][tool].output.model_validate(TOOL_EXAMPLES[f"ledger.{tool}"][1])


def _run(svc: LedgerService, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    res = asyncio.run(run_tool("ledger", tool, "test", svc.cores()[tool], args))
    payload: dict[str, Any] = json.loads(res.model_dump_json())
    return payload


def _envelope_schema(tool: str) -> dict[str, Any]:
    out = ORGAN_TOOLS["ledger"][tool].output
    schema: dict[str, Any] = ToolResult[out].model_json_schema(mode="serialization")  # type: ignore[valid-type]
    return schema


@pytest.mark.parametrize("integer", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_real_outputs_validate(override: bool, integer: bool, load_schema: Loader) -> None:
    svc = LedgerService(store=RunStore(None))
    if override:
        args = dict(TOOL_EXAMPLES["ledger.optimize_allocation"][0], integer=integer)
    else:
        args = {
            "scenario_id": "demo-sindh-2022",
            "commodities": [
                {
                    "id": "food",
                    "name": "Food",
                    "unit": "pack",
                    "unit_cost": 12.0,
                    "per_person_need": 1.0,
                },
            ],
            "supply": {"food": 1_500_000.0},
            "budget": 10_000_000.0,
            "equity_floor": 0.4,
            "integer": integer,
            "mode": "demo",
        }
    opt = _run(svc, "optimize_allocation", args)
    assert opt["ok"], opt["error"]
    Draft202012Validator(load_schema("ledger.optimize_allocation.out.json")).validate(opt["data"])
    Draft202012Validator(_envelope_schema("optimize_allocation")).validate(opt)

    rep = _run(svc, "sensitivity_report", {"run_id": opt["provenance"]["run_id"]})
    assert rep["ok"], rep["error"]
    Draft202012Validator(load_schema("ledger.sensitivity_report.out.json")).validate(rep["data"])
    Draft202012Validator(_envelope_schema("sensitivity_report")).validate(rep)


def test_failure_envelope_validates() -> None:
    svc = LedgerService(store=RunStore(None))
    bad = _run(svc, "sensitivity_report", {"run_id": "missing"})
    assert not bad["ok"] and bad["error"]["code"] == "NOT_FOUND"
    Draft202012Validator(_envelope_schema("sensitivity_report")).validate(bad)


def test_resource_rows_validate(load_schema: Loader) -> None:
    validator = Draft202012Validator(load_schema("ledger.resource.districts.json"))
    rows = LedgerService(store=RunStore(None)).scenario_districts("demo-sindh-2022")
    for row in rows:
        validator.validate(json.loads(row.model_dump_json()))
