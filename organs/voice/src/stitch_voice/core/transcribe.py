"""Core logic of voice.transcribe. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.voice import TranscribeIn, TranscribeOut
from stitch_common.tooling import Outcome


def run(
    params: TranscribeIn,
) -> TranscribeOut | Outcome[TranscribeOut]:
    """Implement transcribe.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("voice.transcribe")
