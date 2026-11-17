"""Provider chains, Urdu policy, fallbacks, budget and error mapping through the envelope.
Refs: VOX-R2.5, R7.3, R7.6, R10.1, R10.2, R10.4, design 6 and 14."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import voice_helpers as h

from stitch_voice.core import audio
from stitch_voice.providers.azure import AzureTTS
from stitch_voice.providers.fake import FakeSTT, FakeTTS
from stitch_voice.service import URDU_NEEDS_AZURE

UR_TEXT = "دریائے سندھ میں پانی بڑھ رہا ہے۔"


def _wav_b64(seconds: float = 1.0, silent: bool = False) -> str:
    raw = audio.silence_wav(seconds) if silent else audio.tone_wav(seconds, 440.0)
    return base64.b64encode(raw).decode("ascii")


def test_english_uses_deepgram_live_then_cache() -> None:
    rec = h.Recorder([h.wav_response(0.8)])
    svc = h.service(tts=[h.deepgram_tts(rec)], stt=[])
    first = h.call(svc, "speak", {"text": "The river is rising.", "lang": "en"})
    second = h.call(svc, "speak", {"text": "The river is rising.", "lang": "en"})
    assert first.ok and first.data.provider == "deepgram" and first.data.synthesized == "live"
    assert first.data.voice == "aura-2-thalia-en" and first.provenance.mode == "live"
    assert first.provenance.model is not None
    assert any(s.id == "deepgram-api" for s in first.provenance.data_sources)
    assert second.ok and second.data.synthesized == "cache"
    assert second.data.audio_b64 == first.data.audio_b64
    assert len(rec.requests) == 1


def test_urdu_without_azure_or_prerendered_is_unavailable_with_warning() -> None:
    rec = h.Recorder([h.wav_response()])
    svc = h.service(tts=[h.deepgram_tts(rec)], stt=[])
    res = h.call(svc, "speak", {"text": UR_TEXT, "lang": "ur"})
    assert not res.ok and res.error is not None
    assert res.error.code == "UPSTREAM_UNAVAILABLE" and not res.error.retryable
    assert URDU_NEEDS_AZURE in res.warnings
    assert rec.requests == []  # Urdu never goes to the English voice


def test_urdu_with_english_voice_is_invalid_input() -> None:
    svc = h.service(tts=[h.deepgram_tts(h.Recorder([h.wav_response()]))], stt=[])
    res = h.call(svc, "speak", {"text": UR_TEXT, "lang": "ur", "voice": "aura-2-thalia-en"})
    assert not res.ok and res.error is not None and res.error.code == "INVALID_INPUT"


def test_urdu_served_from_prerendered(voice_env: Path) -> None:
    wav = h.add_prerendered(voice_env / "prerendered", UR_TEXT, "ur", "ur-PK-UzmaNeural", "azure")
    svc = h.service(tts=[h.deepgram_tts(h.Recorder([h.wav_response()]))], stt=[])
    res = h.call(svc, "speak", {"text": UR_TEXT, "lang": "ur"})
    assert res.ok and res.data.provider == "prerendered" and res.data.synthesized == "prerendered"
    assert base64.b64decode(res.data.audio_b64) == wav and res.data.lang == "ur"


def test_urdu_uses_azure_when_keyed() -> None:
    rec = h.Recorder([h.wav_response()])
    azure = AzureTTS(h.KEY, "eastus", client=h.client(rec), sleep=h.no_sleep)
    svc = h.service(tts=[h.deepgram_tts(h.Recorder([])), azure], stt=[])
    res = h.call(svc, "speak", {"text": UR_TEXT, "lang": "ur"})
    assert res.ok and res.data.provider == "azure" and res.data.voice == "ur-PK-UzmaNeural"
    assert len(rec.requests) == 1 and rec.requests[0].url.host.startswith("eastus.")


def test_english_falls_back_to_prerendered_when_deepgram_fails(voice_env: Path) -> None:
    text = "Stitch demo briefing."
    h.add_prerendered(voice_env / "prerendered", text, "en", "aura-2-thalia-en", "deepgram")
    svc = h.service(tts=[h.deepgram_tts(h.Recorder([httpx.Response(503)]))], stt=[])
    res = h.call(svc, "speak", {"text": text, "lang": "en"})
    assert res.ok and res.data.provider == "prerendered"
    assert any(w.startswith("TTS_FALLBACK: deepgram") for w in res.warnings)


def test_english_failure_without_prerendered_is_retryable_upstream() -> None:
    svc = h.service(tts=[h.deepgram_tts(h.Recorder([httpx.Response(503)]))], stt=[])
    res = h.call(svc, "speak", {"text": "Nothing cached.", "lang": "en"})
    assert not res.ok and res.error is not None
    assert res.error.code == "UPSTREAM_UNAVAILABLE" and res.error.retryable
    assert h.KEY not in res.error.message


def test_budget_cap_makes_no_http_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STITCH_TTS_MONTHLY_CHAR_CAP", "5")
    rec = h.Recorder([h.wav_response()])
    svc = h.service(tts=[h.deepgram_tts(rec)], stt=[])
    res = h.call(svc, "speak", {"text": "A sentence longer than five characters.", "lang": "en"})
    assert not res.ok and res.error is not None and res.error.code == "UPSTREAM_UNAVAILABLE"
    assert rec.requests == []


def test_long_text_is_chunked_and_joined() -> None:
    rec = h.Recorder([h.wav_response(0.5)])
    svc = h.service(tts=[h.deepgram_tts(rec)], stt=[])
    text = " ".join(f"Sentence number {i} about the river level at Kotri." for i in range(60))
    res = h.call(svc, "speak", {"text": text, "lang": "en"})
    assert res.ok and len(rec.requests) >= 2
    assert all(len(r.content) < 2000 for r in rec.requests)
    n = len(rec.requests)
    assert abs(res.data.duration_s - (0.5 * n + 0.4 * (n - 1))) < 0.05


def test_mp3_request_returns_wav_with_warning() -> None:
    svc = h.service(tts=[FakeTTS()], stt=[])
    res = h.call(svc, "speak", {"text": "Hello.", "lang": "en", "format": "mp3"})
    assert res.ok and res.data.format == "wav"
    assert any(w.startswith("FORMAT_WAV_ONLY") for w in res.warnings)


def test_unspeakable_text_is_invalid_input() -> None:
    res = h.call(h.service(tts=[FakeTTS()], stt=[]), "speak", {"text": "[1] ***", "lang": "en"})
    assert not res.ok and res.error is not None and res.error.code == "INVALID_INPUT"


def test_prerendered_only_mode_unknown_text_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STITCH_TTS_PROVIDER", "prerendered")
    svc = h.service(stt=[])
    res = h.call(svc, "speak", {"text": "Not in the index.", "lang": "en"})
    assert not res.ok and res.error is not None and res.error.code == "NOT_FOUND"


def test_transcribe_deepgram_failure_falls_back_with_warning() -> None:
    dg = h.deepgram_stt(h.Recorder([httpx.Response(500)]))
    svc = h.service(tts=[], stt=[dg, FakeSTT()])
    res = h.call(svc, "transcribe", {"audio_b64": _wav_b64(), "format": "wav", "lang_hint": "en"})
    assert res.ok and res.data.text == FakeSTT.TEXT["en"]
    assert any(w.startswith("STT_FALLBACK: deepgram") for w in res.warnings)


def test_transcribe_deepgram_success_states_live_mode() -> None:
    body = h.listen_body("پانی بڑھ رہا ہے", None)
    dg = h.deepgram_stt(h.Recorder([httpx.Response(200, json=body)]))
    svc = h.service(tts=[], stt=[dg])
    res = h.call(
        svc, "transcribe", {"audio_b64": _wav_b64(2.0), "format": "wav", "lang_hint": "ur"}
    )
    assert res.ok and res.data.lang == "ur" and res.data.text == "پانی بڑھ رہا ہے"
    assert res.provenance.mode == "live" and res.provenance.model is not None


def test_transcribe_silence_is_no_speech_without_calling_the_engine() -> None:
    rec = h.Recorder([httpx.Response(200, json=h.listen_body("hallucination"))])
    svc = h.service(tts=[], stt=[h.deepgram_stt(rec)])
    res = h.call(svc, "transcribe", {"audio_b64": _wav_b64(silent=True), "format": "wav"})
    assert res.ok and res.data.text == "" and "NO_SPEECH" in res.warnings
    assert rec.requests == []


def test_transcribe_wrong_magic_bytes_is_invalid_input() -> None:
    svc = h.service(tts=[], stt=[FakeSTT()])
    res = h.call(svc, "transcribe", {"audio_b64": _wav_b64(), "format": "ogg"})
    assert not res.ok and res.error is not None and res.error.code == "INVALID_INPUT"


def test_no_stt_engine_is_upstream_unavailable() -> None:
    res = h.call(
        h.service(tts=[], stt=[]), "transcribe", {"audio_b64": _wav_b64(), "format": "wav"}
    )
    assert not res.ok and res.error is not None and res.error.code == "UPSTREAM_UNAVAILABLE"


def test_meta_reports_urdu_route() -> None:
    meta = h.service(tts=[h.deepgram_tts(h.Recorder([]))], stt=[FakeSTT()]).meta()
    assert meta["urdu_tts"] == "prerendered" and meta["hosted"] is True
    assert meta["tts_chain"] == ["deepgram", "prerendered"]
