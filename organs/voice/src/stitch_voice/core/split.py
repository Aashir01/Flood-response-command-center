"""Sentence splitter and chunker (VOX-R2.2, design 3.5). Runs after normalization."""

from __future__ import annotations

import re

_ABBREVIATIONS = ("Dr.", "St.", "No.", "Mr.", "Mrs.", "Ms.", "e.g.", "i.e.", "etc.")
_BOUNDARY_RE = re.compile(r"(?<=[.!?۔؟])\s+|\n+")


def sentences(text: str) -> list[str]:
    """Split at ``. ! ? ۔ ؟`` followed by space, and at newlines. Abbreviations are protected.
    ``"".join`` of the result with single spaces reproduces the text up to whitespace."""
    parts: list[str] = []
    buf = ""
    for piece in _BOUNDARY_RE.split(text):
        if not piece or not piece.strip():
            continue
        buf = f"{buf} {piece}" if buf else piece
        if not buf.endswith(_ABBREVIATIONS):
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _split_long(sentence: str, limit: int) -> list[str]:
    out: list[str] = []
    current = ""
    for word in re.split(r"(?<=[,،;])\s+|\s+", sentence):
        if not word:
            continue
        while len(word) > limit:
            if current:
                out.append(current)
                current = ""
            out.append(word[:limit])
            word = word[limit:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) > limit:
            out.append(current)
            current = word
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def chunks(text: str, limit: int = 800) -> list[str]:
    """Group sentences into chunks of at most ``limit`` characters, at sentence boundaries.
    A sentence longer than ``limit`` is split at commas and then at word boundaries."""
    out: list[str] = []
    current = ""
    for sentence in sentences(text):
        pieces = [sentence] if len(sentence) <= limit else _split_long(sentence, limit)
        for piece in pieces:
            candidate = f"{current} {piece}" if current else piece
            if len(candidate) > limit:
                out.append(current)
                current = piece
            else:
                current = candidate
    if current:
        out.append(current)
    return [c for c in out if c]
