"""Pre-render the demo briefing audio (voice task 8). Dev wrapper around
``python -m stitch_voice.prerender`` that can also build the spoken scripts from the Brain.

    uv run python scripts/prerender_voice.py --build-scripts     # write data/demo/voice/scripts
    uv run python scripts/prerender_voice.py --check-scripts     # fail when they drift
    uv run python scripts/prerender_voice.py --dry-run           # sizes and budget, no calls
    uv run python scripts/prerender_voice.py --env-file .env     # render into data/cache/voice

In Compose (the image has no ``scripts/``):

    docker compose run --rm voice python -m stitch_voice.prerender --out /cache/voice/prerendered

The scripts are the exact text ``stitch_brain.api.voice.briefing_script`` builds for the default
demo briefing with recorded organs, so a prerendered lookup matches what the Brain sends.
Generated audio is never committed (``docs/decisions.md``). Keys are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from stitch_voice.prerender import (
    KEY_NAMES,
    LANGS,
    load_env_file,
    parser,
    read_scripts,
    render,
    run_args,
)

__all__ = ["KEY_NAMES", "brain_scripts", "load_env_file", "main", "read_scripts", "render"]


def brain_scripts() -> dict[str, str]:
    """The Brain's spoken script for the demo briefing in each language (recorded organs)."""
    from stitch_brain.api.voice import briefing_script
    from stitch_brain.cli import _run  # the CLI's own briefing path

    out: dict[str, str] = {}
    for lang in LANGS:
        ns = argparse.Namespace(
            scenario="demo-sindh-2022",
            lang=lang,
            mode="demo",
            organs="recorded",
            connect_timeout=60.0,
        )
        out[lang] = briefing_script(asyncio.run(_run(ns)))
    return out


def main(argv: list[str] | None = None) -> int:
    p = parser()
    p.add_argument("--build-scripts", action="store_true", help="write scripts from the Brain")
    p.add_argument("--check-scripts", action="store_true", help="scripts equal the Brain's")
    args = p.parse_args(argv)
    scripts_dir: Path = args.scripts
    if args.build_scripts:
        scripts_dir.mkdir(parents=True, exist_ok=True)
        for lang, text in brain_scripts().items():
            (scripts_dir / f"{lang}.txt").write_text(text + "\n", encoding="utf-8", newline="\n")
            print(f"wrote {lang}.txt ({len(text)} characters)")
        return 0
    if args.check_scripts:
        committed = read_scripts(scripts_dir)
        stale = [lang for lang, text in brain_scripts().items() if committed.get(lang) != text]
        print("scripts match the Brain" if not stale else f"stale scripts: {stale}")
        return 1 if stale else 0
    return run_args(args)


if __name__ == "__main__":
    raise SystemExit(main())
