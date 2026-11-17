"""Pre-render the demo briefing audio into the Voice organ's prerendered cache (voice task 8).

The spoken scripts are the exact text the Brain sends to ``speak`` for the default demo briefing
(``stitch_brain.api.voice.briefing_script`` over the recorded-organs briefing). They are committed
as ``data/demo/voice/scripts/{en,ur}.txt``. Generated audio is NOT committed: Deepgram's terms do
not clearly permit redistribution (``docs/decisions.md``), so it is written to the git-ignored
cache (``STITCH_VOICE_PRERENDERED_DIR``, default ``data/cache/voice/prerendered``) at deploy time.

    # dev: rebuild the scripts from the Brain (offline, recorded organs) or check they match
    uv run python scripts/prerender_voice.py --build-scripts
    uv run python scripts/prerender_voice.py --check-scripts

    # render (needs DEEPGRAM_API_KEY for English; Urdu needs AZURE_SPEECH_KEY/REGION)
    uv run python scripts/prerender_voice.py --dry-run
    uv run python scripts/prerender_voice.py --env-file .env

    # production, once after deploy (writes into the voice_cache volume)
    docker compose run --rm voice python /app/scripts/prerender_voice.py \
        --out /cache/voice/prerendered

Urdu is never synthesized with an English voice: without Azure the Urdu script is skipped and
the organ answers Urdu ``speak`` with ``UPSTREAM_UNAVAILABLE`` and the "Urdu speech needs Azure"
warning (the UI shows the Urdu text briefing). Keys are never printed.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "data" / "demo" / "voice" / "scripts"
LANGS = ("en", "ur")
KEY_NAMES = ("DEEPGRAM_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION")


def load_env_file(path: Path) -> list[str]:
    """Put the voice keys from a dotenv file into ``os.environ`` (existing values win).
    Returns the names loaded, never the values."""
    loaded: list[str] = []
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if not m or m.group(1) not in KEY_NAMES or os.environ.get(m.group(1)):
            continue
        value = m.group(2).strip().strip('"').strip("'")
        if value:
            os.environ[m.group(1)] = value
            loaded.append(m.group(1))
    return loaded


def brain_scripts() -> dict[str, str]:
    """The Brain's spoken script for the demo briefing in each language (recorded organs)."""
    import asyncio

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


def read_scripts(directory: Path = SCRIPTS_DIR) -> dict[str, str]:
    return {
        lang: (directory / f"{lang}.txt").read_text(encoding="utf-8").strip()
        for lang in LANGS
        if (directory / f"{lang}.txt").is_file()
    }


def _write_index(out: Path, entries: list[dict[str, Any]]) -> None:
    index_path = out / "index.json"
    old: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            old = list(json.loads(index_path.read_text(encoding="utf-8")).get("entries", []))
        except (OSError, ValueError):
            old = []
    keep = {(e["text_sha256"], e["lang"]) for e in entries}
    merged = [e for e in old if (e.get("text_sha256"), e.get("lang")) not in keep] + entries
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"entries": merged}, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, index_path)


def render(scripts: dict[str, str], out: Path, dry_run: bool) -> int:
    from stitch_common.organs.voice import SpeakIn
    from stitch_common.tooling import ToolFailure
    from stitch_voice.core.keys import text_hash
    from stitch_voice.core.normalize import normalize
    from stitch_voice.service import TOOL_VERSION, VoiceService
    from stitch_voice.settings import load_settings

    settings = dataclasses.replace(load_settings(), prerendered_dir=out)
    svc = VoiceService(settings)
    entries: list[dict[str, Any]] = []
    status = 0
    for lang, text in scripts.items():
        chain = [p.name for p in svc.tts if p.supports(lang) and p.available()]  # type: ignore[arg-type]
        chars = len(normalize(text, lang))
        print(f"{lang}: {len(text)} characters of script, {chars} spoken; providers {chain or '-'}")
        if not chain:
            print(f"{lang}: skipped (no live voice; Urdu needs AZURE_SPEECH_KEY/REGION)")
            continue
        if dry_run:
            print(
                f"{lang}: dry run, would use {chars} of {settings.tts_monthly_char_cap} "
                "monthly characters"
            )
            continue
        try:
            outcome = svc.speak(SpeakIn(text=text, lang=lang))
        except ToolFailure as exc:
            print(f"{lang}: failed: {exc.code}: {exc.message}", file=sys.stderr)
            status = 1
            continue
        data = outcome.data
        wav = base64.b64decode(data.audio_b64)
        name = f"{lang}-{text_hash(text)[:8]}.wav"
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(wav)
        entries.append(
            {
                "text_sha256": text_hash(text),
                "lang": lang,
                "voice": data.voice or "",
                "provider": data.provider,
                "file": name,
                "duration_s": data.duration_s,
                "sample_rate": data.sample_rate,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "tool_version": TOOL_VERSION,
            }
        )
        print(
            f"{lang}: wrote {name} ({data.duration_s:.1f} s, {data.provider}:{data.voice}, "
            f"{data.synthesized})"
        )
    if entries:
        _write_index(out, entries)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=None, help="prerendered cache directory")
    parser.add_argument("--scripts", type=Path, default=SCRIPTS_DIR)
    parser.add_argument("--lang", choices=LANGS, action="append", help="default: both")
    parser.add_argument("--env-file", type=Path, default=None, help="load voice keys from it")
    parser.add_argument("--dry-run", action="store_true", help="print sizes, call nothing")
    parser.add_argument("--build-scripts", action="store_true", help="write scripts from Brain")
    parser.add_argument("--check-scripts", action="store_true", help="scripts equal the Brain's")
    args = parser.parse_args(argv)

    if args.build_scripts or args.check_scripts:
        built = brain_scripts()
        if args.build_scripts:
            args.scripts.mkdir(parents=True, exist_ok=True)
            for lang, text in built.items():
                (args.scripts / f"{lang}.txt").write_text(
                    text + "\n", encoding="utf-8", newline="\n"
                )
                print(f"wrote {lang}.txt ({len(text)} characters)")
            return 0
        stale = [
            lang for lang, text in built.items() if read_scripts(args.scripts).get(lang) != text
        ]
        print("scripts match the Brain" if not stale else f"stale scripts: {stale}")
        return 1 if stale else 0

    if args.env_file is not None:
        names = load_env_file(args.env_file)
        print(f"loaded from {args.env_file.name}: {', '.join(names) or 'nothing new'}")
    scripts = read_scripts(args.scripts)
    if args.lang:
        scripts = {k: v for k, v in scripts.items() if k in args.lang}
    if not scripts:
        print(f"no scripts in {args.scripts}", file=sys.stderr)
        return 1
    from stitch_voice.settings import load_settings

    out = args.out or load_settings().prerendered_dir
    return render(scripts, out, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
