"""Idempotent seeding of the committed pack into Postgres (design section 5.4).

1. Take ``pg_advisory_lock`` so two replicas cannot seed at once.
2. Migrations ran when the store was opened.
3. ``seed_key`` = the pack's seed key plus the runtime embedder id.
4. If ``meta.seed_key`` equals it, do nothing ("already seeded").
5. Otherwise, in one transaction: upsert documents, pages, chunks and vectors, delete committed
   documents no longer in the pack, set ``meta.seed_key``. ``tier = fetched`` documents are never
   touched. A failure rolls the whole transaction back, so the previous state stays.
6. Release the lock.
"""

from __future__ import annotations

import hashlib
import logging

from stitch_library.ml.embedder import Embedder
from stitch_library.pack import Pack, load_into_store
from stitch_library.store.pgvector import PgVectorStore

ADVISORY_LOCK = 4_202_211  # constant lock id for library seeding
SQL_LOCK = "SELECT pg_advisory_lock(%s)"
SQL_UNLOCK = "SELECT pg_advisory_unlock(%s)"
SQL_COMMITTED_IDS = "SELECT doc_id FROM documents WHERE tier = 'committed'"

log = logging.getLogger("stitch.library.seed")


def seed_key(pack: Pack, embedder: Embedder) -> str:
    return hashlib.sha256(f"{pack.seed_key}|{embedder.model_id}".encode()).hexdigest()


def seed(store: PgVectorStore, pack: Pack, embedder: Embedder) -> list[str]:
    """Seed if needed. Returns warnings. Raises ``StoreError`` after rolling back on failure."""
    key = seed_key(pack, embedder)
    store._exec(SQL_LOCK, (ADVISORY_LOCK,))
    try:
        if store.get_meta("seed_key") == key:
            log.info("already seeded", extra={"seed_key": key[:12]})
            return []
        store.begin()
        try:
            warnings = load_into_store(store, pack, embedder)
            keep = {d.doc_id for d in pack.docs}
            stale = [str(r[0]) for r in store._exec(SQL_COMMITTED_IDS) if r[0] not in keep]
            if stale:
                store.delete_documents(stale)
            store.set_meta("seed_key", key)
            store.commit()
        except Exception:
            store.rollback()
            raise
        log.info("seeded", extra={"seed_key": key[:12], "docs": len(pack.docs)})
        return warnings
    finally:
        store._exec(SQL_UNLOCK, (ADVISORY_LOCK,))


def is_seeded(store: PgVectorStore, pack: Pack, embedder: Embedder) -> bool:
    """True when the store holds exactly this pack for this embedder (read-only check)."""
    return store.get_meta("seed_key") == seed_key(pack, embedder)


def main(argv: list[str] | None = None) -> int:
    """``python -m stitch_library.store.seed [--check]``: idempotent seed job for Compose.

    Reads ``STITCH_LIBRARY_DSN`` (a role that owns the schema), ``STITCH_EMBED_MODEL``,
    ``STITCH_MODEL_DIR`` and ``STITCH_LIBRARY_PACK``. Applies migrations, then seeds under the
    advisory lock; a second run writes nothing. Prints one JSON line. Exit codes: 0 seeded or
    already seeded, 1 store error, 2 configuration error (no DSN, embedder missing),
    3 ``--check`` found the store not seeded with this pack.
    """
    import argparse
    import json
    import sys
    import time

    from stitch_library.ml.embedder import ModelUnavailable, load_embedder
    from stitch_library.pack import load_pack
    from stitch_library.settings import Settings
    from stitch_library.store.base import StoreError

    parser = argparse.ArgumentParser(prog="python -m stitch_library.store.seed")
    parser.add_argument("--check", action="store_true", help="only report; never write")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings.from_env()
    if not settings.dsn:
        print("seed: STITCH_LIBRARY_DSN is not set", file=sys.stderr)
        return 2
    try:
        embedder = load_embedder(settings.embed_model, settings.model_dir, threads=settings.threads)
    except ModelUnavailable as exc:
        print(f"seed: embedding model unavailable ({exc})", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    pack = load_pack(settings.pack_dir)
    try:
        store = PgVectorStore(settings.dsn, migrate=not args.check)
        try:
            before = store.get_meta("seed_key")
            if args.check:
                ok = is_seeded(store, pack, embedder)
                warnings: list[str] = []
            else:
                warnings = seed(store, pack, embedder)
                ok = True
            stats = store.stats()
        finally:
            store.close()
    except StoreError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        return 1
    key = seed_key(pack, embedder)
    report = {
        "event": "library_seed",
        "mode": "check" if args.check else "seed",
        "seeded": ok,
        "wrote": (not args.check) and before != key,
        "seed_key": key[:12],
        "docs": stats.docs,
        "chunks": stats.chunks,
        "warnings": warnings,
        "seconds": round(time.monotonic() - t0, 2),
    }
    print(json.dumps(report))
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
