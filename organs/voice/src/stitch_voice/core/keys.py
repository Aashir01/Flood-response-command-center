"""Cache keys (VOX-R3.2, design 5)."""

from __future__ import annotations

import hashlib
import json

# Bump when normalization, splitting or joining changes, so stale audio is never served.
PIPELINE_VERSION = "1"


def cache_key(text: str, lang: str, voice: str, provider: str, fmt: str = "wav") -> str:
    payload = {
        "text": text,
        "lang": lang,
        "voice": voice,
        "provider": provider,
        "format": fmt,
        "pipeline_version": PIPELINE_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    """Key of the prerendered index: the raw text only (lookup also checks ``lang``)."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
