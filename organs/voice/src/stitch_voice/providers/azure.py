"""Azure Neural TTS over REST, used for Urdu (``ur-PK-UzmaNeural``; design 3.3 and 14).

SSML is built from a fixed template and all text is XML-escaped, so input cannot inject tags.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx

from stitch_voice.core import audio
from stitch_voice.providers.base import (
    ChunkAudio,
    Lang,
    NotConfigured,
    TTSName,
    UnsupportedLanguage,
    UpstreamFailed,
)
from stitch_voice.providers.http import post_with_retries

OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
XML_LANG = {"ur": "ur-PK", "en": "en-GB"}


def build_ssml(text: str, lang: Lang, voice: str) -> str:
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f"xml:lang={quoteattr(XML_LANG[lang])}>"
        f"<voice name={quoteattr(voice)}>{escape(text)}</voice></speak>"
    )


class AzureTTS:
    name: TTSName = "azure"
    hosted = True
    max_chunk_chars = 800

    def __init__(
        self,
        key: str,
        region: str,
        voice_ur: str = "ur-PK-UzmaNeural",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._key = key
        self._region = region
        self._voice_ur = voice_ur
        self._client = client or httpx.Client()
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"AzureTTS(region={self._region!r})"

    def supports(self, lang: Lang) -> bool:
        return lang == "ur"  # English goes to Deepgram (owner decision)

    def default_voice(self, lang: Lang) -> str:
        return self._voice_ur

    def available(self) -> bool:
        return bool(self._key and self._region)

    def synthesize(self, text: str, lang: Lang, voice: str) -> ChunkAudio:
        if not self.supports(lang):
            raise UnsupportedLanguage("Azure is configured for Urdu only")
        if not self.available():
            raise NotConfigured("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION are not set")
        kwargs: dict[str, Any] = {} if self._sleep is None else {"sleep": self._sleep}
        resp = post_with_retries(
            self._client,
            "Azure Speech",
            f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1",
            params={},
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                "User-Agent": "stitch-voice",
            },
            content=build_ssml(text, lang, voice).encode("utf-8"),
            **kwargs,
        )
        try:
            info = audio.wav_info(resp.content)
        except audio.AudioError as exc:
            raise UpstreamFailed("Azure returned audio that is not a WAV file") from exc
        return ChunkAudio(resp.content, info.sample_rate, info.duration_s)
