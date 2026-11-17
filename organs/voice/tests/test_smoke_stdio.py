"""Smoke tests: start the server over stdio with the ``fake`` providers, list tools, call both,
check the envelopes; serve ``GET /healthz`` from the streamable HTTP app. Refs: VOX-R5.1, task 7."""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from starlette.testclient import TestClient

from stitch_common import CONTRACT_VERSION
from stitch_common.envelope import ToolResult
from stitch_common.organs.voice import SpeakOut, TranscribeOut
from stitch_voice.core import audio
from stitch_voice.models import TOOL_NAMES
from stitch_voice.server import create_server

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _params(cache: Path) -> StdioServerParameters:
    env = {
        "PYTHONPATH": SRC,
        "STITCH_MODE": "demo",
        "STITCH_TTS_PROVIDER": "fake",
        "STITCH_STT_PROVIDER": "fake",
        "STITCH_VOICE_CACHE_DIR": str(cache),
    }
    for name in ("SYSTEMROOT", "PATH"):  # Windows needs SYSTEMROOT
        if os.environ.get(name):
            env[name] = os.environ[name]
    return StdioServerParameters(
        command=sys.executable, args=["-m", "stitch_voice.server", "--stdio"], env=env
    )


async def test_stdio_lists_tools_and_calls_both(voice_env: Path) -> None:
    clip = base64.b64encode(audio.tone_wav(1.0, 440.0, 16000)).decode("ascii")
    async with Client(_params(voice_env), read_timeout_seconds=60) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        spoken = await client.call_tool("speak", {"text": "The river is rising.", "lang": "en"})
        heard = await client.call_tool("transcribe", {"audio_b64": clip, "format": "wav"})
    s_env = ToolResult[SpeakOut].model_validate(spoken.structured_content)
    assert s_env.ok and s_env.data is not None and s_env.provenance.organ == "voice"
    assert s_env.data.provider == "fake" and s_env.data.duration_s > 0
    t_env = ToolResult[TranscribeOut].model_validate(heard.structured_content)
    assert t_env.ok and t_env.data is not None and t_env.provenance.tool == "transcribe"
    assert t_env.data.text


def test_healthz_reports_voice_meta() -> None:
    client = TestClient(create_server().streamable_http_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["organ"] == "voice"
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["tools"] == ["speak", "transcribe"]
    meta = body["meta"]
    assert meta["capabilities"] == ["speak", "transcribe"]
    assert meta["tts_provider"] == "fake" and meta["hosted"] is False
