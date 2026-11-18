"""Regression: a spoken briefing is one SSE event of several MB.

The MCP SDK caps one SSE event at 1 MiB by default, which made every full-briefing
``voice.speak`` call over HTTP fail with ``MCPError: Server-sent event exceeded the 1048576 byte
limit`` in production. The Brain's HTTP connector must raise that cap.
"""

from __future__ import annotations

from stitch_brain.api.voice import SPEAK_MAX_CHARS, SPEAK_SCRIPT_CHARS
from stitch_brain.runtime.mcp_client import MAX_SSE_EVENT_BYTES

# 24 kHz, 16-bit mono WAV is 48 kB per second of speech; English speech runs about 15
# characters per second; base64 adds a third.
_WAV_BYTES_PER_S = 48_000
_CHARS_PER_S = 15


# Speech normalization spells numbers out; on the demo briefing it grew the text by about 1.5x.
_NORMALIZE_GROWTH = 2.0


def test_sse_cap_holds_the_longest_spoken_briefing() -> None:
    # The briefing script is capped at SPEAK_SCRIPT_CHARS; free text (when enabled) at
    # SPEAK_MAX_CHARS. Both must fit after normalization.
    assert SPEAK_SCRIPT_CHARS <= SPEAK_MAX_CHARS
    worst = SPEAK_MAX_CHARS * _NORMALIZE_GROWTH / _CHARS_PER_S * _WAV_BYTES_PER_S * 4 / 3
    assert MAX_SSE_EVENT_BYTES > 1024 * 1024
    assert worst < MAX_SSE_EVENT_BYTES
