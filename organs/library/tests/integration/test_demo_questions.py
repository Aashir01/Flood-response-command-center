"""Brain demo questions replay the recorded LLM replies offline (library task 15, LIB-R7.1, P1).

Real local models (``@pytest.mark.models``), the committed pack, and ``FakeLLM`` replaying
``data/demo/library/llm_recordings.jsonl`` (recorded with Nebius). Sockets stay disabled. Each
question of ``data/demo/library/demo_questions.yaml`` is asked the way the Brain asks it (``lang``
set) and the way ``/ask`` asks it (``lang = auto``); the result must match ``expected``, come from
the LLM path (not the extractive fallback) and cite only verbatim spans of stored pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from stitch_common.llm import FakeLLM
from stitch_common.organs.library import AnswerWithCitationsIn
from stitch_library.core.citations import is_verbatim
from stitch_library.ml.embedder import DEFAULT_EMBED_MODEL, load_embedder
from stitch_library.ml.reranker import DEFAULT_RERANK_MODEL, load_reranker
from stitch_library.pack import LIBRARY_DATA, load_into_store, load_pack
from stitch_library.service import LibraryService
from stitch_library.settings import Settings
from stitch_library.store.memory import MemoryStore

pytestmark = pytest.mark.models

QUESTIONS: list[dict[str, Any]] = yaml.safe_load(
    (LIBRARY_DATA / "demo_questions.yaml").read_text(encoding="utf-8")
)
CASES = [(q, lp) for q in QUESTIONS for lp in (q["lang"], "auto")]


@pytest.fixture(scope="module")
def replay_service(models_dir: Path) -> LibraryService:
    settings = Settings()
    emb = load_embedder(DEFAULT_EMBED_MODEL, models_dir)
    rr = load_reranker(DEFAULT_RERANK_MODEL, models_dir)
    store = MemoryStore()
    load_into_store(store, load_pack(), emb)
    return LibraryService.build(
        store, emb, rr, llm=FakeLLM([settings.recordings]), settings=settings
    )


@pytest.mark.parametrize(
    ("q", "lang_param"), CASES, ids=[f"{q['id']}-{q['lang']}-{lp}" for q, lp in CASES]
)
def test_demo_question_replays_with_verbatim_citations(
    replay_service: LibraryService, q: dict[str, Any], lang_param: str
) -> None:
    out = replay_service.answer(AnswerWithCitationsIn(query=q["query"], lang=lang_param))
    data = out.data
    assert data.status == q["expected"], out.warnings
    assert data.generation is not None and data.generation.mode == "llm", out.warnings
    assert not any(w.startswith("EXTRACTIVE_FALLBACK") for w in out.warnings)
    if data.status == "answered":
        assert data.answer and data.citations and data.claims
        for claim in data.claims:
            assert claim.citation_idx
            assert all(0 <= i < len(data.citations) for i in claim.citation_idx)
    else:
        assert data.refusal is not None and data.refusal.reason == q.get("expected_reason")
    for c in [*data.citations, *(data.refusal.closest_hits if data.refusal else [])]:
        assert is_verbatim(replay_service.store.get_page(c.doc_id, c.page), c)
