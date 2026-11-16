"""Command line: ``python -m stitch_brain.cli run --scenario demo-sindh-2022 --lang en``.

``--organs recorded`` serves every organ from ``data/demo/recorded`` (no organ processes, no
sockets). ``--organs real`` uses ``config/organs.yaml`` and ``STITCH_RECORDED_ORGANS``. A comma
list (``--organs eyes,oracle``) records just those organs and runs the others for real.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from stitch_brain.config import load_organs, load_scenarios
from stitch_brain.runtime.registry import OrganRegistry
from stitch_brain.runtime.runner import BriefingRunner
from stitch_brain.settings import Settings
from stitch_common.brain_api import BriefingRequest


def _settings(organs: str) -> Settings:
    s = Settings.from_env()
    if organs == "recorded":
        return replace(s, recorded_organs=("all",))
    if organs == "real":
        return s
    return replace(s, recorded_organs=tuple(x.strip() for x in organs.split(",") if x.strip()))


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings(args.organs)
    scenario = load_scenarios()[args.scenario]
    organs_cfg = None if settings.recorded_all else load_organs()
    registry = OrganRegistry.build(settings, organs_cfg)
    await registry.start()
    try:
        for c in registry.clients.values():
            wait = getattr(c, "wait_connected", None)
            if wait is not None:
                await wait(args.connect_timeout)
        req = BriefingRequest(
            region=scenario.region, scenario=scenario.id, lang=args.lang, mode=args.mode
        )
        runner = BriefingRunner(registry, settings=settings)
        result = await runner.run(req, str(uuid.uuid4()))
    finally:
        await registry.close()
    assert result.briefing is not None
    return result.briefing.model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stitch_brain.cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="produce one briefing and print it as JSON")
    run.add_argument("--scenario", default="demo-sindh-2022")
    run.add_argument("--lang", default="en", choices=["en", "ur"])
    run.add_argument("--mode", default="demo", choices=["demo", "live"])
    run.add_argument("--organs", default="recorded")
    run.add_argument("--connect-timeout", type=float, default=60.0)
    run.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.cmd == "run":
        briefing = asyncio.run(_run(args))
        text = json.dumps(briefing, indent=2, ensure_ascii=False)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
        else:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
