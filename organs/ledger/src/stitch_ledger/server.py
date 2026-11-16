"""MCP server for ledger-mcp (contract v0.4, ``mcp-contracts.md`` sections 6 and 8b).

Thin layer: validation, the ``ToolResult`` envelope and ``GET /healthz`` come from
``stitch_common.mcp_app``; tool logic lives in ``stitch_ledger.service`` and ``stitch_ledger.core``.

    python -m stitch_ledger.server --stdio
    python -m stitch_ledger.server --http --host 127.0.0.1 --port 8000   # also serves GET /healthz

Environment: ``STITCH_MODE`` (``demo`` default), ``STITCH_LEDGER_DB`` (DuckDB file for the run
store; unset means in memory), ``STITCH_DEMO_DIR`` (dataset root; default ``data/demo``).
"""

from __future__ import annotations

import json

from mcp.server.mcpserver.exceptions import ResourceError

from stitch_common.mcp_app import ContractServer, serve
from stitch_common.tooling import ToolFailure
from stitch_ledger.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_ledger.service import LedgerService

TOOL_VERSION = "0.2.0"
DISTRICTS_URI = "ledger://scenario/{scenario_id}/districts"

DESCRIPTIONS = {
    "optimize_allocation": (
        "Allocate relief commodities across districts to maximise severity- and access-weighted "
        "coverage under supply, budget and an equity floor (LP, or MIP when integer=true). "
        "Omit `districts` to use the committed scenario dataset. Returns coverage, cost-benefit, "
        "solver gap and the equity block; the run_id feeds sensitivity_report."
    ),
    "sensitivity_report": (
        "Shadow prices, reduced costs and the efficiency-equity trade-off curve for a prior "
        "optimize_allocation run_id, from the LP relaxation."
    ),
}

__all__ = ["DISTRICTS_URI", "TOOL_NAMES", "TOOL_SCHEMAS", "TOOL_VERSION", "create_server", "main"]


def create_server(service: LedgerService | None = None) -> ContractServer:
    svc = service if service is not None else LedgerService()
    server = ContractServer(
        organ="ledger",
        tool_version=TOOL_VERSION,
        cores=svc.cores(),
        descriptions=DESCRIPTIONS,
        health_checks=svc.health,
    )

    @server.resource(
        DISTRICTS_URI,
        name="scenario_districts",
        description="Districts of a scenario dataset (population, road access, air/boat share, "
        "default severity). Demo data: severity and air/boat share are illustrative.",
        mime_type="application/json",
    )
    def scenario_districts(scenario_id: str) -> str:
        try:
            rows = svc.scenario_districts(scenario_id)
        except ToolFailure as f:
            raise ResourceError(f"{f.code}: {f.message}") from None
        return json.dumps([r.model_dump(mode="json") for r in rows], ensure_ascii=False)

    return server


def main(argv: list[str] | None = None) -> int:
    return serve(create_server(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
