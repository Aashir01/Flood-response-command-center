"""Start MCP servers from ``.kiro/settings/mcp.json`` and send ``initialize`` over stdio.

    uv run python scripts/mcp_probe.py                  # every enabled stdio server
    uv run python scripts/mcp_probe.py filesystem fetch # named servers (even if disabled)
    uv run python scripts/mcp_probe.py --timeout 120 --json

Exit 0 when every probed server answered; 1 otherwise. Remote (``url``) servers are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".kiro" / "settings" / "mcp.json"
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(value: str) -> str:
    return VAR.sub(lambda m: os.environ.get(m.group(1), ""), value)


def select(servers: dict[str, dict[str, Any]], names: list[str]) -> dict[str, dict[str, Any]]:
    """Named servers, or every enabled stdio server when no names are given."""
    if names:
        missing = [n for n in names if n not in servers]
        if missing:
            raise SystemExit(f"unknown server(s): {', '.join(missing)}")
        return {n: servers[n] for n in names}
    return {n: s for n, s in servers.items() if not s.get("disabled", False) and "command" in s}


async def probe(name: str, cfg: dict[str, Any], timeout: float) -> dict[str, Any]:
    if "command" not in cfg:
        return {"server": name, "ok": False, "detail": "remote server, not probed"}
    params = StdioServerParameters(
        command=expand(cfg["command"]),
        args=[expand(a) for a in cfg.get("args", [])],
        env={**os.environ, **{k: expand(v) for k, v in cfg.get("env", {}).items()}},
        cwd=REPO_ROOT,
    )
    try:
        async with asyncio.timeout(timeout):
            async with Client(params, read_timeout_seconds=timeout) as client:
                info = client.server_info
                if info is None:
                    return {"server": name, "ok": False, "detail": "no server_info"}
                return {"server": name, "ok": True, "detail": f"{info.name} {info.version}"}
    except Exception as exc:
        return {"server": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


async def run(names: list[str], timeout: float, config: Path = CONFIG) -> list[dict[str, Any]]:
    servers = json.loads(config.read_text(encoding="utf-8")).get("mcpServers", {})
    return [await probe(n, c, timeout) for n, c in select(servers, names).items()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("servers", nargs="*")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)
    results = asyncio.run(run(args.servers, args.timeout, args.config))
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['server']}: {r['detail']}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
