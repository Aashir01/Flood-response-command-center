"""Capture real organ results as Brain recorded fixtures (brain design 3.3, task 30).

    uv run python scripts/record_organ_fixture.py --organ ledger --scenario demo-sindh-2022
    uv run python scripts/record_organ_fixture.py --organ ledger --transport stdio

The organ runs in demo mode with no network. ``--transport inproc`` (default) calls the organ's
service in this process through ``stitch_common.tooling.run_tool`` (the same envelope code the
MCP server uses); ``stdio`` starts ``python -m stitch_<organ>.server --stdio`` and calls it over
MCP. Fixtures are written to ``data/demo/recorded/<organ>/<tool>/<scenario>-<variant>.json``
with ``authoring = captured`` and the full call arguments in ``match.args``, so a fixture never
answers a call it was not computed for.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(REPO).as_posix()}")


def _fixture(
    scenario: str,
    args: dict[str, Any],
    result: dict[str, Any],
    transport: str,
    run_id_of: str | None = None,
    organ: str = "ledger",
) -> dict[str, Any]:
    match: dict[str, Any] = {"scenario": scenario, "exact": True, "args": args}
    if run_id_of is not None:
        match = {"scenario": scenario, "run_id_of": run_id_of, "args": {}}
    return {
        "match": match,
        "authoring": "captured",
        "captured_from": {
            "organ_version": version(f"stitch-{organ}"),
            "transport": transport,
            "date": datetime.now(UTC).date().isoformat(),
            "mode": "demo",
        },
        "result": result,
    }


class LedgerCaller:
    """Calls the Ledger in-process (``inproc``) or over MCP stdio."""

    def __init__(self, transport: str) -> None:
        self.transport = transport
        self._client: Any = None
        self._service: Any = None

    async def __aenter__(self) -> LedgerCaller:
        if self.transport == "inproc":
            from stitch_ledger.service import LedgerService

            self._service = LedgerService()
        else:
            from mcp import Client, StdioServerParameters

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "stitch_ledger.server", "--stdio"],
                env={**os.environ, "STITCH_MODE": "demo"},
            )
            self._client = await Client(params, read_timeout_seconds=120).__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if self._service is not None:
            from stitch_common.tooling import run_tool

            core = self._service.cores()[tool]
            res = await run_tool("ledger", tool, version("stitch-ledger"), core, args)
            out: dict[str, Any] = res.model_dump(mode="json")
            return out
        raw = await self._client.call_tool(tool, args)
        return dict(raw.structured_content)

    def districts(self, scenario_id: str) -> list[dict[str, Any]]:
        if self._service is None:
            from stitch_ledger.service import LedgerService

            self._service = LedgerService()
        return [d.model_dump(mode="json") for d in self._service.scenario_districts(scenario_id)]


async def record_ledger(
    scenario_id: str, transport: str, variants: dict[str, dict[str, Any] | None]
) -> None:
    from stitch_brain.config import load_scenarios
    from stitch_brain.runtime.organs import wrap_resource

    scenario = load_scenarios()[scenario_id]
    root = REPO / "data" / "demo" / "recorded" / "ledger"
    async with LedgerCaller(transport) as ledger:
        uri = f"ledger://scenario/{scenario.ledger_scenario_id}/districts"
        res = wrap_resource("ledger", uri, ledger.districts(scenario.ledger_scenario_id))
        _write(
            root / "resource_districts" / f"{scenario.ledger_scenario_id}.json",
            {
                "match": {"args": {"uri": uri}},
                "authoring": "captured",
                "captured_from": {"organ_version": version("stitch-ledger"), "transport": "inproc"},
                "result": res,
            },
        )
        for variant, args in variants.items():
            if args is None:
                print(f"skip {variant}: inputs unavailable")
                continue
            opt = await ledger.call("optimize_allocation", args)
            name = f"{scenario_id}-{variant}.json"
            opt_rel = f"data/demo/recorded/ledger/optimize_allocation/{name}"
            _write(REPO / opt_rel, _fixture(scenario_id, args, opt, transport))
            if opt.get("ok"):
                sens_args = {"run_id": opt["provenance"]["run_id"]}
                sens = await ledger.call("sensitivity_report", sens_args)
                _write(
                    root / "sensitivity_report" / name,
                    _fixture(scenario_id, {}, sens, transport, run_id_of=opt_rel),
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organ", default="ledger", choices=["ledger"])
    parser.add_argument("--scenario", default="demo-sindh-2022")
    parser.add_argument("--transport", default="inproc", choices=["inproc", "stdio"])
    parser.add_argument("--variants", default="defaults,full,eyes_only")
    args = parser.parse_args(argv)
    os.environ.setdefault("STITCH_MODE", "demo")
    from stitch_brain.config import load_scenarios
    from stitch_brain.offline import ledger_variant_args

    scenario = load_scenarios()[args.scenario]
    variants = {v: ledger_variant_args(scenario, v) for v in args.variants.split(",")}
    asyncio.run(record_ledger(args.scenario, args.transport, variants))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
