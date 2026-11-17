"""Tool entry points through the shared envelope (design 9.1, LIB-R8.2): ok results, error
mapping, provenance, input limits. Uses the fake-model demo service (conftest)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stitch_common.envelope import ToolResult
from stitch_common.organs.library import AnswerWithCitationsOut, SearchGuidanceOut
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_common.tooling import run_tool
from stitch_library.core import CORES
from stitch_library.models import TOOL_NAMES
from stitch_library.server import TOOL_VERSION
from stitch_library.service import LibraryService, set_service
from stitch_library.store.base import StoreError


def call(tool: str, args: dict[str, Any]) -> ToolResult[Any]:
    return asyncio.run(run_tool("library", tool, TOOL_VERSION, CORES[tool], args))


def test_cores_cover_exactly_the_contract_tools() -> None:
    assert sorted(CORES) == sorted(TOOL_NAMES)


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_contract_example_input_returns_ok_with_provenance(tool: str) -> None:
    result = call(tool, TOOL_EXAMPLES[f"library.{tool}"][0])
    assert result.ok and result.error is None
    assert result.provenance.organ == "library" and result.provenance.tool == tool
    assert result.provenance.mode == "demo"
    assert result.provenance.models and result.provenance.model is not None


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_invalid_input_is_reported_not_raised(tool: str) -> None:
    result = call(tool, {"unexpected": 1})
    assert result.error is not None and result.error.code == "INVALID_INPUT"


def test_search_returns_scored_hits_with_v04_fields() -> None:
    result = call("search_guidance", {"query": "boil water one minute", "top_k": 5})
    data = SearchGuidanceOut.model_validate(result.data)
    assert 1 <= len(data.hits) <= 5
    h = data.hits[0]
    assert h.chunk_id and h.span is not None and h.title and h.publisher
    assert {d.id for d in result.provenance.data_sources} == {x.doc_id for x in data.hits}


def test_answer_on_the_committed_pack_has_verbatim_citations(
    demo_service: LibraryService,
) -> None:
    result = call("answer_with_citations", {"query": "How long should water be boiled?"})
    data = AnswerWithCitationsOut.model_validate(result.data)
    assert data.status == "answered" and data.citations
    for c in data.citations:
        page = demo_service.store.get_page(c.doc_id, c.page)
        assert page is not None and page.text[c.span[0] : c.span[1]] == c.quote
    assert data.generation is not None and data.generation.mode == "extractive"
    assert any(w.startswith("EXTRACTIVE_FALLBACK") for w in result.warnings)


def test_refusal_is_an_ok_result_never_no_evidence() -> None:
    result = call("answer_with_citations", {"query": "zzqx vortex quantum blockchain"})
    assert result.ok
    data = AnswerWithCitationsOut.model_validate(result.data)
    assert data.status == "refused" and data.refusal is not None
    assert data.citations == [] and data.quantities == []


@pytest.mark.parametrize(
    "args",
    [
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "water", "filters": {"publisher": ["p" * 101]}},
        {"query": "water", "filters": {"doc_id": [f"d{i}" for i in range(21)]}},
    ],
)
def test_input_limits_are_invalid_input(args: dict[str, Any]) -> None:
    result = call("search_guidance", args)
    assert result.error is not None and result.error.code == "INVALID_INPUT"


def test_top_k_outside_contract_range_is_invalid() -> None:
    assert call("search_guidance", {"query": "water", "top_k": 21}).error is not None
    assert call("search_guidance", {"query": "water", "top_k": 0}).error is not None


def test_store_down_is_upstream_unavailable_and_retryable(demo_service: LibraryService) -> None:
    class Down:
        def __getattr__(self, name: str) -> Any:
            def fail(*a: Any, **k: Any) -> Any:
                raise StoreError("db down")

            return fail

    broken = LibraryService.build(
        demo_service.store,
        demo_service.embedder,
        demo_service.reranker,
        llm=None,
        calibration=demo_service.calibration,
    )
    broken.retriever.store = Down()  # type: ignore[assignment]
    set_service(broken)
    result = call("search_guidance", {"query": "boil water"})
    assert result.error is not None and result.error.code == "UPSTREAM_UNAVAILABLE"
    assert result.error.retryable


def test_require_llm_without_llm_is_upstream_unavailable(demo_service: LibraryService) -> None:
    from stitch_library.settings import Settings

    strict = LibraryService.build(
        demo_service.store,
        demo_service.embedder,
        demo_service.reranker,
        llm=None,
        settings=Settings(require_llm=True),
        calibration=demo_service.calibration,
    )
    set_service(strict)
    result = call("answer_with_citations", {"query": "How long should water be boiled?"})
    assert result.error is not None and result.error.code == "UPSTREAM_UNAVAILABLE"


def test_queries_are_logged_as_hash_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "my private question about water boiling"
    with caplog.at_level("INFO", logger="stitch.library"):
        call("search_guidance", {"query": secret})
    assert all(
        secret not in r.getMessage() and secret not in str(r.__dict__) for r in caplog.records
    )


def test_health_reports_store_index_and_models(demo_service: LibraryService) -> None:
    h = demo_service.health()
    assert h["db_ok"] and h["chunks"] > 0 and h["docs"] == 11
    assert h["calibration"] == "ok" and h["embedder"]["loaded"]
    assert demo_service.health_checks() == {
        "db": True,
        "index_nonempty": True,
        "embedder_loaded": True,
    }
