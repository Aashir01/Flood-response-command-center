"""Rerankers: ``OnnxReranker`` (cross-encoder), ``FakeReranker`` (token overlap) and
``NullReranker`` (no reranking; hits carry ``rerank = null``).

``OnnxReranker`` loads ``<STITCH_MODEL_DIR>/<key>/model_int8.onnx`` and ``tokenizer.json``,
truncates pairs to 256 tokens, scores in batches of 20, and allows at most 4 concurrent calls.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from stitch_library.core.normalize import search_text
from stitch_library.core.tokenize import content_tokens
from stitch_library.ml.embedder import ModelUnavailable, _session, default_model_dir, sha256_file


class Reranker(Protocol):
    model_id: str
    name: str
    revision: str
    sha256: str

    @property
    def active(self) -> bool: ...

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class RerankSpec:
    key: str
    repo: str
    revision: str
    max_len: int
    license: str


RERANKERS: dict[str, RerankSpec] = {
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1": RerankSpec(
        "mmarco",
        "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        "1427fd652930e4ba29e8149678df786c240d8825",
        256,
        "Apache-2.0",
    ),
}
DEFAULT_RERANK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


class NullReranker:
    model_id = "none"
    name = "none"
    revision = "none"
    sha256 = "0" * 64
    active = False

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        raise RuntimeError("NullReranker does not score")


class FakeReranker:
    """Score = 10 * share of query content tokens present in the passage, minus 5."""

    model_id = "fake-overlap"
    name = "fake-overlap"
    revision = "1"
    sha256 = "0" * 64
    active = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if self.fail:
            raise RuntimeError("fake reranker failure")
        q = content_tokens(search_text(query))
        out = []
        for p in passages:
            toks = content_tokens(search_text(p))
            out.append(10.0 * (len(q & toks) / len(q)) - 5.0 if q else -5.0)
        return out


class OnnxReranker:
    active = True

    def __init__(
        self, spec: RerankSpec, model_dir: Path, *, threads: int = 2, batch_size: int = 20
    ) -> None:
        from tokenizers import Tokenizer

        base = model_dir / spec.key
        onnx = base / "model_int8.onnx"
        tok_path = base / "tokenizer.json"
        if not onnx.exists() or not tok_path.exists():
            raise ModelUnavailable(f"reranker files missing under {base}")
        self.name = spec.repo
        self.revision = spec.revision
        self.model_id = f"{spec.key}-int8"
        self.sha256 = sha256_file(onnx)
        self.batch_size = batch_size
        self._lock = threading.BoundedSemaphore(4)
        try:
            self._tok = Tokenizer.from_file(str(tok_path))
            self._tok.enable_truncation(max_length=spec.max_len)
            self._tok.enable_padding()
            self._sess = _session(onnx, threads)
        except Exception as exc:
            raise ModelUnavailable(f"failed to load reranker: {type(exc).__name__}") from exc
        self._inputs = {i.name for i in self._sess.get_inputs()}

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        out: list[float] = []
        with self._lock:
            for b in range(0, len(passages), self.batch_size):
                pairs = [(query, p) for p in passages[b : b + self.batch_size]]
                enc = self._tok.encode_batch(pairs)
                ids = np.array([e.ids for e in enc], dtype=np.int64)
                feed: dict[str, Any] = {
                    "input_ids": ids,
                    "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
                }
                if "token_type_ids" in self._inputs:
                    feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
                logits = self._sess.run(None, feed)[0]
                out.extend(float(x) for x in np.asarray(logits).reshape(len(pairs), -1)[:, 0])
        return out


def load_reranker(name: str, model_dir: Path | None = None, *, threads: int = 2) -> Reranker:
    if name in ("none", ""):
        return NullReranker()
    if name == "fake":
        return FakeReranker()
    spec = RERANKERS.get(name)
    if spec is None:
        raise ModelUnavailable(f"unknown reranker {name!r}; known: {sorted(RERANKERS)}")
    return OnnxReranker(spec, model_dir or default_model_dir(), threads=threads)
