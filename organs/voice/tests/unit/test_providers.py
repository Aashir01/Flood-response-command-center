"""Hosted providers against mocked HTTP (httpx ``MockTransport``; no network). Refs: VOX-R7.2,
R7.6, R10.1 to R10.4, design 14."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import httpx
import pytest
import voice_helpers as h

from stitch_voice.providers.azure import AzureTTS, build_ssml
from stitch_voice.providers.base import (
    CredentialsRejected,
    NotConfigured,
    RateLimited,
    UnsupportedLanguage,
    UpstreamFailed,
)
from stitch_voice.providers.deepgram import DeepgramSTT, DeepgramTTS, parse_listen


def test_deepgram_tts_request_shape() -> None:
    rec = h.Recorder([h.wav_response(0.5)])
    out = h.deepgram_tts(rec).synthesize("The river is rising.", "en", "aura-2-thalia-en")
    assert out.sample_rate == 24000 and abs(out.duration_s - 0.5) < 0.01
    req = rec.requests[0]
    assert req.url.path == "/v1/speak"
    params = dict(req.url.params)
    assert params["model"] == "aura-2-thalia-en" and params["mip_opt_out"] == "true"
    assert params["encoding"] == "linear16" and params["container"] == "wav"
    assert req.headers["authorization"] == f"Token {h.KEY}"
    assert json.loads(req.content) == {"text": "The river is rising."}


def test_deepgram_tts_has_no_urdu() -> None:
    rec = h.Recorder([h.wav_response()])
    tts = h.deepgram_tts(rec)
    assert not tts.supports("ur")
    with pytest.raises(UnsupportedLanguage):
        tts.synthesize("پانی", "ur", "aura-2-thalia-en")
    assert rec.requests == []


def test_deepgram_tts_non_wav_body_is_upstream_failure() -> None:
    with pytest.raises(UpstreamFailed):
        h.deepgram_tts(h.Recorder([httpx.Response(200, content=b"<html>")])).synthesize(
            "x", "en", "aura-2-thalia-en"
        )


def test_retry_after_429_then_success() -> None:
    rec = h.Recorder([httpx.Response(429, headers={"retry-after": "1"}), h.wav_response()])
    h.deepgram_tts(rec).synthesize("Hello.", "en", "aura-2-thalia-en")
    assert len(rec.requests) == 2


@pytest.mark.parametrize("status", [401, 403])
def test_credentials_rejected_is_not_retried(status: int) -> None:
    rec = h.Recorder([httpx.Response(status)])
    with pytest.raises(CredentialsRejected) as err:
        h.deepgram_tts(rec).synthesize("Hello.", "en", "aura-2-thalia-en")
    assert len(rec.requests) == 1 and not err.value.retryable
    assert h.KEY not in err.value.message


def test_503_exhaustion_and_timeout_are_retryable() -> None:
    rec = h.Recorder([httpx.Response(503)])
    with pytest.raises(UpstreamFailed) as err:
        h.deepgram_tts(rec).synthesize("Hello.", "en", "aura-2-thalia-en")
    assert len(rec.requests) == 3 and err.value.retryable
    rec = h.Recorder([httpx.ReadTimeout("slow")])
    with pytest.raises(UpstreamFailed):
        h.deepgram_tts(rec).synthesize("Hello.", "en", "aura-2-thalia-en")
    assert len(rec.requests) == 3


def test_429_exhaustion_is_rate_limited() -> None:
    with pytest.raises(RateLimited):
        h.deepgram_tts(h.Recorder([httpx.Response(429)])).synthesize(
            "Hello.", "en", "aura-2-thalia-en"
        )


def test_missing_key_makes_no_request() -> None:
    rec = h.Recorder([h.wav_response()])
    tts = DeepgramTTS("", client=h.client(rec))
    assert not tts.available()
    with pytest.raises(NotConfigured):
        tts.synthesize("Hello.", "en", "aura-2-thalia-en")
    assert rec.requests == []


def test_repr_never_shows_the_key() -> None:
    for obj in (
        DeepgramTTS(h.KEY),
        DeepgramSTT(h.KEY),
        AzureTTS(h.KEY, "eastus"),
    ):
        assert h.KEY not in repr(obj)


@pytest.mark.parametrize(("hint", "expected"), [("ur", "ur"), ("en", "en")])
def test_deepgram_stt_language_from_hint(hint: str, expected: str) -> None:
    rec = h.Recorder([httpx.Response(200, json=h.listen_body("water is rising"))])
    out = h.deepgram_stt(rec).transcribe(b"RIFF....WAVE", "wav", hint, 1.0)  # type: ignore[arg-type]
    params = dict(rec.requests[0].url.params)
    assert params["model"] == "nova-3" and params["language"] == expected
    assert params["mip_opt_out"] == "true" and "detect_language" not in params
    assert rec.requests[0].headers["content-type"] == "audio/wav"
    assert out.lang == expected and out.lang_confidence == 1.0
    assert out.text == "water is rising" and out.segments and out.speech_s


def test_deepgram_stt_auto_detects_and_maps_hindi_to_urdu() -> None:
    rec = h.Recorder([httpx.Response(200, json=h.listen_body("پانی بڑھ رہا ہے", "hi", 0.8))])
    out = h.deepgram_stt(rec).transcribe(b"OggS", "ogg", None, 2.0)
    params = dict(rec.requests[0].url.params)
    assert params["detect_language"] == "true" and "language" not in params
    assert rec.requests[0].headers["content-type"] == "audio/ogg"
    assert out.lang == "ur" and out.lang_confidence == pytest.approx(0.8)


def test_deepgram_stt_bad_body_is_upstream_failure() -> None:
    rec = h.Recorder([httpx.Response(200, json={"unexpected": True})])
    with pytest.raises(UpstreamFailed):
        h.deepgram_stt(rec).transcribe(b"x", "wav", "en", 1.0)


def test_parse_listen_empty_transcript() -> None:
    out = parse_listen(h.listen_body(""), "en")
    assert out.text == "" and out.speech_s == 0.0 and out.segments == []


def test_azure_request_shape_and_urdu_only() -> None:
    rec = h.Recorder([h.wav_response()])
    tts = AzureTTS(h.KEY, "eastus", client=h.client(rec), sleep=h.no_sleep)
    assert tts.supports("ur") and not tts.supports("en")
    tts.synthesize("پانی بڑھ رہا ہے۔", "ur", "ur-PK-UzmaNeural")
    req = rec.requests[0]
    assert req.url.host == "eastus.tts.speech.microsoft.com"
    assert req.headers["ocp-apim-subscription-key"] == h.KEY
    assert req.headers["x-microsoft-outputformat"] == "riff-24khz-16bit-mono-pcm"
    with pytest.raises(UnsupportedLanguage):
        tts.synthesize("Hello", "en", "ur-PK-UzmaNeural")


@pytest.mark.parametrize("text", ["<break/>", "a & b", '"><voice name="x">', "]]>", "پانی < 3"])
def test_ssml_cannot_be_injected(text: str) -> None:
    root = ET.fromstring(build_ssml(text, "ur", "ur-PK-UzmaNeural"))
    tags = {el.tag.split("}")[-1] for el in root.iter()}
    assert tags == {"speak", "voice"}
    voice = next(el for el in root.iter() if el.tag.endswith("voice"))
    assert voice.text == text
