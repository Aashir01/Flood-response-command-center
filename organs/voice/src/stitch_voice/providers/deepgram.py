"""Deepgram providers over REST (design 14): Aura-2 TTS (English only) and Nova-3 STT (en, ur).

Every request sets ``mip_opt_out=true`` (Deepgram Model Improvement Program opt-out; terms 3.3).
The key goes only into the ``Authorization: Token`` header.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from stitch_voice.core import audio
from stitch_voice.core.guards import select_language
from stitch_voice.providers.base import (
    ChunkAudio,
    Lang,
    NotConfigured,
    Segment,
    STTName,
    Transcript,
    TTSName,
    UnsupportedLanguage,
    UpstreamFailed,
)
from stitch_voice.providers.http import post_with_retries

TTS_SAMPLE_RATE = 24000
CONTENT_TYPES = {"wav": "audio/wav", "webm": "audio/webm", "ogg": "audio/ogg", "mp3": "audio/mpeg"}


class _Base:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepgram.com",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client()
        self._sleep = sleep

    def available(self) -> bool:
        return bool(self._key)

    def _headers(self, content_type: str) -> dict[str, str]:
        if not self._key:
            raise NotConfigured("DEEPGRAM_API_KEY is not set")
        return {"Authorization": f"Token {self._key}", "Content-Type": content_type}

    def _post(self, path: str, params: dict[str, str], body: bytes, ctype: str) -> httpx.Response:
        kwargs: dict[str, Any] = {} if self._sleep is None else {"sleep": self._sleep}
        return post_with_retries(
            self._client,
            "Deepgram",
            f"{self._base}{path}",
            params={**params, "mip_opt_out": "true"},
            headers=self._headers(ctype),
            content=body,
            **kwargs,
        )

    def __repr__(self) -> str:  # never show the key
        return f"{type(self).__name__}(base_url={self._base!r})"


class DeepgramTTS(_Base):
    name: TTSName = "deepgram"
    hosted = True
    # Aura-2 accepts up to 2000 characters per request; stay below it.
    max_chunk_chars = 1500

    def __init__(self, api_key: str, voice_en: str = "aura-2-thalia-en", **kw: Any) -> None:
        super().__init__(api_key, **kw)
        self._voice_en = voice_en

    def supports(self, lang: Lang) -> bool:
        return lang == "en"  # Aura-2 has no Urdu voice

    def default_voice(self, lang: Lang) -> str:
        return self._voice_en

    def synthesize(self, text: str, lang: Lang, voice: str) -> ChunkAudio:
        if not self.supports(lang):
            raise UnsupportedLanguage("Deepgram Aura-2 has no Urdu voice")
        resp = self._post(
            "/v1/speak",
            {
                "model": voice,
                "encoding": "linear16",
                "container": "wav",
                "sample_rate": str(TTS_SAMPLE_RATE),
            },
            json.dumps({"text": text}).encode("utf-8"),
            "application/json",
        )
        wav = resp.content
        try:
            info = audio.wav_info(wav)
        except audio.AudioError as exc:
            raise UpstreamFailed("Deepgram returned audio that is not a WAV file") from exc
        return ChunkAudio(wav, info.sample_rate, info.duration_s)


class DeepgramSTT(_Base):
    name: STTName = "deepgram"
    hosted = True
    model = "nova-3"

    def transcribe(
        self, audio_bytes: bytes, fmt: str, lang_hint: Lang | None, duration_s: float
    ) -> Transcript:
        params = {
            "model": self.model,
            "punctuate": "true",
            "smart_format": "false",
            "utterances": "true",
        }
        if lang_hint in ("en", "ur"):
            params["language"] = lang_hint
        else:
            params["detect_language"] = "true"
        resp = self._post("/v1/listen", params, audio_bytes, CONTENT_TYPES.get(fmt, "audio/wav"))
        try:
            return parse_listen(resp.json(), lang_hint)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise UpstreamFailed("Deepgram returned an unexpected response") from exc


def parse_listen(body: dict[str, Any], lang_hint: Lang | None) -> Transcript:
    """Map a ``/v1/listen`` response to a ``Transcript``."""
    channel = body["results"]["channels"][0]
    alt = channel["alternatives"][0]
    text = str(alt.get("transcript", "")).strip()
    if lang_hint in ("en", "ur"):
        lang: Lang = lang_hint
        confidence = 1.0
    else:
        detected = str(channel.get("detected_language", "en"))
        conf = float(channel.get("language_confidence", 0.0) or 0.0)
        lang_s, confidence, _ = select_language({detected: max(conf, 1e-6)})
        lang = "ur" if lang_s == "ur" else "en"
        confidence = conf if detected in ("en", "ur", "hi") else 0.0
    segments = [
        Segment(float(u["start"]), max(float(u["start"]), float(u["end"])), str(u["transcript"]))
        for u in body["results"].get("utterances") or []
    ]
    words = alt.get("words") or []
    speech_s = (float(words[-1]["end"]) - float(words[0]["start"])) if words else 0.0
    return Transcript(
        text=text,
        lang=lang,
        lang_confidence=min(1.0, max(0.0, confidence)),
        segments=segments,
        speech_s=speech_s,
        model="deepgram:nova-3",
    )
