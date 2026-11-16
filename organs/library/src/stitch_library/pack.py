"""The committed Library pack (design section 4.5): ``data/demo/library/pack/``.

* ``pages.parquet``, ``chunks.parquet``: rows of every committed document (chunks sorted by id).
* ``vectors.<model_id>.npy``: float16 vectors in ``chunks.parquet`` order, one file per model.
* ``pack.json``: documents, manifest hash, chunker version, models, counts, ingest report.

``load_into_store`` upserts a pack into any ``Store``. When the pack has no vectors for the
runtime embedder, chunk vectors are computed locally from the pack's chunk text (a warning is
returned; this needs the model cache, never the network).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from stitch_library.core.chunk import CHUNKER_VERSION
from stitch_library.ml.embedder import Embedder
from stitch_library.store.base import ChunkRow, DocRow, PageRow, Store, Vectors

REPO_ROOT = Path(__file__).resolve().parents[4]
LIBRARY_DATA = REPO_ROOT / "data" / "demo" / "library"
DEFAULT_PACK = LIBRARY_DATA / "pack"
PACK_VERSION = 1
EMBED_BATCH = 64


@dataclass
class Pack:
    docs: list[DocRow]
    pages: list[PageRow]
    chunks: list[ChunkRow]
    vectors: dict[str, Vectors]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def seed_key(self) -> str:
        src = "|".join(
            [
                str(self.meta.get("manifest_sha256", "")),
                str(self.meta.get("chunker_version", "")),
                ",".join(sorted(self.vectors)),
                str(self.meta.get("content_sha256", "")),
            ]
        )
        return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _doc_to_json(d: DocRow) -> dict[str, Any]:
    out = asdict(d)
    out["as_of"] = d.as_of.isoformat() if d.as_of else None
    return out


def _doc_from_json(o: dict[str, Any]) -> DocRow:
    return DocRow(**{**o, "as_of": date.fromisoformat(o["as_of"]) if o.get("as_of") else None})


def content_hash(pages: Sequence[PageRow], chunks: Sequence[ChunkRow]) -> str:
    h = hashlib.sha256()
    for p in sorted(pages, key=lambda p: (p.doc_id, p.page)):
        h.update(f"{p.doc_id}:{p.page}:{p.status}:{p.text}\n".encode())
    for c in sorted(chunks, key=lambda c: c.chunk_id):
        h.update(f"{c.chunk_id}\n".encode())
    return h.hexdigest()


def write_pack(out: Path, pack: Pack) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pages = sorted(pack.pages, key=lambda p: (p.doc_id, p.page))
    chunks = sorted(pack.chunks, key=lambda c: c.chunk_id)
    pq.write_table(
        pa.Table.from_pylist([asdict(p) for p in pages]), out / "pages.parquet", compression="zstd"
    )
    pq.write_table(
        pa.Table.from_pylist([asdict(c) for c in chunks]),
        out / "chunks.parquet",
        compression="zstd",
    )
    for old in out.glob("vectors.*.npy"):
        old.unlink()
    for model_id, mat in sorted(pack.vectors.items()):
        np.save(out / f"vectors.{model_id}.npy", np.asarray(mat, dtype=np.float16))
    meta = dict(pack.meta)
    meta.update(
        {
            "pack_version": PACK_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "documents": [_doc_to_json(d) for d in sorted(pack.docs, key=lambda d: d.doc_id)],
            "doc_ids": sorted(d.doc_id for d in pack.docs),
            "models": sorted(pack.vectors),
            "counts": {"docs": len(pack.docs), "pages": len(pages), "chunks": len(chunks)},
            "content_sha256": content_hash(pages, chunks),
        }
    )
    (out / "pack.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_pack(path: Path = DEFAULT_PACK) -> Pack:
    meta = json.loads((path / "pack.json").read_text(encoding="utf-8"))
    pages = [PageRow(**r) for r in pq.read_table(path / "pages.parquet").to_pylist()]
    chunks = [ChunkRow(**r) for r in pq.read_table(path / "chunks.parquet").to_pylist()]
    vectors: dict[str, Vectors] = {}
    for f in sorted(path.glob("vectors.*.npy")):
        model_id = f.name[len("vectors.") : -len(".npy")]
        mat = np.load(f).astype(np.float32)
        if mat.shape[0] == len(chunks):
            vectors[model_id] = mat
    docs = [_doc_from_json(o) for o in meta.get("documents", [])]
    return Pack(docs, pages, chunks, vectors, meta)


def load_pack_chunks(path: Path = DEFAULT_PACK) -> list[ChunkRow]:
    if not (path / "chunks.parquet").exists():
        return []
    return [ChunkRow(**r) for r in pq.read_table(path / "chunks.parquet").to_pylist()]


def embed_chunks(embedder: Embedder, chunks: Sequence[ChunkRow]) -> Vectors:
    if not chunks:
        return np.zeros((0, embedder.dim), dtype=np.float32)
    parts = [
        embedder.embed_passages([c.text for c in chunks[i : i + EMBED_BATCH]])
        for i in range(0, len(chunks), EMBED_BATCH)
    ]
    return np.concatenate(parts).astype(np.float32)


def load_into_store(
    store: Store, pack: Pack, embedder: Embedder, *, doc_ids: Sequence[str] | None = None
) -> list[str]:
    """Upsert the pack (optionally a subset of documents). Returns warnings."""
    warnings: list[str] = []
    keep = set(doc_ids) if doc_ids is not None else {d.doc_id for d in pack.docs}
    docs = [d for d in pack.docs if d.doc_id in keep]
    pages = [p for p in pack.pages if p.doc_id in keep]
    idx = [i for i, c in enumerate(pack.chunks) if c.doc_id in keep]
    chunks = [pack.chunks[i] for i in idx]
    mat = pack.vectors.get(embedder.model_id)
    if mat is None:
        if pack.vectors:
            warnings.append(f"PACK_REEMBEDDED:{embedder.model_id}")
        vecs = embed_chunks(embedder, chunks)
    else:
        vecs = mat[idx] if idx else np.zeros((0, embedder.dim), dtype=np.float32)
    store.upsert_documents(docs)
    store.upsert_pages(pages)
    store.upsert_chunks(chunks, embedder.model_id, vecs)
    return warnings
