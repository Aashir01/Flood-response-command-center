"""voice-mcp tool I/O (mcp-contracts.md section 7).

Ambiguities: "<= 10 MB" is read as 10,000,000 decoded bytes. The 60 s limit needs audio
decoding and is enforced by the organ, not here. ``audio_b64`` must be valid base64.
"""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from pydantic import Field, field_validator, model_validator

from stitch_common.base import Contract
from stitch_common.types import Lang, LangOrAuto, NonNeg, Unit

MAX_AUDIO_BYTES = 10_000_000
# base64 length for MAX_AUDIO_BYTES, used as a cheap pre-check before decoding.
_MAX_B64_CHARS = 4 * ((MAX_AUDIO_BYTES + 2) // 3)

Provider = Literal["azure", "google", "deepgram", "prerendered", "local-mms", "fake"]
Synthesized = Literal["live", "cache", "prerendered"]


def _check_b64(value: str) -> str:
    if len(value) > _MAX_B64_CHARS:
        raise ValueError("audio exceeds 10 MB")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("audio_b64 is not valid base64") from exc
    if len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("audio exceeds 10 MB")
    return value


class TranscribeIn(Contract):
    audio_b64: str
    format: Literal["wav", "webm", "mp3", "ogg"]
    lang_hint: LangOrAuto | None = None

    @field_validator("audio_b64")
    @classmethod
    def _b64(cls, value: str) -> str:
        return _check_b64(value)


class Segment(Contract):
    start: NonNeg
    end: NonNeg
    text: str

    @model_validator(mode="after")
    def _ordered(self) -> Segment:
        if self.end < self.start:
            raise ValueError("segment end must be >= start")
        return self


class TranscribeOut(Contract):
    text: str
    lang: Lang
    segments: list[Segment]
    lang_confidence: Unit


class SpeakIn(Contract):
    text: str = Field(min_length=1, max_length=4000)
    lang: Lang
    voice: str | None = None
    format: Literal["wav", "mp3"] | None = None


class SpeakOut(Contract):
    audio_b64: str
    format: Literal["wav", "mp3"]
    duration_s: NonNeg
    sample_rate: int = Field(gt=0)
    lang: Lang
    provider: Provider
    synthesized: Synthesized
    voice: str | None = None  # v0.4: resolved voice name
