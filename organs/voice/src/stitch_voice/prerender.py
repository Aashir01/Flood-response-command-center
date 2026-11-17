"""Pre-render the demo briefing audio into the prerendered cache (voice task 8).

    python -m stitch_voice.prerender --dry-run                   # sizes and budget, no calls
    python -m stitch_voice.prerender --env-file .env             # dev: keys from the dotenv file
    docker compose run --rm voice python -m stitch_voice.prerender --out /cache/voice/prerendered

The scripts are ``data/demo/voice/scripts/{en,ur}.txt``: the exact text the Brain sends to
``speak`` for the default demo briefing (built and checked by ``scripts/prerender_voice.py
--build-scripts`` / ``--check-scripts``). Generated audio is NOT committed: Deepgram's terms do
not clearly permit redistribution (``docs/decisions.md``), so it goes to the git-ignored cache
(``STITCH_VOICE_PRERENDERED_DIR``, default ``data/cache/voice/prerendered``) at deploy time.

Urdu is never synthesized with an English voice: without Azure the Urdu script is skipped and
Urdu ``speak`` answers ``UPSTREAM_UNAVAILABLE`` with the "Urdu speech needs Azure" warning.
Keys are never printed.
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

from stitch_common.organs.voice import SpeakIn
from stitch_common.tooling import ToolFailure
from stitch_voice.core.keys import text_hash
from stitch_voice.core.normalize import normalize
from stitch_voice.service import TOOL_VERSION, VoiceService
from stitch_voice.settings import REPO_ROOT, load_settings

SCRIPTS_DIR = REPO_ROOT / "data" / "demo" / "voice" / "scripts"
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
    """Speak each script through the normal ``speak`` pipeline and index the WAV files."""
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
            cap = settings.tts_monthly_char_cap
            print(f"{lang}: dry run, would use {chars} of {cap} monthly characters")
            continue
        try:
            outcome = svc.speak(SpeakIn(text=text, lang=lang))
        except ToolFailure as exc:
            print(f"{lang}: failed: {exc.code}: {exc.message}", file=sys.stderr)
            status = 1
            continue
        data = outcome.data
        name = f"{lang}-{text_hash(text)[:8]}.wav"
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(base64.b64decode(data.audio_b64))
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


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stitch_voice.prerender", description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, default=None, help="prerendered cache directory")
    p.add_argument("--scripts", type=Path, default=SCRIPTS_DIR)
    p.add_argument("--lang", choices=LANGS, action="append", help="default: both")
    p.add_argument("--env-file", type=Path, default=None, help="load voice keys from it")
    p.add_argument("--dry-run", action="store_true", help="print sizes, call nothing")
    return p


def run_args(args: argparse.Namespace) -> int:
    if args.env_file is not None:
        names = load_env_file(args.env_file)
        print(f"loaded from {args.env_file.name}: {', '.join(names) or 'nothing new'}")
    scripts = read_scripts(args.scripts)
    if args.lang:
        scripts = {k: v for k, v in scripts.items() if k in args.lang}
    if not scripts:
        print(f"no scripts in {args.scripts}", file=sys.stderr)
        return 1
    return render(scripts, args.out or load_settings().prerendered_dir, args.dry_run)


def main(argv: list[str] | None = None) -> int:
    return run_args(parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
