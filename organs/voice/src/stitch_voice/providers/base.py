"""Provider interfaces and typed errors (design 3.2).

Providers return audio or transcripts; the ``speak``/``transcribe`` output schemas are built by
``stitch_voice.service`` only, so swapping providers cannot change them (VOX-P5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Lang = Literal["en", "ur"]
TTSName = Literal["deepgram", "azure", "prerendered", "fake"]
STTName = Literal["deepgram", "whisper", "fake"]


class ProviderError(Exception):
    """Base class. ``message`` is safe for clients: never contains keys or user text."""

    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotConfigured(ProviderError):
    """Missing key or disabled provider. Not retryable."""


class CredentialsRejected(ProviderError):
    """401/403 from the provider. Not retryable."""


class RateLimited(ProviderError):
    retryable = True


class UpstreamFailed(ProviderError):
    """5xx, timeout or a transport error after retries."""

    retryable = True


class BudgetExceeded(ProviderError):
    """The monthly cap would be exceeded; no request was sent."""


class NotFound(ProviderError):
    """``prerendered``: no audio for this text."""


class UnsupportedLanguage(ProviderError):
    """The provider has no voice for the language."""


@dataclass(frozen=True)
class ChunkAudio:
    wav: bytes
    sample_rate: int
    duration_s: float


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    text: str
    lang: Lang
    lang_confidence: float
    segments: list[Segment] = field(default_factory=list)
    speech_s: float | None = None  # detected speech duration, when the engine reports it
    model: str = ""


class TTSProvider(Protocol):
    name: TTSName
    hosted: bool

    def supports(self, lang: Lang) -> bool: ...

    def default_voice(self, lang: Lang) -> str: ...

    def available(self) -> bool:
        """Configured and keyed. No network call."""
        ...

    def synthesize(self, text: str, lang: Lang, voice: str) -> ChunkAudio:
        """Synthesize one normalized chunk (at most ``max_chunk_chars``) as PCM16 WAV."""
        ...

    @property
    def max_chunk_chars(self) -> int: ...


class STTProvider(Protocol):
    name: STTName
    hosted: bool

    def available(self) -> bool: ...

    def transcribe(
        self, audio: bytes, fmt: str, lang_hint: Lang | None, duration_s: float
    ) -> Transcript: ...
