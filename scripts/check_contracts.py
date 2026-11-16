"""Check the committed contract schemas, lock file, markdown contract and organ tool schemas.

Usage:
    python scripts/check_contracts.py [--root PATH] [--update]

Checks (exit 1 with a readable diff on any failure):
1. every schema generated from the ``stitch_common`` models equals the committed file and the
   hash in ``packages/stitch_common/contracts.lock.json`` (added, removed and changed are listed);
2. ``CONTRACT_VERSION`` equals the version in the ``# MCP contracts (vX.Y)`` heading of
   ``.kiro/steering/mcp-contracts.md`` and equals the lock's ``contract_version``, and the change
   log has an entry ``- X.Y`` for it;
3. every organ under ``organs/`` that exposes ``stitch_<organ>.models.TOOL_SCHEMAS`` has exactly
   the contract's tools, with input schemas equal to the exported ones.

The markdown is documentation. Only its version heading and change log are machine-checked; the
Pydantic models and the lock are the machine contract.

``--update`` rewrites the lock and schema files after checks 2 and 3 pass.
"""

from __future__ import annotations

import argparse
import difflib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_REL = Path("packages") / "stitch_common"
LOCK_NAME = "contracts.lock.json"
MD_REL = Path(".kiro") / "steering" / "mcp-contracts.md"

HEADING_RE = re.compile(r"^# MCP contracts \(v(\d+\.\d+)\)\s*$", re.MULTILINE)


def _generated() -> tuple[str, dict[str, dict[str, Any]]]:
    from stitch_common import CONTRACT_VERSION
    from stitch_common.schemas import all_schemas

    return CONTRACT_VERSION, all_schemas()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(schema: dict[str, Any]) -> str:
    from stitch_common.schemas import dump_schema

    return dump_schema(schema)


def _hash(schema: dict[str, Any]) -> str:
    from stitch_common.schemas import schema_hash

    return schema_hash(schema)


def _diff(name: str, old: dict[str, Any], new: dict[str, Any]) -> str:
    return "".join(
        difflib.unified_diff(
            _dump(old).splitlines(keepends=True),
            _dump(new).splitlines(keepends=True),
            fromfile=f"committed/{name}",
            tofile=f"generated/{name}",
        )
    )


def check_schemas(root: Path, version: str, schemas: dict[str, dict[str, Any]]) -> list[str]:
    """Compare generated schemas with the schema files and the lock file."""
    problems: list[str] = []
    common = root / COMMON_REL
    schema_dir = common / "schemas"
    lock_path = common / LOCK_NAME
    if not lock_path.exists():
        return [f"missing {lock_path.relative_to(root)} (run with --update)"]
    lock = _read_json(lock_path)
    locked: dict[str, str] = lock.get("schemas", {})
    if lock.get("contract_version") != version:
        problems.append(
            f"lock contract_version {lock.get('contract_version')!r} != "
            f"CONTRACT_VERSION {version!r}"
        )
    on_disk = {p.name: p for p in schema_dir.glob("*.json")} if schema_dir.exists() else {}

    for name in sorted(set(schemas) - set(locked)):
        problems.append(f"schema added without lock entry: {name}")
    for name in sorted(set(locked) - set(schemas)):
        problems.append(f"schema removed from models but still locked: {name}")
    for name in sorted(set(on_disk) - set(schemas)):
        problems.append(f"stale schema file with no model: {name}")
    for name in sorted(set(schemas) - set(on_disk)):
        problems.append(f"schema file missing on disk: {name}")

    for name in sorted(set(schemas) & set(locked)):
        if _hash(schemas[name]) != locked[name]:
            before = _read_json(on_disk[name]) if name in on_disk else {}
            problems.append(
                f"schema changed without lock update: {name}\n" + _diff(name, before, schemas[name])
            )
    for name in sorted(set(schemas) & set(on_disk)):
        if name in locked and _hash(schemas[name]) != locked[name]:
            continue  # already reported
        if _read_json(on_disk[name]) != schemas[name]:
            problems.append(
                f"schema file differs from models: {name}\n"
                + _diff(name, _read_json(on_disk[name]), schemas[name])
            )
    return problems


