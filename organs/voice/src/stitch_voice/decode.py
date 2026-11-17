"""Input audio checks before any recognizer runs (design 2.3; VOX-R1.2, VOX-P4).

All work is in memory. WAV is parsed with the stdlib; webm, ogg and mp3 go through PyAV, which
decodes until 60 s of audio have been produced and then stops, so a small file that claims or
expands to hours is rejected cheaply.
"""

from __future__ import annotations

import io
import math
import threading
from dataclasses import dataclass

from stitch_voice.core import audio
from stitch_voice.core.audio import AudioError, Container

DECODE_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class CheckedAudio:
    duration_s: float
    level_dbfs: float | None  # None when the level was not measured


def _wav(raw: bytes, max_s: float) -> CheckedAudio:
    info, pcm = audio.wav_frames(raw)
    if info.duration_s > max_s:
        raise AudioError(f"audio longer than {max_s:.0f} s")
    if info.frames == 0:
        return CheckedAudio(0.0, -math.inf)
    level: float | None = None
    if info.sample_width == 2:
        level = audio.rms_dbfs(audio.pcm16_mono_samples(info, pcm))
    return CheckedAudio(info.duration_s, level)


def _av(raw: bytes, max_s: float) -> CheckedAudio:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - av ships with faster-whisper
        raise AudioError("compressed audio is not supported in this build") from exc
    seconds = 0.0
    sum_sq = 0.0
    count = 0
    try:
        with av.open(io.BytesIO(raw), mode="r") as container:
            if not container.streams.audio:
                raise AudioError("no audio stream")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    arr = out.to_ndarray().reshape(-1)
                    seconds += arr.shape[0] / 16000.0
                    sum_sq += float((arr.astype("float64") ** 2).sum())
                    count += int(arr.shape[0])
                if seconds > max_s:
                    raise AudioError(f"audio longer than {max_s:.0f} s")
    except AudioError:
        raise
    except Exception as exc:  # any decoder failure is invalid input, never a crash
        raise AudioError("could not decode audio") from exc
    if count == 0:
        return CheckedAudio(0.0, -math.inf)
    rms = math.sqrt(sum_sq / count)
    return CheckedAudio(seconds, 20 * math.log10(rms / 32768.0) if rms > 0 else -math.inf)


def check_audio(raw: bytes, fmt: Container, max_s: float = audio.MAX_SECONDS) -> CheckedAudio:
    """Validate magic bytes and duration; measure the level. Raises ``AudioError``."""
    audio.sniff(raw, fmt)
    if fmt == "wav":
        return _wav(raw, max_s)
    result: list[CheckedAudio] = []
    error: list[BaseException] = []

    def work() -> None:
        try:
            result.append(_av(raw, max_s))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(DECODE_TIMEOUT_S)
    if thread.is_alive():
        raise AudioError("audio decoding timed out")
    if error:
        exc = error[0]
        raise exc if isinstance(exc, AudioError) else AudioError("could not decode audio")
    return result[0]
