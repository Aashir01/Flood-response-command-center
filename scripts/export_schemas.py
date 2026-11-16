"""Write every contract schema and the lock file without running the other checks.

Usage: python scripts/export_schemas.py [--root PATH]
Prefer ``check_contracts.py --update`` after an intentional contract change: it also verifies the
markdown version and the organ schemas first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from check_contracts import REPO_ROOT, _generated, write_schemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export contract JSON Schemas and the lock.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    version, schemas = _generated()
    write_schemas(args.root, version, schemas)
    print(f"export_schemas: wrote {len(schemas)} schemas for contract v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
