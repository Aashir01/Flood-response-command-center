"""MCP server for library-mcp. Thin layer: validation, envelope and ``/healthz`` come from
``stitch_common.mcp_app``; the logic lives in ``stitch_library.core`` and ``service.py``.

    python -m stitch_library.server --stdio
    python -m stitch_library.server --http --host 127.0.0.1 --port 8000

``GET /healthz`` reports ``db``, ``index_nonempty`` and ``embedder_loaded`` (503 if any is false;
a missing reranker is degraded, not unhealthy). ``GET /healthz/library`` adds counts, seed key,
BM25 fingerprint, model ids, calibration status and the LLM provider. Models load at startup.
"""

from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from stitch_common.mcp_app import ContractServer, serve
from stitch_library.core import CORES
from stitch_library.models import TOOL_NAMES, TOOL_SCHEMAS

TOOL_VERSION = "0.2.0"
DESCRIPTIONS = {
    "search_guidance": (
        "Hybrid BM25 + dense search with cross-encoder reranking over the flood-response "
        "guidance corpus (English and Urdu). Returns scored passages with page and span."
    ),
    "answer_with_citations": (
        "Answer a guidance question only from retrieved passages, with verified page-level "
        "citations, or refuse (INSUFFICIENT_EVIDENCE, OUT_OF_SCOPE, CONFLICTING_EVIDENCE)."
    ),
}

__all__ = ["TOOL_NAMES", "TOOL_SCHEMAS", "TOOL_VERSION", "create_server", "main"]


def _checks() -> Mapping[str, bool]:
    from stitch_library.service import get_service

    try:
        return get_service().health_checks()
    except Exception:
        return {"service": False}


def create_server(*, warm: bool = False) -> ContractServer:
    server = ContractServer(
        organ="library",
        tool_version=TOOL_VERSION,
        cores=CORES,
        descriptions=DESCRIPTIONS,
        health_checks=_checks,
    )

    @server.custom_route("/healthz/library", methods=["GET"])  # type: ignore[untyped-decorator]
    async def library_health(request: Request) -> Response:
        from stitch_library.service import get_service

        try:
            detail = get_service().health()
        except Exception as exc:
            return JSONResponse({"status": "unwell", "error": type(exc).__name__}, status_code=503)
        return JSONResponse(detail)

    if warm:
        from stitch_library.service import get_service

        get_service()
    return server


def main(argv: list[str] | None = None) -> int:
    return serve(create_server(warm=True), argv)


if __name__ == "__main__":
    raise SystemExit(main())
