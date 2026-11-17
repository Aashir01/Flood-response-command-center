"""VOX-P3: identical ``(text, lang, voice)`` returns byte-identical audio. A noisy provider that
returns different bytes on every call proves the second response comes from the cache."""

from __future__ import annotations

import dataclasses
import itertools
import tempfile
from pathlib import Path

import voice_helpers as h
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_voice.core import audio
from stitch_voice.providers.base import ChunkAudio, Lang, TTSName
from stitch_voice.service import VoiceService
from stitch_voice.settings import load_settings


class NoisyTTS:
    name: TTSName = "fake"
    hosted = False
    max_chunk_chars = 800

    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.calls = 0

    def supports(self, lang: Lang) -> bool:
        return True

    def default_voice(self, lang: Lang) -> str:
        return f"noisy-{lang}"

    def available(self) -> bool:
        return True

    def synthesize(self, text: str, lang: Lang, voice: str) -> ChunkAudio:
        self.calls += 1
        wav = audio.tone_wav(0.2, 200.0 + next(self._n), 16000)
        return ChunkAudio(wav, 16000, 0.2)


words = st.sampled_from(["river", "rising", "Sukkur", "evacuate", "water", "پانی", "سکھر"])


@settings(deadline=None)
@given(st.lists(words, min_size=1, max_size=8).map(" ".join), st.sampled_from(["en", "ur"]))
def test_vox_p3_cache_returns_identical_bytes(text: str, lang: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = dataclasses.replace(
            load_settings(), cache_dir=Path(tmp), prerendered_dir=Path(tmp) / "prerendered"
        )
        noisy = NoisyTTS()
        svc = VoiceService(settings, tts=[noisy], stt=[])
        first = h.call(svc, "speak", {"text": text, "lang": lang})
        second = h.call(svc, "speak", {"text": text, "lang": lang})
        other = h.call(svc, "speak", {"text": text + " again", "lang": lang})
    assert first.ok and second.ok and other.ok
    assert first.data.synthesized == "live" and second.data.synthesized == "cache"
    assert second.data.audio_b64 == first.data.audio_b64
    assert other.data.audio_b64 != first.data.audio_b64
    assert noisy.calls == 2
