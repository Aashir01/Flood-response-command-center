"""Test helpers (importable as ``voice_helpers``): mocked HTTP, envelopes, prerendered fixtures."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from stitch_common.envelope import ToolResult
from stitch_common.tooling import run_tool
from stitch_voice.core import audio
from stitch_voice.core.keys import text_hash
from stitch_voice.providers.base import STTProvider, TTSProvider
from stitch_voice.providers.deepgram import DeepgramSTT, DeepgramTTS
from stitch_voice.service import TOOL_VERSION, VoiceService
from stitch_voice.settings import load_settings

KEY = "test-key-not-real-0123456789"
Handler = Callable[[httpx.Request], httpx.Response]


def no_sleep(_: float) -> None:
    return None


def client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def wav_response(seconds: float = 0.5, rate: int = 24000) -> httpx.Response:
    return httpx.Response(200, content=audio.tone_wav(seconds, 300.0, rate))


def listen_body(text: str, lang: str | None = None, conf: float = 0.97) -> dict[str, Any]:
    words = [
        {"word": w, "start": 0.1 + i * 0.3, "end": 0.35 + i * 0.3}
        for i, w in enumerate(text.split())
    ]
    channel: dict[str, Any] = {"alternatives": [{"transcript": text, "words": words}]}
    if lang is not None:
        channel["detected_language"] = lang
        channel["language_confidence"] = conf
    end = words[-1]["end"] if words else 0.0
    return {
        "results": {
            "channels": [channel],
            "utterances": [{"start": 0.1, "end": end, "transcript": text}] if words else [],
        }
    }


class Recorder:
    """Mock handler that records requests and plays back a list of responses."""

    def __init__(self, responses: Sequence[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


def deepgram_tts(handler: Handler) -> DeepgramTTS:
    return DeepgramTTS(KEY, client=client(handler), sleep=no_sleep)


def deepgram_stt(handler: Handler) -> DeepgramSTT:
    return DeepgramSTT(KEY, client=client(handler), sleep=no_sleep)


def service(
    tts: Sequence[TTSProvider] | None = None, stt: Sequence[STTProvider] | None = None
) -> VoiceService:
    """A service on the test environment (temporary cache) with the given providers."""
    return VoiceService(load_settings(), tts=tts, stt=stt)


def call(svc: VoiceService, tool: str, args: dict[str, Any]) -> ToolResult[Any]:
    return asyncio.run(run_tool("voice", tool, TOOL_VERSION, svc.cores()[tool], args))


def add_prerendered(root: Path, text: str, lang: str, voice: str, provider: str = "fake") -> bytes:
    """Write one prerendered entry (a tone) and return its bytes."""
    root.mkdir(parents=True, exist_ok=True)
    wav = audio.tone_wav(1.0, 330.0, 24000)
    name = f"{lang}-{text_hash(text)[:8]}.wav"
    (root / name).write_bytes(wav)
    index_path = root / "index.json"
    index: dict[str, Any] = {"entries": []}
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    index["entries"].append(
        {
            "text_sha256": text_hash(text),
            "lang": lang,
            "voice": voice,
            "provider": provider,
            "file": name,
            "duration_s": 1.0,
            "sample_rate": 24000,
            "generated_at": "2026-11-18T00:00:00Z",
            "tool_version": TOOL_VERSION,
        }
    )
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return wav
