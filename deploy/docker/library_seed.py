"""One-shot Library seed job for Compose (deploy design 7, DEP-R1.3, DEP-P5).

Runs as the schema owner role. Building the Library service with ``STITCH_LIBRARY_STORE=pgvector``
applies the migrations and seeds the committed pack under a Postgres advisory lock; a repeated
run sees the same ``seed_key`` and does nothing ("already seeded"). The runtime ``library``
service then connects as the read-only ``stitch_app`` role.

Prints one JSON line with the seed key and counts; exits non-zero if the index is empty, the
store is not Postgres, or the embedding model fell back to the test embedder.
"""

from __future__ import annotations

import json
import logging
import sys
import time


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from stitch_library.service import LibraryService

    t0 = time.monotonic()
    service = LibraryService.from_env()
    health = service.health()
    checks = service.health_checks()
    report = {
        "event": "library_seed",
        "store": service.store.kind,
        "seed_key": (health.get("seed_key") or "")[:12],
        "startup_warnings": list(service.startup_warnings),
        "checks": checks,
        "seconds": round(time.monotonic() - t0, 1),
    }
    stats = getattr(service.store, "stats", None)
    if callable(stats):
        s = stats()
        report["stats"] = s.__dict__ if hasattr(s, "__dict__") else str(s)
    print(json.dumps(report, default=str))
    if service.store.kind != "pgvector":
        print("seed: STITCH_LIBRARY_STORE must be pgvector", file=sys.stderr)
        return 2
    if not all(checks.values()):
        print(f"seed: unhealthy after seeding: {checks}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
