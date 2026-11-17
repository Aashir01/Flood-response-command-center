"""Corpora and services for the Library evals.

* ``committed``: the committed pack only (what ``docker compose up`` serves). The default.
* ``full``: the committed pack plus every fetch-tier document present under ``data/raw/library``
  (``scripts/fetch_corpus.py``). Reported separately, never mixed (LIB-R10.4).

Services use the real local models (``STITCH_MODEL_DIR``, default ``data/raw/models``) and the
``FakeLLM`` replaying ``data/demo/library/llm_recordings.jsonl``; questions without a recording
take the extractive path. No network is used.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Literal

from evals.library.dataset import PageText
from stitch_common.llm import FakeLLM, LLMClient
from stitch_library.calibration import Calibration, load_calibration, profile_key
from stitch_library.core.normalize import normalize_text
from stitch_library.fetched import FetchedSet, ingest_fetched, load_fetched_into_store
from stitch_library.ingest.manifest import load_manifest
from stitch_library.ml.embedder import (
    DEFAULT_EMBED_MODEL,
    Embedder,
    ModelUnavailable,
    default_model_dir,
    load_embedder,
)
from stitch_library.ml.reranker import (
    DEFAULT_RERANK_MODEL,
    NullReranker,
    Reranker,
    load_reranker,
)
from stitch_library.pack import load_into_store, load_pack
from stitch_library.service import LibraryService
from stitch_library.settings import Settings
from stitch_library.store.memory import MemoryStore

Corpus = Literal["committed", "full"]


class ModelsMissing(RuntimeError):
    """The local model cache is not present (run scripts/fetch_models.py)."""


@cache
def embedder() -> Embedder:
    try:
        return load_embedder(DEFAULT_EMBED_MODEL, default_model_dir())
    except ModelUnavailable as exc:
        raise ModelsMissing(
            f"model cache missing under {default_model_dir()} "
            "(uv run python scripts/fetch_models.py && uv run python scripts/export_models.py)"
        ) from exc


@cache
def reranker(enabled: bool = True) -> Reranker:
    if not enabled:
        return NullReranker()
    try:
        return load_reranker(DEFAULT_RERANK_MODEL, default_model_dir())
    except ModelUnavailable as exc:
        raise ModelsMissing(f"reranker missing under {default_model_dir()}") from exc


@cache
def fetched() -> FetchedSet:
    return ingest_fetched()


def manifest_tiers() -> dict[str, str]:
    from stitch_library.fetched import MANIFEST

    return {e.doc_id: e.tier for e in load_manifest(MANIFEST)}


def page_lookup(include_fetched: bool = True) -> PageText:
    pages = {(p.doc_id, p.page): p.text for p in load_pack().pages if p.status == "ok"}
    if include_fetched:
        for d in fetched().docs:
            for p in d.pages:
                if p.status == "ok":
                    pages[(p.doc_id, p.page)] = p.text
    return lambda doc_id, page: pages.get((doc_id, page))


def normalize_quote(s: str) -> str:
    return normalize_text(s)


@dataclass
class Built:
    service: LibraryService
    corpus: Corpus
    reranker_on: bool
    docs: int


def build_service(
    corpus: Corpus,
    *,
    reranker_on: bool = True,
    calibration: Calibration | None = None,
    llm: LLMClient | None = None,
    rerank_langs: tuple[str, ...] | None = None,
) -> Built:
    emb = embedder()
    rr = reranker(reranker_on)
    store = MemoryStore()
    load_into_store(store, load_pack(), emb)
    if corpus == "full":
        load_fetched_into_store(store, fetched(), emb)
    settings = Settings() if rerank_langs is None else Settings(rerank_langs=rerank_langs)
    cal = calibration or load_calibration(profile_key(emb.model_id, rr.model_id))
    service = LibraryService.build(
        store,
        emb,
        rr,
        llm=llm if llm is not None else FakeLLM([settings.recordings]),
        settings=settings,
        calibration=cal,
    )
    return Built(service, corpus, reranker_on, len(store.get_documents()))


ServiceFactory = Callable[[Corpus, bool], Built]
