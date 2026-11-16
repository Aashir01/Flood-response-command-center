"""JSON Schema export. Inputs use validation mode, outputs use serialization mode.

File names: ``<organ>.<tool>.in.json`` / ``.out.json`` (the output file describes ``data``, not the
envelope), ``ledger.resource.districts.json`` for the resource item, and ``common.*.json`` /
``brain.*.json`` for shared models.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from stitch_common.brain import Briefing, TaskEvent
from stitch_common.envelope import ToolResult
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.organs.ledger import ScenarioDistrict
from stitch_common.provenance import Provenance
from stitch_common.types import Citation, EvidenceRef, Interval


def _schema(model: type[BaseModel], mode: str) -> dict[str, Any]:
    return model.model_json_schema(mode=mode)  # type: ignore[arg-type]


def all_schemas() -> dict[str, dict[str, Any]]:
    """Return ``{file_name: schema}`` for every contract schema, sorted by name."""
    out: dict[str, dict[str, Any]] = {}
    for organ, tools in ORGAN_TOOLS.items():
        for tool, spec in tools.items():
            out[f"{organ}.{tool}.in.json"] = _schema(spec.input, "validation")
            out[f"{organ}.{tool}.out.json"] = _schema(spec.output, "serialization")
    out["ledger.resource.districts.json"] = _schema(ScenarioDistrict, "serialization")
    out["common.tool_result.json"] = _schema(ToolResult[dict[str, Any]], "serialization")
    out["common.provenance.json"] = _schema(Provenance, "serialization")
    out["common.interval.json"] = _schema(Interval, "serialization")
    out["common.citation.json"] = _schema(Citation, "serialization")
    out["common.evidence_ref.json"] = _schema(EvidenceRef, "serialization")
    out["brain.briefing.json"] = _schema(Briefing, "serialization")
    out["brain.task_event.json"] = _schema(TaskEvent, "serialization")
    return dict(sorted(out.items()))


def dump_schema(schema: dict[str, Any]) -> str:
    """Stable text form written to disk (sorted keys, 2-space indent, LF, trailing newline)."""
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def schema_hash(schema: dict[str, Any]) -> str:
    """sha256 over canonical JSON, independent of line endings and indentation on disk."""
    canon = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
