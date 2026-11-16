"""Scaffold a Stitch organ (MCP server, tests, spec skeleton) from ``.kiro/templates/organ/``.

Usage:
    python scripts/scaffold_organ.py --organ ledger [--tools a,b] [--package stitch_ledger]
                                     [--dry-run] [--force] [--root PATH]

What it writes (nothing else):
* ``organs/<organ>/**`` from the template. Existing files are skipped unless ``--force``.
* ``.kiro/specs/<organ>-mcp/{requirements,design,tasks}.md`` only for files that do not exist.
  Specs are human-authored, so ``--force`` never overwrites them.
* A ``THIRD_PARTY.md`` section for the organ, only if its heading is missing.
* ``.kiro/settings/mcp.json``: sets ``disabled: false`` on ``<organ>-mcp`` (adds the entry if
  absent).
* Root ``pyproject.toml``: removes ``organs/<organ>`` from ``[tool.uv.workspace].exclude``.

The organ must be one of the contract organs and ``--tools`` (default: all) must be exactly the
tools the contract defines for it, because ``check_contracts.py`` requires every contract tool.
Output is deterministic and the second run is a no-op (BOOT-P6). Run ``uv sync --all-packages``
afterwards to install the new package.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_REL = Path(".kiro") / "templates" / "organ"
SPECIAL = {"THIRD_PARTY.section.md.tmpl"}
PREFIXES = {
    "eyes": "EYE",
    "oracle": "ORA",
    "library": "LIB",
    "ledger": "LED",
    "voice": "VOX",
}
SPEC_FILES = ("requirements.md", "design.md", "tasks.md")


@dataclass(frozen=True)
class Action:
    kind: str  # create | overwrite | skip | edit | unchanged
    path: str  # repo-relative, POSIX
    content: str | None = None  # None for skip/unchanged

    def __str__(self) -> str:
        note = {"skip": " (exists)", "unchanged": " (already done)"}.get(self.kind, "")
        return f"{self.kind:<9} {self.path}{note}"


class ScaffoldError(Exception):
    pass


def _contract_tools() -> dict[str, dict[str, tuple[str, str]]]:
    from stitch_common.organs import ORGAN_TOOLS

    return {
        organ: {t: (s.input.__name__, s.output.__name__) for t, s in tools.items()}
        for organ, tools in ORGAN_TOOLS.items()
    }


def _context(organ: str, package: str, tools: list[str]) -> dict[str, str]:
    from stitch_common import CONTRACT_VERSION

    names = ", ".join(f'"{t}"' for t in tools)
    return {
        "organ": organ,
        "Organ": organ.capitalize(),
        "package": package,
        "dist": f"stitch-{organ}",
        "server_name": f"{organ}-mcp",
        "spec": f"{organ}-mcp",
        "prefix": PREFIXES[organ],
        "contract_version": CONTRACT_VERSION,
        "tools_tuple": f"({names},)" if len(tools) == 1 else f"({names})",
        "core_imports": "\n".join(
            f"from {package}.core.{t} import run as {t}" for t in sorted(tools)
        ),
        "core_registry": "\n".join(f'    "{t}": {t},' for t in tools),
        "first_tool": tools[0],
        "tool_bullets": "\n".join(f"- `{t}`" for t in tools),
    }


def _render(text: str, ctx: dict[str, str]) -> str:
    return Template(text).substitute(ctx)


def _dest_path(rel: Path, ctx: dict[str, str]) -> str:
    parts = []
    for part in rel.parts:
        for token in ("organ", "package", "spec"):
            part = part.replace(f"__{token}__", ctx[token])
        parts.append(part)
    name = "/".join(parts)
    return name[: -len(".tmpl")] if name.endswith(".tmpl") else name


def _read(root: Path, rel: str) -> str | None:
    p = root / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def _file_action(root: Path, rel: str, content: str, force: bool, protect: bool) -> Action:
    existing = _read(root, rel)
    if existing is None:
        return Action("create", rel, content)
    if existing == content:
        return Action("unchanged", rel)
    if force and not protect:
        return Action("overwrite", rel, content)
    return Action("skip", rel)


def plan(
    root: Path,
    organ: str,
    tools: list[str] | None = None,
    package: str | None = None,
    force: bool = False,
) -> list[Action]:
    contract = _contract_tools()
    if organ not in contract:
        raise ScaffoldError(f"unknown organ {organ!r}; contract organs: {sorted(contract)}")
    expected = list(contract[organ])
    tools = tools or expected
    if sorted(tools) != sorted(expected):
        raise ScaffoldError(
            f"--tools must be exactly the contract tools for {organ}: {expected} (got {tools})"
        )
    package = package or f"stitch_{organ}"
    if package != f"stitch_{organ}":
        raise ScaffoldError(f"package must be stitch_{organ} (got {package!r})")
    tools = expected  # contract order, deterministic
    ctx = _context(organ, package, tools)

    template_root = root / TEMPLATE_REL
    if not template_root.is_dir():
        raise ScaffoldError(f"template directory not found: {TEMPLATE_REL.as_posix()}")

    actions: list[Action] = []
    for src in sorted(p for p in template_root.rglob("*") if p.is_file()):
        rel = src.relative_to(template_root)
        if rel.name in SPECIAL:
            continue
        text = src.read_text(encoding="utf-8")
        if "__tool__" in rel.name:
            for tool in tools:
                tctx = {**ctx, "tool": tool}
                tctx["in_model"], tctx["out_model"] = contract[organ][tool]
                dest = _dest_path(Path(str(rel).replace("__tool__", tool)), tctx)
                actions.append(_file_action(root, dest, _render(text, tctx), force, protect=False))
            continue
        dest = _dest_path(rel, ctx)
        is_spec = dest.startswith(".kiro/specs/")
        actions.append(_file_action(root, dest, _render(text, ctx), force, protect=is_spec))

    actions.append(_third_party(root, ctx))
    actions.append(_mcp_json(root, organ, package))
    actions.append(_root_pyproject(root, organ))
    _check_allowed(actions, organ, ctx["spec"])
    return actions


def _third_party(root: Path, ctx: dict[str, str]) -> Action:
    rel = "THIRD_PARTY.md"
    section = _render(
        (root / TEMPLATE_REL / "THIRD_PARTY.section.md.tmpl").read_text(encoding="utf-8"), ctx
    )
    heading = section.splitlines()[0]
    existing = _read(root, rel)
    if existing is None:
        return Action("skip", rel)
    if heading in existing.splitlines():
        return Action("unchanged", rel)
    return Action("edit", rel, existing.rstrip("\n") + "\n" + section.rstrip("\n") + "\n")


def _mcp_json(root: Path, organ: str, package: str) -> Action:
    rel = ".kiro/settings/mcp.json"
    existing = _read(root, rel)
    if existing is None:
        return Action("skip", rel)
    data = json.loads(existing)
    servers = data.setdefault("mcpServers", {})
    entry = servers.get(f"{organ}-mcp") or {
        "command": "uv",
        "args": [
            "run",
            "--package",
            f"stitch-{organ}",
            "python",
            "-m",
            f"{package}.server",
            "--stdio",
        ],
        "env": {"STITCH_MODE": "demo"},
    }
    entry["disabled"] = False
    servers[f"{organ}-mcp"] = entry
    new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return Action("unchanged", rel) if new == existing else Action("edit", rel, new)


def _root_pyproject(root: Path, organ: str) -> Action:
    rel = "pyproject.toml"
    existing = _read(root, rel)
    if existing is None:
        return Action("skip", rel)
    pattern = re.compile(rf'^[ \t]*"organs/{re.escape(organ)}",?[ \t]*\n', re.MULTILINE)
    new = pattern.sub("", existing)
    return Action("unchanged", rel) if new == existing else Action("edit", rel, new)


def _check_allowed(actions: list[Action], organ: str, spec: str) -> None:
    allowed_prefixes = (f"organs/{organ}/", f".kiro/specs/{spec}/")
    allowed_files = {"THIRD_PARTY.md", ".kiro/settings/mcp.json", "pyproject.toml"}
    for a in actions:
        if not (a.path.startswith(allowed_prefixes) or a.path in allowed_files) or ".." in a.path:
            raise ScaffoldError(f"refusing to touch {a.path}")


def apply(root: Path, actions: list[Action]) -> None:
    for a in actions:
        if a.kind in ("create", "overwrite", "edit") and a.content is not None:
            dest = root / a.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(a.content, encoding="utf-8", newline="\n")


def scaffold(
    root: Path,
    organ: str,
    tools: list[str] | None = None,
    package: str | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> list[Action]:
    actions = plan(root, organ, tools, package, force)
    if not dry_run:
        apply(root, actions)
    return actions


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Scaffold a Stitch organ.")
    parser.add_argument("--organ", required=True)
    parser.add_argument("--package", default=None)
    parser.add_argument("--tools", default=None, help="comma-separated; default all contract tools")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing organ files")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    tools = [t.strip() for t in args.tools.split(",") if t.strip()] if args.tools else None
    try:
        actions = scaffold(
            args.root, args.organ, tools, args.package, dry_run=args.dry_run, force=args.force
        )
    except ScaffoldError as exc:
        print(f"scaffold_organ: {exc}", file=sys.stderr)
        return 2
    for a in actions:
        print(("would " if args.dry_run else "") + str(a))
    skipped = sum(1 for a in actions if a.kind == "skip")
    changed = sum(1 for a in actions if a.kind in ("create", "overwrite", "edit"))
    print(
        f"scaffold_organ: {'dry run: ' if args.dry_run else ''}{changed} change(s), "
        f"{skipped} skipped. "
        + ("Use --force to overwrite existing organ files. " if skipped else "")
        + "Next: uv sync --all-packages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
