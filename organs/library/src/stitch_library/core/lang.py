"""Script-based language detection for pages, chunks and queries (design section 4.3). Pure.

``ur`` when Arabic-script letters are at least half of the letters and the text passes the Urdu
marker test (Urdu-only letters or Urdu function words); ``en`` when Latin letters are at least
half; otherwise ``other``. Roman Urdu is detected as ``en`` (out of scope).
"""

from __future__ import annotations

import re
from typing import Literal

DetectedLang = Literal["en", "ur", "other"]

# Letters used by Urdu but not by Arabic (after the folds in normalize.py, ک and ہ also occur in
# folded Arabic text, so they are not used as markers).
URDU_ONLY_LETTERS = frozenset("ٹڈڑںےھ")
URDU_FUNCTION_WORDS = frozenset(["کے", "کی", "کا", "میں", "ہے", "اور", "سے", "کو", "پر", "نے"])
_WORD = re.compile(r"\w+")


def is_arabic_letter(ch: str) -> bool:
    o = ord(ch)
    return ch.isalpha() and (
        0x0600 <= o <= 0x06FF
        or 0x0750 <= o <= 0x077F
        or 0xFB50 <= o <= 0xFDFF
        or 0xFE70 <= o <= 0xFEFF
    )


def is_latin_letter(ch: str) -> bool:
    return ch.isalpha() and ord(ch) < 0x0250


def urdu_function_word_rate(text: str) -> float:
    words = _WORD.findall(text)
    if not words:
        return 0.0
    return sum(1 for w in words if w in URDU_FUNCTION_WORDS) / len(words)


def has_urdu_markers(text: str) -> bool:
    if any(c in URDU_ONLY_LETTERS for c in text):
        return True
    return any(w in URDU_FUNCTION_WORDS for w in _WORD.findall(text))


def detect_lang(text: str) -> DetectedLang:
    arabic = latin = letters = 0
    for ch in text:
        if not ch.isalpha():
            continue
        letters += 1
        if is_arabic_letter(ch):
            arabic += 1
        elif is_latin_letter(ch):
            latin += 1
    if letters == 0:
        return "other"
    if arabic * 2 >= letters:
        return "ur" if has_urdu_markers(text) else "other"
    if latin * 2 >= letters:
        return "en"
    return "other"


def detect_query_lang(text: str) -> Literal["en", "ur"]:
    """Queries are routed to ``en`` or ``ur`` by script alone (short Urdu queries often have no
    marker letter); a query that is mostly Arabic-script is ``ur``, anything else ``en``."""
    arabic = sum(1 for c in text if is_arabic_letter(c))
    letters = sum(1 for c in text if c.isalpha())
    return "ur" if letters and arabic * 2 >= letters else "en"
