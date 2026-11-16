"""Environment configuration for the Library (design section 14)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from stitch_library.ml.embedder import DEFAULT_EMBED_MODEL, default_model_dir
from stitch_library.ml.reranker import DEFAULT_RERANK_MODEL
from stitch_library.pack import DEFAULT_PACK, LIBRARY_DATA


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    store: str = "memory"  # "memory" | "pgvector"
    dsn: str | None = None
    embed_model: str = DEFAULT_EMBED_MODEL
    rerank_model: str = DEFAULT_RERANK_MODEL
    rerank_langs: tuple[str, ...] = ("en", "ur")
    model_dir: Path = Path("data/raw/models")
    threads: int = 2
    llm_provider: str = "fake"
    require_llm: bool = False
    conflict_policy: str = "refuse"
    log_queries: bool = False
    data_dir: Path = LIBRARY_DATA
    pack_dir: Path = DEFAULT_PACK
    llm_timeout_s: float = 6.0

    @property
    def recordings(self) -> Path:
        return self.data_dir / "llm_recordings.jsonl"

    @property
    def anchors_path(self) -> Path:
        return self.data_dir / "scope_anchors.yaml"

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("STITCH_LIBRARY_DATA") or LIBRARY_DATA)
        langs = os.environ.get("STITCH_RERANK_LANGS", "en,ur")
        return cls(
            store=os.environ.get("STITCH_LIBRARY_STORE", "memory").strip().lower(),
            dsn=os.environ.get("STITCH_LIBRARY_DSN") or None,
            embed_model=os.environ.get("STITCH_EMBED_MODEL") or DEFAULT_EMBED_MODEL,
            rerank_model=os.environ.get("STITCH_RERANK_MODEL") or DEFAULT_RERANK_MODEL,
            rerank_langs=tuple(x.strip() for x in langs.split(",") if x.strip()),
            model_dir=default_model_dir(),
            threads=int(os.environ.get("STITCH_LIB_THREADS", "2")),
            llm_provider=(os.environ.get("STITCH_LLM_PROVIDER") or "fake").strip().lower(),
            require_llm=_flag("STITCH_LIB_REQUIRE_LLM"),
            conflict_policy=os.environ.get("STITCH_LIB_CONFLICT_POLICY", "refuse"),
            log_queries=_flag("STITCH_LIB_LOG_QUERIES"),
            data_dir=data_dir,
            pack_dir=Path(os.environ.get("STITCH_LIBRARY_PACK") or data_dir / "pack"),
        )
