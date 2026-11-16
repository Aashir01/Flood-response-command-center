"""Text normalization (design section 4.2). Pure.

Two strings exist per page and chunk:

* ``normalize_text`` gives the canonical ``text``: storage, quotes, spans and display. Digits are
  kept as in the source so quotes match it. Spans are code-point offsets into this string.
* ``search_text`` is derived from ``text`` for BM25 and the embedder. It is never used for
  offsets.

``normalize_text`` is idempotent (LIB-P9).
"""

from __future__ import annotations

import re
import unicodedata

BIDI_CONTROLS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
TATWEEL = "\u0640"
ZWNJ, ZWJ = "\u200c", "\u200d"

# Arabic letters folded to their Urdu forms. ھ (U+06BE) and آ are kept.
LETTER_FOLDS = {
    "\u064a": "\u06cc",  # ي -> ی
    "\u0649": "\u06cc",  # ى -> ی
    "\u0643": "\u06a9",  # ك -> ک
    "\u0647": "\u06c1",  # ه -> ہ
}
_FOLD_TABLE = str.maketrans(LETTER_FOLDS)
_REMOVE_TABLE = str.maketrans({c: None for c in BIDI_CONTROLS + TATWEEL + "\ufeff"})

# C0/C1 controls except newline; tab is turned into a space later.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-z])-\n(?!\n)(?=[a-z])")
_PARA_BREAK = re.compile(r"\n\s*\n")

_ARABIC_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")
_DIGITS = str.maketrans(
    {**{chr(0x0660 + i): str(i) for i in range(10)}, **{chr(0x06F0 + i): str(i) for i in range(10)}}
)


def _is_presentation_form(ch: str) -> bool:
    o = ord(ch)
    return 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF


def fold_presentation_forms(text: str) -> str:
    """NFKC applied only to Arabic presentation-form characters (shaped glyph codes)."""
    if not any(_is_presentation_form(c) for c in text):
        return text
    return "".join(
        unicodedata.normalize("NFKC", c) if _is_presentation_form(c) else c for c in text
    )


def _once(raw: str) -> str:
    s = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    s = s.translate(_REMOVE_TABLE)
    s = fold_presentation_forms(s)
    s = s.translate(_FOLD_TABLE)
    s = unicodedata.normalize("NFC", s)
    s = s.translate(_FOLD_TABLE)
    s = _CONTROL.sub("", s)
    lines = [_SPACES.sub(" ", line).strip() for line in s.split("\n")]
    s = "\n".join(lines)
    s = _HYPHEN_BREAK.sub("", s)
    paragraphs = []
    for para in _PARA_BREAK.split(s):
        flat = _SPACES.sub(" ", para.replace("\n", " ")).strip()
        if flat:
            paragraphs.append(flat)
    return "\n\n".join(paragraphs)


def normalize_text(raw: str) -> str:
    """Canonical page text (idempotent)."""
    s = _once(raw)
    for _ in range(3):
        t = _once(s)
        if t == s:
            return s
        s = t
    return s


def search_text(text: str) -> str:
    """Matching form: no diacritics or joiners, ASCII digits, NFKC, case-folded."""
    s = _ARABIC_DIACRITICS.sub("", text)
    s = s.replace(ZWNJ, "").replace(ZWJ, "")
    s = s.translate(_DIGITS)
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_FOLD_TABLE)
    return s.casefold()


def clean_query(raw: str) -> str:
    """Query text: normalized like page text, newlines flattened."""
    return normalize_text(raw).replace("\n\n", " ")
