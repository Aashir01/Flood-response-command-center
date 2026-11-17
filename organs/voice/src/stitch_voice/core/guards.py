"""Transcription guards (VOX-R1.4, design 2.4 and 2.5). Pure functions over recognizer output."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

SILENCE_DBFS = -50.0
MIN_SPEECH_S = 0.3
SHORT_CLIP_S = 1.5
FILLER_PHRASES = frozenset(
    {"thanks for watching", "thank you", "thank you for watching", "you", "bye", "subtitles by"}
)


def is_silent(level_dbfs: float) -> bool:
    return level_dbfs < SILENCE_DBFS


def trim_repetition(text: str, n: int = 3, max_repeats: int = 4) -> tuple[str, bool]:
    """If any word ``n``-gram occurs more than ``max_repeats`` times, cut the text at the start of
    its second occurrence. Returns ``(text, trimmed)``."""
    words = text.split()
    grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(grams)
    worst = next((g for g in grams if counts[g] > max_repeats), None)
    if worst is None:
        return text, False
    first = grams.index(worst)
    second = grams.index(worst, first + 1)
    return " ".join(words[:second]), True


def is_filler(text: str, speech_s: float) -> bool:
    """A known English filler phrase on a short clip is treated as no speech."""
    simple = re.sub(r"[^\w\s]", "", text.lower()).strip()
    simple = re.sub(r"\s+", " ", simple)
    if speech_s >= SHORT_CLIP_S:
        return False
    return simple in FILLER_PHRASES or any(
        simple.startswith(p) for p in FILLER_PHRASES if len(p) > 6
    )


def select_language(probs: Mapping[str, float]) -> tuple[str, float, str | None]:
    """Map language probabilities to ``(lang, confidence, unsupported_code)``.

    ``hi`` counts as ``ur`` (spoken Hindi and Urdu are near-identical; design 2.5). When the top
    language overall is not en, ur or hi and its probability exceeds 0.5, ``unsupported_code``
    names it. With no mass on en/ur/hi the result is ``("en", 0.0, ...)``.
    """
    clean = {k: max(0.0, float(v)) for k, v in probs.items() if v == v}
    top = max(clean, key=lambda k: clean[k], default=None)
    unsupported = None
    if top is not None and top not in ("en", "ur", "hi") and clean[top] > 0.5:
        unsupported = top
    en = clean.get("en", 0.0)
    ur = clean.get("ur", 0.0) + clean.get("hi", 0.0)
    total = en + ur
    if total <= 0:
        return "en", 0.0, unsupported
    if ur > en:
        return "ur", min(1.0, ur / total), unsupported
    return "en", min(1.0, en / total), unsupported
