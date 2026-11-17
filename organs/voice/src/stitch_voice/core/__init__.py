"""Pure core logic for voice-mcp: no network, no MCP imports, no global state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stitch_voice.core.speak import run as speak
from stitch_voice.core.transcribe import run as transcribe

CORES: dict[str, Callable[[Any], Any]] = {
    "transcribe": transcribe,
    "speak": speak,
}
