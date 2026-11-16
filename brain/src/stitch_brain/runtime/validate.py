"""Validate organ payloads against the ``stitch_common`` contract models."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from stitch_common.envelope import ToolResult
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.organs.eyes import SceneInfo
from stitch_common.organs.ledger import ScenarioDistrict
from stitch_common.organs.oracle import StationInfo

RESOURCE_ITEMS: dict[str, type[Any]] = {
    "resource:districts": ScenarioDistrict,
    "resource:stations": StationInfo,
    "resource:scenes": SceneInfo,
}


class ContractViolation(ValueError):
    pass


def first_error(exc: ValidationError) -> str:
    e = exc.errors()[0]
    loc = ".".join(str(p) for p in e.get("loc", ())) or "<root>"
    return f"{loc}: {e.get('msg', 'invalid')}"


def validate_tool_result(organ: str, tool: str, payload: Any) -> dict[str, Any]:
    """Return the payload as plain JSON after validating it as ``ToolResult[Out]``."""
    if tool.startswith("resource:"):
        return validate_resource_result(tool, payload)
    spec = ORGAN_TOOLS.get(organ, {}).get(tool)
    if spec is None:
        raise ContractViolation(f"unknown tool {organ}.{tool}")
    try:
        model = ToolResult[spec.output].model_validate(payload)  # type: ignore[name-defined]
    except ValidationError as exc:
        raise ContractViolation(first_error(exc)) from exc
    if model.provenance.organ != organ or model.provenance.tool != tool:
        raise ContractViolation("provenance organ or tool does not match the call")
    out: dict[str, Any] = model.model_dump(mode="json")
    return out


def validate_resource_result(tool: str, payload: Any) -> dict[str, Any]:
    """Resource reads are wrapped by the Brain as ``{ok, data: {uri, items}, ...}``."""
    item = RESOURCE_ITEMS.get(tool)
    if item is None or not isinstance(payload, dict):
        raise ContractViolation(f"unknown resource {tool}")
    data = payload.get("data")
    if payload.get("ok"):
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ContractViolation("resource data must be {uri, items: [...]}")
        adapter: TypeAdapter[list[Any]] = TypeAdapter(list[item])  # type: ignore[valid-type]
        try:
            items = adapter.validate_python(data["items"])
        except ValidationError as exc:
            raise ContractViolation(first_error(exc)) from exc
        data = {**data, "items": adapter.dump_python(items, mode="json")}
    return {**payload, "data": data}


def validate_input(organ: str, tool: str, args: dict[str, Any]) -> None:
    """Contract check of the arguments the Brain sends (raises ``ContractViolation``)."""
    spec = ORGAN_TOOLS.get(organ, {}).get(tool)
    if spec is None:
        if tool.startswith("resource:"):
            return
        raise ContractViolation(f"unknown tool {organ}.{tool}")
    try:
        spec.input.model_validate(args)
    except ValidationError as exc:
        raise ContractViolation(first_error(exc)) from exc
