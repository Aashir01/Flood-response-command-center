"""Serve pre-rendered demo audio only (VOX-R7.3). Index: ``<root>/index.json``.

Index entries: ``{"text_sha256", "lang", "voice", "provider", "file", "duration_s",
"sample_rate", "generated_at", "tool_version"}``. Lookup is by ``sha256(text.strip())`` and
``lang`` (and ``voice`` when one is requested). Unknown text raises ``NotFound``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stitch_voice.core.keys import text_hash
from stitch_voice.providers.base import Lang, NotFound


@dataclass(frozen=True)
class PrerenderedAudio:
    wav: bytes
    sample_rate: int
    duration_s: float
    voice: str
    source_provider: str


class PrerenderedStore:
    name = "prerendered"
    hosted = False

    def __init__(self, root: Path) -> None:
        self.root = root

    def _index(self) -> list[dict[str, Any]]:
        path = self.root / "index.json"
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        entries = data.get("entries", []) if isinstance(data, dict) else []
        return [e for e in entries if isinstance(e, dict)]

    def count(self) -> int:
        return len(self._index())

    def lookup(self, text: str, lang: Lang, voice: str | None = None) -> PrerenderedAudio:
        digest = text_hash(text)
        for entry in self._index():
            if entry.get("text_sha256") != digest or entry.get("lang") != lang:
                continue
            if voice and entry.get("voice") != voice:
                continue
            file = (self.root / str(entry.get("file", ""))).resolve()
            if self.root.resolve() not in file.parents or not file.is_file():
                continue
            return PrerenderedAudio(
                wav=file.read_bytes(),
                sample_rate=int(entry.get("sample_rate", 0)) or 24000,
                duration_s=float(entry.get("duration_s", 0.0)),
                voice=str(entry.get("voice", "")),
                source_provider=str(entry.get("provider", "")),
            )
        raise NotFound("no pre-rendered audio for this text")