def check_markdown(root: Path, version: str) -> list[str]:
    path = root / MD_REL
    if not path.exists():
        return [f"missing {MD_REL.as_posix()}"]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    m = HEADING_RE.search(text)
    if not m:
        return [f"{MD_REL.as_posix()}: no heading like '# MCP contracts (vX.Y)'"]
    if m.group(1) != version:
        problems.append(f"CONTRACT_VERSION {version!r} != markdown heading version {m.group(1)!r}")
    log_entry = re.compile(rf"^- {re.escape(version)}\b", re.MULTILINE)
    after_log = text.split("## 9. Change log", 1)
    if len(after_log) < 2 or not log_entry.search(after_log[1]):
        problems.append(f"change log has no entry starting '- {version}'")
    return problems


_CHILD = """
import json, sys
sys.path.insert(0, sys.argv[1])
import importlib
mod = importlib.import_module(sys.argv[2])
print(json.dumps(mod.TOOL_SCHEMAS, sort_keys=True))
"""


def check_organs(root: Path, schemas: dict[str, dict[str, Any]]) -> list[str]:
    """Compare each organ's ``TOOL_SCHEMAS`` with the exported input schemas."""
    problems: list[str] = []
    organs_dir = root / "organs"
    if not organs_dir.is_dir():
        return problems
    for organ_dir in sorted(p for p in organs_dir.iterdir() if p.is_dir()):
        organ = organ_dir.name
        src = organ_dir / "src"
        if not (organ_dir / "pyproject.toml").exists() or not (src / f"stitch_{organ}").is_dir():
            continue
        res = subprocess.run(
            [sys.executable, "-c", _CHILD, str(src), f"stitch_{organ}.models"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        if res.returncode != 0:
            tail = res.stderr.strip().splitlines()[-1:] or ["(no stderr)"]
            problems.append(f"organ {organ}: cannot import TOOL_SCHEMAS: {tail[0]}")
            continue
        got: dict[str, Any] = json.loads(res.stdout.strip().splitlines()[-1])
        expected = {
            n.split(".")[1]: s
            for n, s in schemas.items()
            if n.startswith(f"{organ}.") and n.endswith(".in.json")
        }
        for tool in sorted(set(expected) - set(got)):
            problems.append(
                f"organ {organ}: tool {tool} is in the contract but not in TOOL_SCHEMAS"
            )
        for tool in sorted(set(got) - set(expected)):
            problems.append(f"organ {organ}: tool {tool} is not in the contract")
        for tool in sorted(set(got) & set(expected)):
            if got[tool] != expected[tool]:
                problems.append(
                    f"organ {organ}: input schema of {tool} differs from the exported schema\n"
                    + _diff(f"{organ}.{tool}.in.json", expected[tool], got[tool])
                )
    return problems


def write_schemas(root: Path, version: str, schemas: dict[str, dict[str, Any]]) -> None:
    """Write schema files and the lock. Removes stale schema files."""
    common = root / COMMON_REL
    schema_dir = common / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    for stale in schema_dir.glob("*.json"):
        if stale.name not in schemas:
            stale.unlink()
    for name, schema in schemas.items():
        (schema_dir / name).write_text(_dump(schema), encoding="utf-8", newline="\n")
    lock = {
        "contract_version": version,
        "schemas": {n: _hash(s) for n, s in sorted(schemas.items())},
    }
    (common / LOCK_NAME).write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def run_checks(
    root: Path,
    version: str,
    schemas: dict[str, dict[str, Any]],
    *,
    update: bool = False,
) -> list[str]:
    """Run all checks. With ``update``, rewrite lock and schemas if checks 2 and 3 pass."""
    problems = check_markdown(root, version) + check_organs(root, schemas)
    if update:
        if problems:
            return problems
        write_schemas(root, version, schemas)
        return []
    return problems + check_schemas(root, version, schemas)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--update", action="store_true", help="rewrite lock and schema files")
    args = parser.parse_args(argv)
    version, schemas = _generated()
    problems = run_checks(args.root, version, schemas, update=args.update)
    if problems:
        print(f"check_contracts: {len(problems)} problem(s)\n", file=sys.stderr)
        for p in problems:
            print(f"- {p}\n", file=sys.stderr)
        return 1
    print(
        f"check_contracts: ok (contract v{version}, {len(schemas)} schemas"
        f"{', lock updated' if args.update else ''})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
