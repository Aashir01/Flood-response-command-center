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
import os
import secrets
import shutil
import subprocess
import sys
import time
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


@pytest.fixture(autouse=True)
def _fake_process_service(
    request: pytest.FixtureRequest, demo_service: LibraryService
) -> Iterator[None]:
    """Tool entry points (``CORES``) use the process-wide service. Unit and property tests get
    the fake-model demo service so they never load model files; ``@pytest.mark.models`` tests
    build their own."""
    if request.node.get_closest_marker("models") is not None:
        yield
        return
    set_service(demo_service)
    try:
        yield
    finally:
        set_service(None)


@pytest.fixture
def installed_service(demo_service: LibraryService) -> Iterator[LibraryService]:
    set_service(demo_service)
    try:
        yield demo_service
    finally:
        set_service(None)


PG_IMAGE = "pgvector/pgvector:pg16"


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        res = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0 and bool(res.stdout.strip())


def _wait_for_pg(dsn: str, timeout_s: float = 90.0) -> None:
    import psycopg

    deadline = time.monotonic() + timeout_s
    ok_in_a_row = 0
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            ok_in_a_row += 1
            if ok_in_a_row >= 2:  # the image restarts once after initdb
                return
        except psycopg.Error:
            ok_in_a_row = 0
        time.sleep(1.0)
    raise RuntimeError("Postgres did not become ready")


@pytest.fixture(scope="session")
def pg_admin_dsn() -> Iterator[str]:
    """A superuser DSN on a throwaway ``pgvector/pgvector:pg16`` container (or
    ``STITCH_TEST_PG_DSN``). Skips cleanly when neither Docker nor the variable is available.
    The password is generated per run; nothing is stored."""
    env = os.environ.get("STITCH_TEST_PG_DSN")
    if env:
        yield env
        return
    if not _docker_ok():
        pytest.skip("Docker is not available and STITCH_TEST_PG_DSN is not set")
    password = secrets.token_hex(16)
    name = f"stitch-library-test-{secrets.token_hex(4)}"
    run = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", f"POSTGRES_PASSWORD={password}", "-e", "POSTGRES_DB=postgres",
            "-p", "127.0.0.1::5432", PG_IMAGE,
        ],
        capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    if run.returncode != 0:
        pytest.skip(f"cannot start {PG_IMAGE}: {run.stderr.strip()[:200]}")
    try:
        port_out = subprocess.run(
            ["docker", "port", name, "5432/tcp"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip().splitlines()[0]  # fmt: skip
        port = port_out.rsplit(":", 1)[-1]
        dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
        _wait_for_pg(dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60, check=False)


@pytest.fixture
def pg_dsn(pg_admin_dsn: str) -> Iterator[str]:
    """A fresh database with the ``vector`` extension, dropped after the test."""
    import psycopg
    from psycopg import sql

    db = f"t_{secrets.token_hex(6)}"
    with psycopg.connect(pg_admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
    base, _, _ = pg_admin_dsn.rpartition("/")
    dsn = f"{base}/{db}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield dsn
    finally:
        with psycopg.connect(pg_admin_dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db))
            )


@pytest.fixture(scope="session")
def models_dir() -> Path:
    d = default_model_dir()
    if not (d / "e5-small" / "tokenizer.json").exists():
        pytest.skip(f"model cache not found under {d} (run scripts/fetch_models.py)")
    return d
