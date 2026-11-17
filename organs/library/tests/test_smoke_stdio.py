"""Smoke tests: start the server over stdio, list tools, call both tools on a demo question and
check the envelope, the v0.4 fields and the LIB-P1 invariant; serve ``GET /healthz`` and
``GET /healthz/library`` from the streamable HTTP app. Refs: LIB-R8.1, R8.2, R11.1."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from starlette.testclient import TestClient

from stitch_common import CONTRACT_VERSION
from stitch_common.envelope import ToolResult
from stitch_common.organs.library import AnswerWithCitationsOut, SearchGuidanceOut
from stitch_library.models import TOOL_NAMES
from stitch_library.server import create_server
from stitch_library.service import LibraryService

SRC = str(Path(__file__).resolve().parents[1] / "src")
QUESTION = "How much drinking water does each person need per day in a flood emergency?"


def _params() -> StdioServerParameters:
    env = {"PYTHONPATH": SRC, "STITCH_MODE": "demo", "STITCH_LLM_PROVIDER": "fake"}
    for name in ("SYSTEMROOT", "PATH", "STITCH_MODEL_DIR"):  # Windows needs SYSTEMROOT
        if os.environ.get(name):
            env[name] = os.environ[name]
    return StdioServerParameters(
        command=sys.executable, args=["-m", "stitch_library.server", "--stdio"], env=env
    )


async def test_stdio_lists_tools_and_calls_both() -> None:
    async with Client(_params(), read_timeout_seconds=180) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        found = await client.call_tool("search_guidance", {"query": QUESTION, "top_k": 5})
        answered = await client.call_tool("answer_with_citations", {"query": QUESTION})
    s_env = ToolResult[SearchGuidanceOut].model_validate(found.structured_content)
    assert s_env.ok and s_env.data is not None and s_env.provenance.organ == "library"
    assert s_env.provenance.mode == "demo" and s_env.provenance.models
    assert 1 <= len(s_env.data.hits) <= 5
    assert all(h.chunk_id and h.span and h.title for h in s_env.data.hits)

    a_env = ToolResult[AnswerWithCitationsOut].model_validate(answered.structured_content)
    assert a_env.ok and a_env.data is not None
    out = a_env.data
    assert out.generation is not None and out.quantities is not None
    if out.status == "answered":
        assert out.answer and out.citations and out.claims
        assert all(c.citation_idx for c in out.claims)
    else:
        assert out.refusal is not None and not out.citations


def test_healthz_reports_checks(installed_service: LibraryService) -> None:
    client = TestClient(create_server().streamable_http_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["organ"] == "library"
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["checks"] == {"db": True, "index_nonempty": True, "embedder_loaded": True}
    detail = client.get("/healthz/library").json()
    assert detail["store"] == "memory" and detail["chunks"] > 0
    assert detail["llm_provider"] == "fake"
