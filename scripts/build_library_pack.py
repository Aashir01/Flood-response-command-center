"""Build the committed Library pack from the committed corpus (design section 4.5).

    uv run python scripts/build_library_pack.py [--models e5-small] [--allow-low-yield] [--check]

Reads ``data/demo/library/manifest.yaml``, ingests every ``tier: committed`` document from
``data/demo/library/corpus/`` (sha256 verified), and writes ``data/demo/library/pack/``:
``pages.parquet``, ``chunks.parquet``, ``vectors.<model_id>.npy`` for each requested embedder whose
model cache is present, and ``pack.json`` with the ingest report. Fetch-tier documents are never
read. ``--check`` rebuilds in memory and fails if the committed pack is stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data" / "demo" / "library"


def build(out: Path, models: list[str], allow_low_yield: bool) -> dict[str, object]:
    from stitch_library.ingest.manifest import load_manifest
    from stitch_library.ingest.pipeline import ingest_document
    from stitch_library.ml.embedder import ModelUnavailable, load_embedder
    from stitch_library.pack import Pack, embed_chunks, write_pack

    manifest_path = DATA / "manifest.yaml"
    entries = [e for e in load_manifest(manifest_path) if e.tier == "committed"]
    docs, pages, chunks, reports = [], [], [], []
    for e in entries:
        assert e.path is not None
        data = (DATA / e.path).read_bytes()
        res = ingest_document(e, data, allow_low_yield=allow_low_yield, file_path=DATA / e.path)
        docs.append(res.doc)
        pages += res.pages
        chunks += res.chunks
        r = res.report
        reports.append(
            {
                "doc_id": r.doc_id,
                "pages": r.pages,
                "readable": r.readable,
                "readable_ratio": round(r.readable_ratio, 4),
                "reordered": r.reordered,
                "chunks": r.chunks,
                "unreadable": {str(k): v for k, v in r.unreadable.items()},
            }
        )
        print(f"{e.doc_id}: {r.readable}/{r.pages} readable pages, {r.chunks} chunks")
    chunks.sort(key=lambda c: c.chunk_id)
    vectors = {}
    model_meta = {}
    for name in models:
        try:
            emb = load_embedder(name)
        except ModelUnavailable as exc:
            print(f"skip vectors for {name}: {exc}", file=sys.stderr)
            continue
        vectors[emb.model_id] = embed_chunks(emb, chunks)
        model_meta[emb.model_id] = {
            "name": emb.name,
            "revision": emb.revision,
            "sha256": emb.sha256,
        }
    manifest_sha = hashlib.sha256(manifest_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    meta: dict[str, object] = {
        "manifest_sha256": manifest_sha,
        "ingest_report": reports,
        "model_info": model_meta,
    }
    write_pack(out, Pack(docs, pages, chunks, vectors, meta))
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", default="intfloat/multilingual-e5-small")
    parser.add_argument("--allow-low-yield", action="store_true")
    parser.add_argument("--check", action="store_true", help="fail if the committed pack is stale")
    parser.add_argument("--out", type=Path, default=DATA / "pack")
    args = parser.parse_args(argv)
    models = [m for m in args.models.split(",") if m]
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp), [], args.allow_low_yield)
            fresh = json.loads((Path(tmp) / "pack.json").read_text(encoding="utf-8"))
        current = json.loads((args.out / "pack.json").read_text(encoding="utf-8"))
        keys = ("content_sha256", "manifest_sha256", "chunker_version")
        stale = [k for k in keys if fresh.get(k) != current.get(k)]
        if stale:
            print(f"pack is stale ({', '.join(stale)}); run scripts/build_library_pack.py")
            return 1
        print("pack is current")
        return 0
    build(args.out, models, args.allow_low_yield)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
