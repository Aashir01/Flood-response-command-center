"""Hosted TTS chunks run in parallel but the joined audio keeps the text order."""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from stitch_voice.providers.base import ChunkAudio
from stitch_voice.service import HOSTED_PARALLEL_CHUNKS, _synthesize_all


class _SlowHosted:
    name = "deepgram"
    hosted = True
    max_chunk_chars = 400

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def synthesize(self, text: str, lang: Any, voice: str) -> ChunkAudio:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(random.uniform(0.01, 0.05))
        with self._lock:
            self.active -= 1
        return ChunkAudio(text.encode(), 24000, 0.1)


def test_parallel_chunks_keep_order_and_bound_concurrency() -> None:
    random.seed(0)
    provider = _SlowHosted()
    parts = [f"part {i}" for i in range(12)]
    out = _synthesize_all(provider, parts, "en", "aura-2-thalia-en")  # type: ignore[arg-type]
    assert out == [p.encode() for p in parts]
    assert 1 < provider.peak <= HOSTED_PARALLEL_CHUNKS
