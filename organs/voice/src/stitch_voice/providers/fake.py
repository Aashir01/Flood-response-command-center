"""Deterministic offline providers for tests and CI (design 3.3 ``fake``)."""

from __future__ import annotations

import hashlib

from stitch_voice.core import audio
from stitch_voice.providers.base import ChunkAudio, Lang, Segment, STTName, Transcript, TTSName

SECONDS_PER_CHAR = 0.06
SAMPLE_RATE = 16000


class FakeTTS:
    """A sine tone whose pitch comes from a hash of the text; duration 0.06 s per character."""

    name: TTSName = "fake"
    hosted = False
    max_chunk_chars = 800

    def supports(self, lang: Lang) -> bool:
        return lang in ("en", "ur")

    def default_voice(self, lang: Lang) -> str:
        return f"fake-{lang}"

    def available(self) -> bool:
        return True

    def synthesize(self, text: str, lang: Lang, voice: str) -> ChunkAudio:
        digest = hashlib.sha256(f"{lang}|{voice}|{text}".encode()).digest()
        freq = 200.0 + digest[0] * 2.0
        seconds = SECONDS_PER_CHAR * max(1, len(text))
        wav = audio.tone_wav(seconds, freq, SAMPLE_RATE)
        return ChunkAudio(wav, SAMPLE_RATE, audio.wav_info(wav).duration_s)


class FakeSTT:
    """Returns a fixed transcript for non-silent audio; the service applies the silence gate."""

    name: STTName = "fake"
    hosted = False
    TEXT = {"en": "the water is rising", "ur": "پانی بڑھ رہا ہے"}

    def available(self) -> bool:
        return True

    def transcribe(
        self, audio_bytes: bytes, fmt: str, lang_hint: Lang | None, duration_s: float
    ) -> Transcript:
        lang: Lang = lang_hint or "en"
        text = self.TEXT[lang]
        return Transcript(
            text=text,
            lang=lang,
            lang_confidence=1.0 if lang_hint else 0.9,
            segments=[Segment(0.0, duration_s, text)],
            speech_s=duration_s,
            model="fake",
        )
