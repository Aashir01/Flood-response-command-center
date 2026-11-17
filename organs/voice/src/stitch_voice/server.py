"""MCP server for voice-mcp (contract v0.5, ``mcp-contracts.md`` section 7).

Thin layer: validation, the ``ToolResult`` envelope and ``GET /healthz`` come from
``stitch_common.mcp_app``; tool logic lives in ``stitch_voice.service`` (provider chains, cache,
budget) and ``stitch_voice.core`` (pure normalization, splitting, audio, guards).

    python -m stitch_voice.server --stdio
    python -m stitch_voice.server --http --host 127.0.0.1 --port 8000   # also serves GET /healthz

Environment: ``STITCH_TTS_PROVIDER`` (``deepgram`` default, ``prerendered``, ``fake``),
``STITCH_STT_PROVIDER`` (``whisper`` default, ``deepgram``, ``fake``), ``DEEPGRAM_API_KEY``,
``AZURE_SPEECH_KEY``/``AZURE_SPEECH_REGION`` (Urdu speech), ``STITCH_VOICE_CACHE_DIR``,
``STITCH_VOICE_PRERENDERED_DIR``. See ``organs/voice/README.md``.
"""

from __future__ import annotations

from stitch_common.mcp_app import ContractServer, serve
from stitch_voice.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_voice.service import TOOL_VERSION, VoiceService

DESCRIPTIONS = {
    "transcribe": (
        "Transcribe a short spoken question (wav, webm, mp3 or ogg; at most 60 s and 10 MB) "
        "in English or Urdu. Uses local Whisper by default, or Deepgram Nova-3 when "
        "STITCH_STT_PROVIDER=deepgram. Silence returns empty text with the NO_SPEECH warning."
    ),
    "speak": (
        "Speak briefing text (at most 4000 characters) as WAV. English uses Deepgram Aura-2 "
        "when keyed; Urdu uses Azure when keyed, else the pre-rendered demo audio, else "
        "UPSTREAM_UNAVAILABLE. Urdu is never read by an English voice. Audio is AI-generated."
    ),
}

__all__ = ["TOOL_NAMES", "TOOL_SCHEMAS", "TOOL_VERSION", "create_server", "main"]


def create_server(service: VoiceService | None = None) -> ContractServer:
    svc = service if service is not None else VoiceService()
    return ContractServer(
        organ="voice",
        tool_version=TOOL_VERSION,
        cores=svc.cores(),
        descriptions=DESCRIPTIONS,
        health_checks=svc.health,
        health_meta=svc.meta,
    )


def main(argv: list[str] | None = None) -> int:
    return serve(create_server(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
