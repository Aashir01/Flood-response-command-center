"""Models and published schemas for voice-mcp.

The contract models live in ``stitch_common.organs.voice``; do not copy them. Add models here
only for organ-internal data (they are not part of the MCP contract).

``TOOL_SCHEMAS`` maps each tool name to its input JSON Schema. ``scripts/check_contracts.py``
compares it with the exported schema ``packages/stitch_common/schemas/voice.<tool>.in.json``.
"""

from __future__ import annotations

from typing import Any

from stitch_common.organs import ORGAN_TOOLS

TOOL_NAMES: tuple[str, ...] = ("transcribe", "speak")

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    name: ORGAN_TOOLS["voice"][name].input.model_json_schema(mode="validation")
    for name in TOOL_NAMES
}
