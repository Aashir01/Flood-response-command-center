"""VOX-P2: text normalization is idempotent."""

from __future__ import annotations

import re

from hypothesis import given
from voice_strategies import langs, mixed_text

from stitch_voice.core.normalize import normalize


@given(mixed_text, langs)
def test_vox_p2_normalize_is_idempotent(text: str, lang: str) -> None:
    once = normalize(text, lang)
    assert normalize(once, lang) == once


@given(mixed_text)
def test_vox_p2_urdu_output_has_no_latin_or_ascii_digits(text: str) -> None:
    assert not re.search(r"[A-Za-z0-9]", normalize(text, "ur"))
