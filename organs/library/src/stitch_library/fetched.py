"""Fetch-tier documents on the local disk (design 3.4, LIB-R10.2).

``scripts/fetch_corpus.py`` downloads ``tier: fetch`` documents to ``data/raw/library/`` (git
ignored). This module turns the ones present into store rows with ``tier = "fetched"``. The
sha256 pinned in the manifest is checked by ``ingest_document``; a document whose file is
missing or whose entry has no pinned hash is skipped and reported, never guessed.

These rows are derivatives of documents that may not be redistributed, so they are only ever
written to a local store or a git-ignored directory, never to ``data/demo/``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from stitch_library.ingest.manifest import ManifestEntry, load_manifest
from stitch_library.ingest.pipeline import IngestedDoc, IngestError, ingest_document
from stitch_library.ml.embedder import Embedder
from stitch_library.pack import LIBRARY_DATA, REPO_ROOT, embed_chunks
from stitch_library.store.base import Store

RAW_DIR = REPO_ROOT / "data" / "raw" / "library"
MANIFEST = LIBRARY_DATA / "manifest.yaml"


@dataclass
class FetchedSet:
    docs: list[IngestedDoc] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # doc_id -> reason


def raw_path(entry: ManifestEntry, raw_dir: Path = RAW_DIR) -> Path:
    ext = "txt" if entry.format == "text" else "pdf"
    return raw_dir / f"{entry.doc_id}.{ext}"


def fetch_entries(manifest: Path = MANIFEST) -> list[ManifestEntry]:
    return [e for e in load_manifest(manifest) if e.tier == "fetch"]


def ingest_fetched(
    entries: Sequence[ManifestEntry] | None = None,
    raw_dir: Path = RAW_DIR,
    *,
    only: Sequence[str] | None = None,
) -> FetchedSet:
    """Ingest every fetch-tier document whose file is present under ``raw_dir``."""
    out = FetchedSet()
    for e in entries if entries is not None else fetch_entries():
        if only is not None and e.doc_id not in only:
            continue
        path = raw_path(e, raw_dir)
        if e.sha256 is None:
            out.skipped[e.doc_id] = "no pinned sha256 in the manifest"
            continue
        if not path.exists():
            out.skipped[e.doc_id] = "not fetched"
            continue
        try:
            out.docs.append(
                ingest_document(
                    e, path.read_bytes(), tier="fetched", allow_low_yield=True, file_path=path
                )
            )
        except IngestError as exc:
            out.skipped[e.doc_id] = str(exc)
    return out


def load_fetched_into_store(store: Store, fetched: FetchedSet, embedder: Embedder) -> int:
    """Upsert fetched documents into ``store`` (vectors computed locally). Returns chunk count."""
    n = 0
    for d in fetched.docs:
        store.upsert_documents([d.doc])
        store.upsert_pages(d.pages)
        store.upsert_chunks(d.chunks, embedder.model_id, embed_chunks(embedder, d.chunks))
        n += len(d.chunks)
    return n
