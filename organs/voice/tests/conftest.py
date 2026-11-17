"""Voice test fixtures.

* ``tests/strategies.py`` is importable as ``voice_strategies`` (pytest runs with
  ``--import-mode=importlib``).
* Every test runs with a clean voice environment: ``STITCH_TTS_PROVIDER=fake``,
  ``STITCH_STT_PROVIDER=fake``, no keys, and a temporary cache directory, so no test reads the
  owner's ``.env`` values or writes into ``data/cache``.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_path = Path(__file__).parent / "strategies.py"
if "voice_strategies" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("voice_strategies", _path)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["voice_strategies"] = _module
    _spec.loader.exec_module(_module)

_VOICE_ENV = (
    "DEEPGRAM_API_KEY",
    "AZURE_SPEECH_KEY",
    "AZURE_SPEECH_REGION",
    "STITCH_DEEPGRAM_VOICE_EN",
    "STITCH_WHISPER_MODEL",
    "STITCH_WHISPER_MODEL_DIR",
    "STITCH_WHISPER_DOWNLOAD",
    "STITCH_TTS_MONTHLY_CHAR_CAP",
    "STITCH_STT_MONTHLY_SECONDS_CAP",
)


@pytest.fixture(autouse=True)
def voice_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    if request.node.get_closest_marker("live") is None:
        for name in _VOICE_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("STITCH_TTS_PROVIDER", "fake")
        monkeypatch.setenv("STITCH_STT_PROVIDER", "fake")
    cache = tmp_path / "voice-cache"
    monkeypatch.setenv("STITCH_VOICE_CACHE_DIR", str(cache))
    monkeypatch.setenv("STITCH_VOICE_PRERENDERED_DIR", str(cache / "prerendered"))
    yield cache
