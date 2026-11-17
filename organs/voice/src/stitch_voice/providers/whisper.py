"""Local faster-whisper STT (design 2). Lazy load, CPU int8, one call at a time.

The model is never downloaded at runtime unless ``STITCH_WHISPER_DOWNLOAD=1``: the image (or
``scripts/prerender_voice.py --fetch-whisper``) puts it in the Hugging Face cache beforehand, so the
demo makes no network call. User audio stays in memory (``BytesIO``), never on disk.
"""

from __future__ import annotations

import hashlib
import io
import threading
from pathlib import Path
from typing import Any

from stitch_voice.core.guards import select_language
from stitch_voice.providers.base import Lang, NotConfigured, Segment, STTName, Transcript

DECODE_OPTIONS: dict[str, Any] = {
    "beam_size": 5,
    "temperature": 0.0,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "log_prob_threshold": -1.0,
    "compression_ratio_threshold": 2.4,
    "vad_filter": True,
    "vad_parameters": {"min_silence_duration_ms": 500, "speech_pad_ms": 400},
}


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class WhisperSTT:
    name: STTName = "whisper"
    hosted = False

    def __init__(self, size: str = "base", model_dir: str = "", download: bool = False) -> None:
        self.size = size
        self._dir = model_dir or None
        self._download = download
        self._model: Any = None
        self._lock = threading.Lock()
        self._load_error: str | None = None
        self.model_sha256 = ""

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return self._load_error is None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
            from faster_whisper.utils import download_model
        except ImportError as exc:
            raise NotConfigured("faster-whisper is not installed") from exc
        try:
            path = download_model(
                self.size, local_files_only=not self._download, cache_dir=self._dir
            )
            self.model_sha256 = _sha256(Path(path) / "model.bin")
            self._model = WhisperModel(
                path,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                num_workers=1,
            )
        except Exception as exc:  # missing files, corrupt cache
            self._load_error = type(exc).__name__
            raise NotConfigured(
                f"Whisper model '{self.size}' is not available locally; fetch it at build time "
                "(STITCH_WHISPER_DOWNLOAD=1 once, or scripts/prerender_voice.py --fetch-whisper)"
            ) from exc
        return self._model

    def transcribe(
        self, audio_bytes: bytes, fmt: str, lang_hint: Lang | None, duration_s: float
    ) -> Transcript:
        with self._lock:
            model = self._load()
            language = lang_hint if lang_hint in ("en", "ur") else None
            seg_iter, info = model.transcribe(
                io.BytesIO(audio_bytes), language=language, **DECODE_OPTIONS
            )
            raw = [s for s in seg_iter if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        segments = [Segment(float(s.start), float(s.end), s.text.strip()) for s in raw]
        if language is not None:
            lang: Lang = language
            conf = 1.0
        else:
            probs = dict(getattr(info, "all_language_probs", None) or [])
            probs.setdefault(info.language, float(info.language_probability))
            picked, conf, _ = select_language(probs)
            lang = "ur" if picked == "ur" else "en"
        speech_s = sum(s.end - s.start for s in segments)
        return Transcript(
            text=" ".join(s.text for s in segments if s.text).strip(),
            lang=lang,
            lang_confidence=conf,
            segments=segments,
            speech_s=speech_s,
            model=f"faster-whisper:{self.size}",
        )
