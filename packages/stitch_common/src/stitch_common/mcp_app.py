"""MCP server base for organs (needs the ``mcp`` extra: ``stitch-common[mcp]``).

Built on the MCP Python SDK v2 ``MCPServer`` (renamed from v1 ``FastMCP``). The tool list and the
tool call are overridden so that:

* each tool advertises exactly the contract input schema (``TOOL_SCHEMAS``), not a schema
  derived from a Python signature;
* every call returns a ``ToolResult`` envelope as ``structured_content`` (domain failures are
  envelopes with ``ok=false``, not protocol errors);
* ``GET /healthz`` is served next to the MCP endpoint when running over HTTP.

Run an organ with ``python -m stitch_<organ>.server [--stdio | --http --host H --port P]``.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, Tool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from stitch_common import CONTRACT_VERSION
from stitch_common.envelope import ToolResult
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.tooling import current_mode, organ_cores, run_tool
from stitch_common.types import OrganName


class ContractServer(MCPServer):
    """MCP server whose tools are the contract tools of one organ."""

    def __init__(
        self,
        organ: OrganName,
        tool_version: str,
        cores: Mapping[str, Callable[[Any], Any]],
        descriptions: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            name=f"{organ}-mcp",
            version=tool_version,
            instructions=f"Stitch {organ} organ. Every tool returns a ToolResult envelope.",
        )
        self.organ: OrganName = organ
        self.tool_version = tool_version
        self._cores = organ_cores(organ, cores)
        self._descriptions = dict(descriptions or {})

        @self.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
        async def healthz(request: Request) -> Response:
            return JSONResponse(
                {
                    "status": "ok",
                    "organ": organ,
                    "tool_version": tool_version,
                    "contract_version": CONTRACT_VERSION,
                    "mode": current_mode(),
                    "tools": sorted(self._cores),
                }
            )

    async def list_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for name in sorted(self._cores):
            spec = ORGAN_TOOLS[self.organ][name]
            envelope = ToolResult[spec.output]  # type: ignore[name-defined]
            tools.append(
                Tool(
                    name=name,
                    description=self._descriptions.get(name, f"{self.organ}.{name}"),
                    input_schema=spec.input.model_json_schema(mode="validation"),
                    output_schema=envelope.model_json_schema(mode="serialization"),
                )
            )
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult:
        core = self._cores.get(name)
        if core is None:
            raise ToolError(f"Unknown tool: {name}")
        result = await run_tool(self.organ, name, self.tool_version, core, arguments)
        payload = result.model_dump(mode="json")
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structured_content=payload,
            is_error=False,
        )


def serve(server: ContractServer, argv: list[str] | None = None) -> int:
    """Command line entry: ``--stdio`` (default) or ``--http [--host H] [--port P]``."""
    parser = argparse.ArgumentParser(prog=f"stitch_{server.organ}.server")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stdio", action="store_true", help="serve over stdio (default)")
    group.add_argument("--http", action="store_true", help="serve streamable HTTP + /healthz")
    parser.add_argument("--host", default=os.environ.get("STITCH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STITCH_PORT", "8000")))
    args = parser.parse_args(argv)
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")
    return 0
