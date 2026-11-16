"""MCP server for ledger-mcp. Thin layer: validation, envelope and /healthz come from
``stitch_common.mcp_app``; the logic lives in ``stitch_ledger.core``.

    python -m stitch_ledger.server --stdio
    python -m stitch_ledger.server --http --host 127.0.0.1 --port 8000   # also serves GET /healthz
"""

from __future__ import annotations

from stitch_common.mcp_app import ContractServer, serve
from stitch_ledger.core import CORES
from stitch_ledger.models import TOOL_NAMES, TOOL_SCHEMAS

TOOL_VERSION = "0.1.0"

__all__ = ["TOOL_NAMES", "TOOL_SCHEMAS", "TOOL_VERSION", "create_server", "main"]


def create_server() -> ContractServer:
    return ContractServer(organ="ledger", tool_version=TOOL_VERSION, cores=CORES)


def main(argv: list[str] | None = None) -> int:
    return serve(create_server(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
