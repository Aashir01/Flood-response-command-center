"""Span-preserving sentence splitter for English and Urdu (design section 4.4). Pure.

Returns ``(start, end)`` code-point offsets into the text it was given. Spans are ordered, do not
overlap, start and end on non-whitespace, and together cover every non-whitespace character
(LIB-P13). Rules:

* Newlines (paragraph breaks) always end a sentence.
* Always split after ``۔`` and ``؟`` (and closing quotes right after them).
* Split after ``.``, ``!`` or ``?`` only when whitespace follows and the next character is an
  uppercase letter, digit, bullet, quote or Arabic-script letter. A ``.`` does not split after a
  digit run (``costs 5. Then``), a single capital letter (``J. Smith``) or a known abbreviation
  (``No.``, ``e.g.``, ``i.e.``, ``Fig.``, ``approx.``, ``etc.``). ``1.5 litres`` never splits
  because no whitespace follows the point.
* A bullet character after whitespace starts a new sentence (list items are sentences).
* A sentence longer than 400 characters is cut at the last ``;``, ``،`` or ``,`` (else the last
  space) at or before 400 characters.

Examples (each line is one sentence):
    "Store 1.5 litres. Boil it."        -> "Store 1.5 litres." | "Boil it."
    "See No. 5 for details."             -> one sentence
    "پانی ابالیں۔ کیا یہ محفوظ ہے؟ ہاں"   -> "پانی ابالیں۔" | "کیا یہ محفوظ ہے؟" | "ہاں"
    "Kit: • Water • Food"                -> "Kit:" | "• Water" | "• Food"
"""

from __future__ import annotations

import re

from stitch_library.core.lang import is_arabic_letter

MAX_SENTENCE = 400
URDU_TERMINALS = "۔؟"
LATIN_TERMINALS = ".!?"
BULLETS = "•◦▪‣●■□➢✓"
CLOSERS = "\"'”’)]»"
QUOTES = "\"'“‘«("
ABBREVIATIONS = frozenset(
    ["no", "e.g", "i.e", "fig", "approx", "etc", "dr", "mr", "mrs", "vs", "st"]
)
_LINE = re.compile(r"[^\n]+")


def _prev_token(text: str, i: int, lo: int) -> str:
    j = i
    while j > lo and not text[j - 1].isspace():
        j -= 1
    return text[j:i]


def _boundaries(text: str, lo: int, hi: int) -> list[int]:
    cuts: list[int] = []
    i = lo
    while i < hi:
        ch = text[i]
        if ch in BULLETS and i > lo and text[i - 1].isspace():
            cuts.append(i)
        elif ch in URDU_TERMINALS:
            j = i + 1
            while j < hi and text[j] in CLOSERS:
                j += 1
            cuts.append(j)
            i = j
            continue
        elif ch in LATIN_TERMINALS:
            j = i + 1
            while j < hi and text[j] in CLOSERS:
                j += 1
            k = j
            while k < hi and text[k].isspace():
                k += 1
            if k > j and k < hi and _starts_sentence(text[k]) and _may_split(text, i, lo, ch):
                cuts.append(j)
                i = j
                continue
        i += 1
    return cuts


def _starts_sentence(c: str) -> bool:
    return c.isupper() or c.isdigit() or c in BULLETS or c in QUOTES or is_arabic_letter(c)


def _may_split(text: str, i: int, lo: int, ch: str) -> bool:
    if ch != ".":
        return True
    tok = _prev_token(text, i, lo)
    if not tok:
        return True
    if tok.isdigit():
        return False
    if len(tok) == 1 and tok.isupper():
        return False
    return tok.lower().rstrip(".") not in ABBREVIATIONS


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _limit(text: str, start: int, end: int, max_len: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    while end - start > max_len:
        window = text[start : start + max_len]
        idx = max(window.rfind(";"), window.rfind("،"), window.rfind(","))
        if idx > 0:
            cut = start + idx + 1
        else:
            sp = window.rfind(" ")
            cut = start + sp if sp > 0 else start + max_len
        piece = _trim(text, start, cut)
        if piece:
            out.append(piece)
        start = cut
        while start < end and text[start].isspace():
            start += 1
    piece = _trim(text, start, end)
    if piece:
        out.append(piece)
    return out


def split_sentences(text: str, max_len: int = MAX_SENTENCE) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in _LINE.finditer(text):
        lo, hi = m.start(), m.end()
        start = lo
        for cut in [*_boundaries(text, lo, hi), hi]:
            piece = _trim(text, start, cut)
            start = cut
            if piece:
                spans.extend(_limit(text, piece[0], piece[1], max_len))
    return spans
