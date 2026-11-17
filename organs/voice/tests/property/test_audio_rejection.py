"""VOX-P4: oversized or malformed audio is rejected with ``INVALID_INPUT``, never a crash.
Every case returns an envelope within the decode timeout."""

from __future__ import annotations

import base64
import time

import voice_helpers as h
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_common.organs.voice import MAX_AUDIO_BYTES
from stitch_voice.core import audio
from stitch_voice.decode import DECODE_TIMEOUT_S
from stitch_voice.providers.fake import FakeSTT

FORMATS = ["wav", "webm", "mp3", "ogg"]
MAGIC = {
    "wav": b"RIFF\x00\x00\x00\x00WAVE",
    "webm": b"\x1a\x45\xdf\xa3",
    "ogg": b"OggS",
    "mp3": b"ID3",
}


def _transcribe(args: dict[str, object]) -> tuple[object, float]:
    svc = h.service(tts=[], stt=[FakeSTT()])
    start = time.monotonic()
    res = h.call(svc, "transcribe", args)
    return res, time.monotonic() - start


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@settings(deadline=None)
@given(st.binary(max_size=4096), st.sampled_from(FORMATS), st.booleans())
def test_vox_p4_arbitrary_bytes_never_crash(raw: bytes, fmt: str, with_magic: bool) -> None:
    body = (MAGIC[fmt] + raw) if with_magic else raw
    res, elapsed = _transcribe({"audio_b64": _b64(body), "format": fmt})
    assert elapsed < DECODE_TIMEOUT_S + 2
    if not res.ok:  # type: ignore[attr-defined]
        assert res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]


@settings(deadline=None)
@given(st.integers(min_value=0, max_value=200), st.sampled_from(FORMATS))
def test_vox_p4_truncated_wav_is_rejected_or_handled(cut: int, fmt: str) -> None:
    raw = audio.tone_wav(0.5, 440.0)[:cut]
    res, _ = _transcribe({"audio_b64": _b64(raw), "format": fmt})
    if not res.ok:  # type: ignore[attr-defined]
        assert res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]
    else:
        assert "NO_SPEECH" in res.warnings  # type: ignore[attr-defined]


@settings(deadline=None)
@given(st.text(min_size=1, max_size=40).filter(lambda s: any(c not in "A-Za-z0-9+/=" for c in s)))
def test_vox_p4_bad_base64_is_invalid_input(junk: str) -> None:
    res, _ = _transcribe({"audio_b64": "!" + junk, "format": "wav"})
    assert not res.ok and res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]


def test_vox_p4_declared_format_mismatch_is_invalid_input() -> None:
    wav = _b64(audio.tone_wav(0.5, 440.0))
    for fmt in ("webm", "mp3", "ogg"):
        res, _ = _transcribe({"audio_b64": wav, "format": fmt})
        assert not res.ok and res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]


def test_vox_p4_longer_than_60_s_is_invalid_input() -> None:
    raw = audio.silence_wav(61.0, sample_rate=8000)
    res, _ = _transcribe({"audio_b64": _b64(raw), "format": "wav"})
    assert not res.ok and res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]


def test_vox_p4_size_boundary() -> None:
    over = _b64(b"RIFF" + b"\x00" * (MAX_AUDIO_BYTES - 3))
    res, _ = _transcribe({"audio_b64": over, "format": "wav"})
    assert not res.ok and res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]
    at_limit = _b64(b"RIFF" + b"\x00" * (MAX_AUDIO_BYTES - 4))
    res, _ = _transcribe({"audio_b64": at_limit, "format": "wav"})
    assert not res.ok and res.error.code == "INVALID_INPUT"  # type: ignore[attr-defined]
    assert "10 MB" not in res.error.message  # type: ignore[attr-defined]  # rejected as not-WAV
