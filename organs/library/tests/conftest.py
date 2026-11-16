"""Library test setup.

* ``tests/strategies.py`` is importable as ``library_strategies`` (the repo runs pytest with
  ``--import-mode=importlib``, which does not put test directories on ``sys.path``).
* ``demo_service``: a ``LibraryService`` on the committed pack with the deterministic fake
  embedder and reranker and an empty ``FakeLLM`` (extractive answers). No model files, no
  network.
* ``models_dir``: the model cache, or skip (``@pytest.mark.models`` tests).
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_path = Path(__file__).parent / "strategies.py"
if "library_strategies" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("library_strategies", _path)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["library_strategies"] = _module
    _spec.loader.exec_module(_module)

from stitch_common.llm import FakeLLM  # noqa: E402
from stitch_library.calibration import Calibration  # noqa: E402
from stitch_library.ml.embedder import FakeEmbedder, default_model_dir  # noqa: E402
from stitch_library.ml.reranker import FakeReranker  # noqa: E402
from stitch_library.pack import load_into_store, load_pack  # noqa: E402
from stitch_library.service import LibraryService, set_service  # noqa: E402
from stitch_library.store.memory import MemoryStore  # noqa: E402

# Thresholds for the fake embedder/reranker profile used by unit tests (FakeReranker scores are
# 10 * query-term overlap - 5, so 0 means at least half the query terms are present).
FAKE_CAL = Calibration(
    "fake-hash-256+fake-overlap",
    "ok",
    tau_scope=0.05,
    tau_evid={"en": {"rerank": 0.0, "dense": 0.2}, "ur": {"rerank": 0.0, "dense": 0.2}},
)


def make_demo_service(**kw: object) -> LibraryService:
    emb = FakeEmbedder()
    store = MemoryStore()
    load_into_store(store, load_pack(), emb)
    llm = kw.pop("llm", FakeLLM())
    return LibraryService.build(
        store,
        emb,
        FakeReranker(),
        llm=llm,
        calibration=FAKE_CAL,
        **kw,  # type: ignore[arg-type]
    )


@pytest.fixture(scope="session")
def demo_service() -> LibraryService:
    return make_demo_service()


@pytest.fixture
def installed_service(demo_service: LibraryService) -> Iterator[LibraryService]:
    set_service(demo_service)
    try:
        yield demo_service
    finally:
        set_service(None)


@pytest.fixture(scope="session")
def models_dir() -> Path:
    d = default_model_dir()
    if not (d / "e5-small" / "tokenizer.json").exists():
        pytest.skip(f"model cache not found under {d} (run scripts/fetch_models.py)")
    return d
