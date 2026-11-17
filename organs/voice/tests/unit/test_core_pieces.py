"""Unit tests for split, audio, guards, budget and keys (voice tasks 2, 4, 6)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from stitch_voice.core import audio, budget, guards, keys, split


def test_sentences_split_on_english_and_urdu_marks() -> None:
    text = "Water is rising. Move now! Is the road open? پانی بڑھ رہا ہے۔ کیا سڑک کھلی ہے؟ End"
    parts = split.sentences(text)
    assert parts == [
        "Water is rising.",
        "Move now!",
        "Is the road open?",
        "پانی بڑھ رہا ہے۔",
        "کیا سڑک کھلی ہے؟",
        "End",
    ]
    assert " ".join(parts) == text


def test_abbreviations_are_protected() -> None:
    assert split.sentences("Call Dr. Khan now. Then go.") == ["Call Dr. Khan now.", "Then go."]


def test_chunks_respect_limit_and_keep_words() -> None:
    text = " ".join(f"Sentence number {i} is here." for i in range(60))
    out = split.chunks(text, limit=120)
    assert all(len(c) <= 120 for c in out)
    assert " ".join(out).split() == text.split()
    long_word = "x" * 300
    assert all(len(c) <= 100 for c in split.chunks(long_word, limit=100))


def test_join_wav_duration_is_sum_plus_pauses() -> None:
    a = audio.tone_wav(0.5, 440)
    b = audio.tone_wav(0.25, 660)
    joined = audio.join_wav([a, b, a], pause_s=0.4)
    assert audio.wav_info(joined).duration_s == pytest.approx(0.5 + 0.25 + 0.5 + 0.8, abs=1e-3)


def test_join_wav_rejects_mismatched_parameters() -> None:
    with pytest.raises(audio.AudioError):
        audio.join_wav([audio.silence_wav(0.1, 16000), audio.silence_wav(0.1, 24000)])


def test_sniff_and_levels() -> None:
    wav = audio.silence_wav(0.2)
    audio.sniff(wav, "wav")
    with pytest.raises(audio.AudioError):
        audio.sniff(wav, "ogg")
    with pytest.raises(audio.AudioError):
        audio.sniff(b"RIFF", "wav")
    audio.sniff(b"OggS\x00", "ogg")
    audio.sniff(b"\x1a\x45\xdf\xa3", "webm")
    audio.sniff(b"ID3\x04", "mp3")
    info, pcm = audio.wav_frames(wav)
    assert audio.rms_dbfs(audio.pcm16_mono_samples(info, pcm)) == -math.inf
    info, pcm = audio.wav_frames(audio.tone_wav(0.2, 440, amp=0.3))
    assert audio.rms_dbfs(audio.pcm16_mono_samples(info, pcm)) == pytest.approx(-13.5, abs=0.3)


def test_guards() -> None:
    assert guards.is_silent(-60) and not guards.is_silent(-20)
    text, trimmed = guards.trim_repetition("go to the camp " * 8)
    assert trimmed and text == "go to the camp"
    assert guards.trim_repetition("a b c d") == ("a b c d", False)
    assert guards.is_filler("Thanks for watching!", 1.0)
    assert not guards.is_filler("Thanks for watching!", 3.0)
    assert not guards.is_filler("شکریہ", 0.5)
    lang, conf, unsupported = guards.select_language({"hi": 0.6, "en": 0.2})
    assert (lang, unsupported) == ("ur", None) and conf == pytest.approx(0.75)
    assert guards.select_language({"en": 0.9, "ur": 0.1})[0] == "en"
    assert guards.select_language({"fr": 0.9, "en": 0.05})[2] == "fr"
    assert guards.select_language({}) == ("en", 0.0, None)


def test_budget_decisions() -> None:
    assert budget.month_key(datetime(2026, 11, 30, 23, 59, tzinfo=UTC)) == "2026-11"
    assert budget.decide(0, 100, 1000) == budget.Decision(True, 100, False)
    assert budget.decide(700, 100, 1000).warn
    assert not budget.decide(950, 100, 1000).allowed
    assert not budget.decide(0, 1, 0).allowed


def test_cache_key_depends_on_every_field() -> None:
    base = keys.cache_key("hi", "en", "v", "fake")
    assert base == keys.cache_key("hi", "en", "v", "fake")
    assert (
        len(
            {
                base,
                keys.cache_key("hi!", "en", "v", "fake"),
                keys.cache_key("hi", "ur", "v", "fake"),
                keys.cache_key("hi", "en", "w", "fake"),
                keys.cache_key("hi", "en", "v", "deepgram"),
            }
        )
        == 5
    )
