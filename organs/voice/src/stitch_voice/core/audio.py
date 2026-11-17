"""Audio helpers. Pure: bytes in, bytes or numbers out. No files, no network.

* ``sniff``: magic bytes per declared container (design 2.3).
* ``wav_info`` / ``wav_pcm16_mono``: header parsing with the stdlib ``wave`` module.
* ``silence_wav`` / ``tone_wav``: generated PCM16 WAV.
* ``join_wav``: concatenation with silence between chunks (VOX-R2.2).
* ``rms_dbfs``: energy gate input (design 2.4).
"""

from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import dataclass
from typing import Literal

MAX_SECONDS = 60.0
Container = Literal["wav", "webm", "mp3", "ogg"]


class AudioError(ValueError):
    """Invalid or undecodable audio. Messages are safe to return to the client."""


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    sample_width: int
    frames: int

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


def sniff(raw: bytes, declared: Container) -> None:
    """Raise ``AudioError`` unless the magic bytes match ``declared``."""
    ok = False
    if declared == "wav":
        ok = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    elif declared == "webm":
        ok = raw[:4] == b"\x1a\x45\xdf\xa3"
    elif declared == "ogg":
        ok = raw[:4] == b"OggS"
    elif declared == "mp3":
        ok = raw[:3] == b"ID3" or (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0)
    if not ok:
        raise AudioError(f"audio does not look like {declared}")


def wav_info(raw: bytes) -> WavInfo:
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            info = WavInfo(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
    except (wave.Error, EOFError, struct.error, ValueError) as exc:
        raise AudioError("could not decode audio") from exc
    if info.sample_rate <= 0 or info.channels <= 0:
        raise AudioError("could not decode audio")
    return info


def wav_frames(raw: bytes) -> tuple[WavInfo, bytes]:
    """Header info and the raw PCM payload (``wave`` reports truncated payloads short)."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            info = WavInfo(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
            pcm = w.readframes(info.frames)
    except (wave.Error, EOFError, struct.error, ValueError) as exc:
        raise AudioError("could not decode audio") from exc
    frame_bytes = info.channels * info.sample_width
    if info.sample_rate <= 0 or frame_bytes <= 0:
        raise AudioError("could not decode audio")
    real_frames = len(pcm) // frame_bytes
    return WavInfo(info.sample_rate, info.channels, info.sample_width, real_frames), pcm


def pcm16_mono_samples(info: WavInfo, pcm: bytes) -> list[int]:
    """First channel of 16-bit PCM as ints; other widths raise ``AudioError``."""
    if info.sample_width != 2:
        raise AudioError("only 16-bit PCM WAV is analysed directly")
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return list(samples[:: info.channels])


def rms_dbfs(samples: list[int]) -> float:
    """RMS level in dBFS of 16-bit samples; ``-inf`` for empty or all-zero input."""
    if not samples:
        return -math.inf
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq <= 0:
        return -math.inf
    return 20.0 * math.log10(math.sqrt(mean_sq) / 32768.0)


def _write_wav(pcm: bytes, sample_rate: int, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def silence_wav(seconds: float, sample_rate: int = 16000) -> bytes:
    frames = max(0, round(seconds * sample_rate))
    return _write_wav(b"\x00\x00" * frames, sample_rate)


def tone_wav(seconds: float, freq_hz: float, sample_rate: int = 16000, amp: float = 0.3) -> bytes:
    """Deterministic sine tone, PCM16 mono."""
    frames = max(1, round(seconds * sample_rate))
    peak = int(amp * 32767)
    pcm = b"".join(
        struct.pack("<h", int(peak * math.sin(2.0 * math.pi * freq_hz * i / sample_rate)))
        for i in range(frames)
    )
    return _write_wav(pcm, sample_rate)


def join_wav(chunks: list[bytes], pause_s: float = 0.4) -> bytes:
    """Join WAV chunks with ``pause_s`` of silence between them.

    All chunks must share sample rate, width and channel count (``AudioError`` otherwise).
    The result duration is the sum of the chunk durations plus ``(n - 1) * pause``.
    """
    if not chunks:
        raise AudioError("nothing to join")
    parsed = [wav_frames(c) for c in chunks]
    first = parsed[0][0]
    for info, _ in parsed[1:]:
        if (info.sample_rate, info.sample_width, info.channels) != (
            first.sample_rate,
            first.sample_width,
            first.channels,
        ):
            raise AudioError("chunk audio parameters differ")
    gap_frames = round(pause_s * first.sample_rate)
    gap = b"\x00" * (gap_frames * first.sample_width * first.channels)
    pcm = gap.join(p for _, p in parsed)
    return _write_wav(pcm, first.sample_rate, first.channels, first.sample_width)
