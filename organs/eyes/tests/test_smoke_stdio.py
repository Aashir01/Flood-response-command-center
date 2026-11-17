"""Smoke tests: start the server over stdio, list tools and resources, call both tools on the
committed demo scene, read ``eyes://scenes``; and serve ``GET /healthz`` from the HTTP app.
Refs: EYE-R2.1, R3.1, R6.1, R8.1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from starlette.testclient import TestClient

from stitch_common import CONTRACT_VERSION
from stitch_common.envelope import ToolResult
from stitch_eyes.models import TOOL_NAMES
from stitch_eyes.server import SCENES_URI, create_server
from stitch_eyes.service import EyesService

SRC = str(Path(__file__).resolve().parents[1] / "src")
ARGS = {"region_id": "pk-sindh", "date": "2022-08-27", "bbox": [67.62, 26.45, 67.70, 26.53]}


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "stitch_eyes.server", "--stdio"],
        env={"PYTHONPATH": SRC, "STITCH_MODE": "demo", "STITCH_EYES_WARM": "0"},
    )


async def test_stdio_tools_resource_and_both_calls() -> None:
    async with Client(_params(), read_timeout_seconds=180) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        resources = await client.list_resources()
        assert [str(r.uri) for r in resources.resources] == [SCENES_URI]
        res = await client.read_resource(SCENES_URI)
        rows = json.loads(res.contents[0].text)  # type: ignore[union-attr]
        assert rows[0]["region_id"] == "pk-sindh" and rows[0]["validated_for_region"] is False
        for tool in TOOL_NAMES:
            out = await client.call_tool(tool, ARGS)
            assert not out.is_error
            env = ToolResult[dict[str, object]].model_validate(out.structured_content)
            assert env.ok, env.error
            assert env.provenance.organ == "eyes" and env.provenance.tool == tool
            assert env.provenance.mode == "demo" and env.provenance.model is not None


def test_healthz_reports_checks(real_service: EyesService) -> None:
    server = create_server(real_service, warm=False)
    r = TestClient(server.streamable_http_app()).get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["organ"] == "eyes"
    assert body["checks"] == {"model": True, "catalog": True, "boundaries": True}
    assert body["contract_version"] == CONTRACT_VERSION
