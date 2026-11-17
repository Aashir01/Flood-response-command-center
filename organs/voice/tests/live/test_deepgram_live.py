"""Live checks against Deepgram (marker ``live``; excluded from CI; run by hand):

    uv run pytest organs/voice/tests/live -m live -p no:cacheprovider

The key comes from ``DEEPGRAM_API_KEY`` or, failing that, the git-ignored repo-root ``.env``.
It is never printed. Each run costs about 200 TTS characters and about 10 s of STT.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import voice_helpers as h

from stitch_voice.service import URDU_NEEDS_AZURE, VoiceService
from stitch_voice.settings import load_settings

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[4]
SENTENCE = "The Indus at Kotri is rising. Move to higher ground and boil water before drinking."


def _key_from_dotenv() -> str:
    path = ROOT / ".env"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*DEEPGRAM_API_KEY\s*=\s*(.*)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ""


@pytest.fixture
def live_service(monkeypatch: pytest.MonkeyPatch) -> VoiceService:
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip() or _key_from_dotenv()
    if not key:
        pytest.skip("DEEPGRAM_API_KEY is not set")
    monkeypatch.setenv("DEEPGRAM_API_KEY", key)
    monkeypatch.setenv("STITCH_TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("STITCH_STT_PROVIDER", "deepgram")
    for name in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"):
        monkeypatch.delenv(name, raising=False)
    return VoiceService(load_settings())


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def test_live_english_round_trip(live_service: VoiceService) -> None:
    spoken = h.call(live_service, "speak", {"text": SENTENCE, "lang": "en"})
    assert spoken.ok, spoken.error
    assert spoken.data.provider == "deepgram" and spoken.data.synthesized == "live"
    assert spoken.data.sample_rate == 24000 and spoken.data.duration_s > 2.0
    heard = h.call(
        live_service,
        "transcribe",
        {"audio_b64": spoken.data.audio_b64, "format": "wav", "lang_hint": "en"},
    )
    assert heard.ok, heard.error
    assert heard.data.lang == "en" and heard.provenance.mode == "live"
    ref, hyp = _words(SENTENCE), _words(heard.data.text)
    missing = [w for w in ref if w not in hyp]
    # Place names are the weak spot (2026-11-17: "Indus at Kotri" came back as "Indusic co tree").
    assert len(missing) <= len(ref) // 4, (heard.data.text, missing)


def test_live_auto_language_detection_on_english(live_service: VoiceService) -> None:
    spoken = h.call(live_service, "speak", {"text": "Water is rising in Sukkur.", "lang": "en"})
    assert spoken.ok, spoken.error
    heard = h.call(
        live_service, "transcribe", {"audio_b64": spoken.data.audio_b64, "format": "wav"}
    )
    assert heard.ok, heard.error
    assert heard.data.lang == "en" and heard.data.text


def test_live_urdu_speech_is_refused_without_azure(live_service: VoiceService) -> None:
    res = h.call(live_service, "speak", {"text": "دریا کا پانی بڑھ رہا ہے۔", "lang": "ur"})
    assert not res.ok and res.error is not None and res.error.code == "UPSTREAM_UNAVAILABLE"
    assert URDU_NEEDS_AZURE in res.warnings
