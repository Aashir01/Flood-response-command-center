"""Embedders: ``OnnxEmbedder`` (onnxruntime + tokenizers, no PyTorch) and ``FakeEmbedder``.

``OnnxEmbedder`` loads ``<STITCH_MODEL_DIR>/<key>/model_int8.onnx`` (falls back to
``model_fp32.onnx``) and ``tokenizer.json``, built by ``scripts/fetch_models.py`` and
``scripts/export_models.py``. E5 needs ``query: `` and ``passage: `` prefixes. Output vectors are
mean-pooled and L2-normalized float32. Inference is deterministic on CPU (fixed thread count).

``FakeEmbedder`` is a hashed bag of content tokens with a small built-in English/Urdu lexicon, so
tests can exercise cross-lingual retrieval without a model. Cosine is meaningful for overlap.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from stitch_library.core.normalize import search_text
from stitch_library.core.tokenize import concept_tokens
from stitch_library.store.base import Vectors


class ModelUnavailable(RuntimeError):
    """The model files are missing or failed to load."""


class Embedder(Protocol):
    model_id: str
    name: str
    revision: str
    sha256: str
    dim: int

    def embed_queries(self, texts: Sequence[str]) -> Vectors: ...
    def embed_passages(self, texts: Sequence[str]) -> Vectors: ...


@dataclass(frozen=True)
class EmbedSpec:
    key: str
    repo: str
    revision: str
    dim: int
    query_prefix: str
    passage_prefix: str
    max_len: int
    license: str


EMBEDDERS: dict[str, EmbedSpec] = {
    "intfloat/multilingual-e5-small": EmbedSpec(
        "e5-small",
        "intfloat/multilingual-e5-small",
        "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        384,
        "query: ",
        "passage: ",
        512,
        "MIT",
    ),
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": EmbedSpec(
        "paraphrase-mminilm",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "unpinned",
        384,
        "",
        "",
        128,
        "Apache-2.0",
    ),
}
DEFAULT_EMBED_MODEL = "intfloat/multilingual-e5-small"


def default_model_dir() -> Path:
    env = os.environ.get("STITCH_MODEL_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[5] / "data" / "raw" / "models"


def _l2(mat: np.ndarray[Any, Any]) -> Vectors:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    out: Vectors = (mat / np.where(norms == 0, 1.0, norms)).astype(np.float32)
    return out


class FakeEmbedder:
    """Deterministic hashed bag-of-tokens embedder for tests (no model files)."""

    name = "fake-hash"
    revision = "1"
    sha256 = "0" * 64

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.model_id = f"fake-hash-{dim}"

    def _vec(self, text: str) -> np.ndarray[Any, Any]:
        v = np.zeros(self.dim, dtype=np.float64)
        for tok in sorted(concept_tokens(search_text(text))):
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            v[idx] += 1.0 if h[4] & 1 else -1.0
        return v

    def _embed(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _l2(np.stack([self._vec(t) for t in texts]))

    def embed_queries(self, texts: Sequence[str]) -> Vectors:
        return self._embed(texts)

    def embed_passages(self, texts: Sequence[str]) -> Vectors:
        return self._embed(texts)


def _session(path: Path, threads: int) -> Any:
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class OnnxEmbedder:
    def __init__(
        self, spec: EmbedSpec, model_dir: Path, *, threads: int = 2, batch_size: int = 16
    ) -> None:
        from tokenizers import Tokenizer

        base = model_dir / spec.key
        onnx = base / "model_int8.onnx"
        if not onnx.exists():
            onnx = base / "model_fp32.onnx"
        tok_path = base / "tokenizer.json"
        if not onnx.exists() or not tok_path.exists():
            raise ModelUnavailable(f"embedding model files missing under {base}")
        self.spec = spec
        self.name = spec.repo
        self.revision = spec.revision
        self.dim = spec.dim
        self.variant = "int8" if onnx.name == "model_int8.onnx" else "fp32"
        self.model_id = f"{spec.key}-{self.variant}"
        self.sha256 = sha256_file(onnx)
        self.batch_size = batch_size
        try:
            self._tok = Tokenizer.from_file(str(tok_path))
            self._tok.enable_truncation(max_length=spec.max_len)
            self._tok.enable_padding()
            self._sess = _session(onnx, threads)
        except Exception as exc:
            raise ModelUnavailable(f"failed to load {onnx.name}: {type(exc).__name__}") from exc
        self._inputs = {i.name for i in self._sess.get_inputs()}

    def _run(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for b in range(0, len(order), self.batch_size):
            idx = order[b : b + self.batch_size]
            enc = self._tok.encode_batch([texts[i] for i in idx])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed: dict[str, Any] = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._sess.run(None, feed)[0].astype(np.float64)
            m = mask[:, :, None].astype(np.float64)
            pooled = (hidden * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1e-9)
            out[idx] = _l2(pooled)
        return out

    def embed_queries(self, texts: Sequence[str]) -> Vectors:
        return self._run([self.spec.query_prefix + search_text(t) for t in texts])

    def embed_passages(self, texts: Sequence[str]) -> Vectors:
        return self._run([self.spec.passage_prefix + search_text(t) for t in texts])


def load_embedder(name: str, model_dir: Path | None = None, *, threads: int = 2) -> Embedder:
    if name in ("fake", "fake-hash"):
        return FakeEmbedder()
    spec = EMBEDDERS.get(name)
    if spec is None:
        raise ModelUnavailable(f"unknown embedding model {name!r}; known: {sorted(EMBEDDERS)}")
    return OnnxEmbedder(spec, model_dir or default_model_dir(), threads=threads)
