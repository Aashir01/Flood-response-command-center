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
