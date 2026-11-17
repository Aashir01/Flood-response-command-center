"""MCP server for eyes-mcp (contract v0.4, ``mcp-contracts.md`` sections 3 and 8b).

Thin layer: validation, the ``ToolResult`` envelope and ``GET /healthz`` come from
``stitch_common.mcp_app``; tool logic lives in ``stitch_eyes.service`` and ``stitch_eyes.core``.

    python -m stitch_eyes.server --stdio
    python -m stitch_eyes.server --http --host 127.0.0.1 --port 8000   # also serves GET /healthz

Environment: see ``stitch_eyes.settings``. With ``STITCH_EYES_WARM=1`` (default) the demo-scene
result is computed in a background thread at startup so the first call is fast.
"""

from __future__ import annotations

import json
import threading

from mcp.server.mcpserver.exceptions import ResourceError

from stitch_common.mcp_app import ContractServer, serve
from stitch_common.tooling import ToolFailure
from stitch_eyes.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_eyes.service import EyesService

TOOL_VERSION = "0.2.0"
SCENES_URI = "eyes://scenes"

DESCRIPTIONS = {
    "segment_flood": (
        "Segment surface water in the committed Sentinel-1 demo scene for a region and date "
        "(U-Net/ResNet-18, ONNX on CPU, order-independent tiled inference), remove JRC "
        "permanent water, and return the new-flood area (km2, from pixel counts in UTM 42N), "
        "simplified WGS84 polygons with confidence classes, mean confidence (null when no "
        "flood) and the validation labels. The Sindh demo scene is not a validated result: the "
        "model is validated on the Sen1Floods11 test split only. Dates: see eyes://scenes."
    ),
    "compare_with_permanent_water": (
        "Total detected water, its permanent part (JRC GSW) and the new flood (total minus "
        "permanent), with new flood by district (district ids from the shared boundaries file; "
        "only the part of each district inside the scene window)."
    ),
}

__all__ = ["SCENES_URI", "TOOL_NAMES", "TOOL_SCHEMAS", "TOOL_VERSION", "create_server", "main"]


def create_server(service: EyesService | None = None, warm: bool | None = None) -> ContractServer:
    svc = service if service is not None else EyesService()
    server = ContractServer(
        organ="eyes",
        tool_version=TOOL_VERSION,
        cores=svc.cores(),
        descriptions=DESCRIPTIONS,
        health_checks=svc.health,
    )

    @server.resource(
        SCENES_URI,
        name="scenes",
        description="Scenes available to the Eyes: region_id, date, scene_id, sensor and "
        "whether the model is validated for the region (false for the Sindh demo scene).",
        mime_type="application/json",
    )
    def scenes() -> str:
        try:
            rows = svc.scenes()
        except ToolFailure as f:
            raise ResourceError(f"{f.code}: {f.message}") from None
        return json.dumps([r.model_dump(mode="json") for r in rows], ensure_ascii=False)

    if svc.settings.warm if warm is None else warm:
        threading.Thread(target=svc.warm, name="eyes-warm", daemon=True).start()
    return server


def main(argv: list[str] | None = None) -> int:
    return serve(create_server(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
