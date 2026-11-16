"""MCP server for oracle-mcp (contract v0.4, ``mcp-contracts.md`` sections 4 and 8b).

Thin layer: validation, the ``ToolResult`` envelope and ``GET /healthz`` come from
``stitch_common.mcp_app``; tool logic lives in ``stitch_oracle.service`` and ``stitch_oracle.core``.

    python -m stitch_oracle.server --stdio
    python -m stitch_oracle.server --http --host 127.0.0.1 --port 8000   # also serves GET /healthz

Environment: ``STITCH_MODE`` (``demo`` default), ``STITCH_ORACLE_DB`` (DuckDB file for the run
store; unset means in memory), ``STITCH_ORACLE_MODELS`` (model bundle directory; default
``organs/oracle/models``), ``STITCH_DEMO_DIR`` (dataset root; default ``data/demo``),
``STITCH_ORACLE_LIVE_CACHE`` (live-mode cache directory; live mode is used only when requested).
"""

from __future__ import annotations

import json

from mcp.server.mcpserver.exceptions import ResourceError

from stitch_common.mcp_app import ContractServer, serve
from stitch_common.tooling import ToolFailure
from stitch_oracle.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_oracle.service import LiveSource, OracleService

TOOL_VERSION = "0.2.0"
STATIONS_URI = "oracle://stations"

DESCRIPTIONS = {
    "forecast_river": (
        "Forecast modeled river discharge (GloFAS via Open-Meteo, m3/s) at the GloFAS grid cell "
        "nearest to a named Indus-system station, 1 to 14 days after as_of. Returns the median "
        "and a split-conformal interval at the requested coverage (default 0.8), the "
        "probability of exceeding the station's danger threshold (a modeled 5-year return "
        "level, an assumption), calibration metadata and the grid cell read. Valid as_of: "
        "2017-01-01 to the end of the dataset. The run_id feeds explain_forecast."
    ),
    "explain_forecast": (
        "Explain a prior forecast_river run_id: TreeSHAP contributions of the median model at "
        "the peak lead day, in m3/s of modeled discharge, the top five features with their "
        "family, and a template narrative (no LLM)."
    ),
}

__all__ = ["STATIONS_URI", "TOOL_NAMES", "TOOL_SCHEMAS", "TOOL_VERSION", "create_server", "main"]


def create_server(service: OracleService | None = None) -> ContractServer:
    svc = service if service is not None else OracleService(live=_live_source())
    server = ContractServer(
        organ="oracle",
        tool_version=TOOL_VERSION,
        cores=svc.cores(),
        descriptions=DESCRIPTIONS,
        health_checks=svc.health,
    )

    @server.resource(
        STATIONS_URI,
        name="stations",
        description="Oracle stations: GloFAS grid cell nearest to each named place, role, "
        "danger threshold and its method (modeled 5-year return level, an assumption), and the "
        "valid as_of window.",
        mime_type="application/json",
    )
    def stations() -> str:
        try:
            rows = svc.stations()
        except ToolFailure as f:
            raise ResourceError(f"{f.code}: {f.message}") from None
        return json.dumps([r.model_dump(mode="json") for r in rows], ensure_ascii=False)

    return server


def _live_source() -> LiveSource:
    from stitch_oracle.live import OpenMeteoLive  # network code, used only for mode=live

    return OpenMeteoLive.from_env()


def main(argv: list[str] | None = None) -> int:
    return serve(create_server(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
