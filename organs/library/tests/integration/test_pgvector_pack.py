"""The committed pack in a real Postgres + pgvector (library task 13, LIB-R1.5, LIB-R8.1, P7, P11).

Runs against a throwaway ``pgvector/pgvector:pg16`` container (or ``STITCH_TEST_PG_DSN``) and
skips cleanly without Docker. The fake embedder and reranker keep it independent of the model
cache. Checks: the seed job loads the whole committed pack; a second seed writes nothing; a
failure mid-seed rolls back to the previous state; the read-only check sees the seed; and the
Library service answers every demo question identically on pgvector and on the memory store.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from stitch_common.llm import FakeLLM
from stitch_common.organs.library import AnswerWithCitationsIn, SearchGuidanceIn
from stitch_library.calibration import Calibration
from stitch_library.ml.embedder import FakeEmbedder
from stitch_library.ml.reranker import FakeReranker
from stitch_library.pack import LIBRARY_DATA, Pack, load_into_store, load_pack
from stitch_library.service import LibraryService
from stitch_library.store.base import StoreError
from stitch_library.store.memory import MemoryStore
from stitch_library.store.pgvector import PgVectorStore
from stitch_library.store.seed import is_seeded, seed, seed_key

pytestmark = [pytest.mark.pg, pytest.mark.integration, pytest.mark.allow_loopback]

QUESTIONS: list[dict[str, Any]] = yaml.safe_load(
    (LIBRARY_DATA / "demo_questions.yaml").read_text(encoding="utf-8")
)
EMB = FakeEmbedder()
# The fake-model thresholds of tests/conftest.py (not importable under --import-mode=importlib).
FAKE_CAL = Calibration(
    "fake-hash-256+fake-overlap",
    "ok",
    tau_scope=0.05,
    tau_evid={"en": {"rerank": 0.0, "dense": 0.2}, "ur": {"rerank": 0.0, "dense": 0.2}},
)


@pytest.fixture(scope="module")
def pack() -> Pack:
    return load_pack()


@pytest.fixture
def pg(pg_dsn: str) -> Iterator[PgVectorStore]:
    store = PgVectorStore(pg_dsn)
    try:
        yield store
    finally:
        store.close()


def _counts(store: PgVectorStore) -> tuple[int, int, int]:
    s = store.stats()
    return s.docs, s.pages, s.chunks


def test_seed_loads_the_committed_pack_and_reseeding_writes_nothing(
    pg: PgVectorStore, pack: Pack
) -> None:
    assert not is_seeded(pg, pack, EMB)
    seed(pg, pack, EMB)
    assert is_seeded(pg, pack, EMB)
    assert pg.get_meta("seed_key") == seed_key(pack, EMB)
    mem = MemoryStore()
    load_into_store(mem, pack, EMB)
    assert _counts(pg) == (len(pack.docs), mem.stats().pages, len(pack.chunks))
    assert list(pg.iter_search_rows()) == list(mem.iter_search_rows())
    before = (_counts(pg), list(pg.iter_search_rows()))
    assert seed(pg, pack, EMB) == []
    assert (_counts(pg), list(pg.iter_search_rows())) == before


def test_failed_seed_keeps_the_previous_state(
    pg: PgVectorStore, pack: Pack, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(pg, pack, EMB)
    before = (pg.get_meta("seed_key"), _counts(pg))

    class Boom(RuntimeError):
        pass

    def fail(*_a: object, **_k: object) -> None:
        raise Boom("simulated crash after the chunks were written")

    other = FakeEmbedder(dim=128)  # another embedder id, so a re-seed is needed
    monkeypatch.setattr(pg, "set_meta", fail)
    with pytest.raises(Boom):
        seed(pg, pack, other)
    monkeypatch.undo()
    assert (pg.get_meta("seed_key"), _counts(pg)) == before
    assert is_seeded(pg, pack, EMB) and not is_seeded(pg, pack, other)


def test_read_only_store_reports_the_seed(pg_dsn: str, pg: PgVectorStore, pack: Pack) -> None:
    seed(pg, pack, EMB)
    ro = PgVectorStore(pg_dsn, migrate=False)
    try:
        assert ro.ping() and is_seeded(ro, pack, EMB)
        assert _counts(ro) == _counts(pg)
    finally:
        ro.close()


def _service(store: Any) -> LibraryService:
    return LibraryService.build(store, EMB, FakeReranker(), llm=FakeLLM(), calibration=FAKE_CAL)


def test_service_on_pgvector_matches_the_memory_store(pg: PgVectorStore, pack: Pack) -> None:
    seed(pg, pack, EMB)
    mem = MemoryStore()
    load_into_store(mem, pack, EMB)
    on_pg, on_mem = _service(pg), _service(mem)
    for q in QUESTIONS:
        s_pg = on_pg.search(SearchGuidanceIn(query=q["query"], top_k=8)).data
        s_mem = on_mem.search(SearchGuidanceIn(query=q["query"], top_k=8)).data
        assert [h.chunk_id for h in s_pg.hits] == [h.chunk_id for h in s_mem.hits]
        a_pg = on_pg.answer(AnswerWithCitationsIn(query=q["query"], lang=q["lang"])).data
        a_mem = on_mem.answer(AnswerWithCitationsIn(query=q["query"], lang=q["lang"])).data
        assert a_pg.model_dump() == a_mem.model_dump()
        for c in a_pg.citations:
            page = pg.get_page(c.doc_id, c.page)
            assert page is not None and page.text[c.span[0] : c.span[1]].startswith(c.quote[:40])


def test_unknown_dsn_is_a_store_error() -> None:
    with pytest.raises(StoreError):
        PgVectorStore("postgresql://nobody:nothing@127.0.0.1:1/none?connect_timeout=1")
