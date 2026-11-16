"""Page extraction and the unreadable-page rule (design section 4.1).

Extraction runs only at pack-build or fetch time, never at query time. PDFs are parsed in a child
process with a timeout because PDF parsers are an attack surface: ``pypdfium2`` first,
``pdfminer.six`` for pages PDFium leaves unreadable. Text-first sources (``format: text``) are
UTF-8 files whose pages are separated by form feeds.

``classify_page`` is deterministic:
1. normalize (presentation forms folded to base letters);
2. ``unreadable:empty`` if fewer than 20 letters remain;
3. ``unreadable:garbled`` if more than 2 % of characters are U+FFFD, private-use or controls;
4. Arabic-script pages: the Urdu function-word rate is computed on the text as extracted, with
   each word reversed, and with the whole string reversed; the best variant wins. Below 0.02 on a
   page of at least 100 tokens is ``unreadable:garbled``; a reversed winner is stored and the page
   is flagged ``reordered``;
5. ``unreadable:other_script`` for Arabic-script pages without Urdu markers, and for pages that
   are neither mostly Latin nor mostly Arabic-script;
6. otherwise ``ok``.
"""

from __future__ import annotations

import concurrent.futures as cf
import re
from dataclasses import dataclass
from pathlib import Path

from stitch_library.core.lang import (
    detect_lang,
    has_urdu_markers,
    is_arabic_letter,
    urdu_function_word_rate,
)
from stitch_library.core.normalize import normalize_text

MIN_LETTERS = 20
GARBLED_MAX = 0.02
URDU_RATE_MIN = 0.02
URDU_RATE_MIN_TOKENS = 100
EXTRACT_TIMEOUT_S = 120
_WORDS = re.compile(r"\S+")


@dataclass(frozen=True)
class PageClass:
    status: str  # "ok" | "unreadable"
    reason: str | None  # "empty" | "garbled" | "other_script" | None
    text: str
    lang: str  # "en" | "ur" | "other"
    reordered: bool = False


def _bad_char(c: str) -> bool:
    o = ord(c)
    return (
        c == "\ufffd" or 0xE000 <= o <= 0xF8FF or (o < 32 and c not in "\n\t") or 0x7F <= o <= 0x9F
    )


def classify_page(raw: str) -> PageClass:
    text = normalize_text(raw)
    letters = sum(1 for c in text if c.isalpha())
    if letters < MIN_LETTERS:
        return PageClass("unreadable", "empty", text, "other")
    bad = sum(1 for c in raw if _bad_char(c))
    if raw and bad / len(raw) > GARBLED_MAX:
        return PageClass("unreadable", "garbled", text, "other")
    arabic = sum(1 for c in text if is_arabic_letter(c))
    reordered = False
    if arabic * 2 >= letters:
        variants = [
            (text, False),
            (" ".join(w[::-1] for w in text.split(" ")), True),
            (text[::-1], True),
        ]
        rates = [urdu_function_word_rate(v) for v, _ in variants]
        best = max(range(3), key=lambda i: (rates[i], -i))
        tokens = len(_WORDS.findall(text))
        if rates[best] < URDU_RATE_MIN and tokens >= URDU_RATE_MIN_TOKENS:
            return PageClass("unreadable", "garbled", text, "other")
        if best != 0:
            text, reordered = normalize_text(variants[best][0]), True
        if not has_urdu_markers(text):
            return PageClass("unreadable", "other_script", text, "other")
        return PageClass("ok", None, text, "ur", reordered)
    lang = detect_lang(text)
    if lang == "other":
        return PageClass("unreadable", "other_script", text, "other")
    return PageClass("ok", None, text, lang, reordered)


PAGE_BREAK = re.compile(r"\f|^[ \t]*<<<page-break>>>[ \t]*$", re.MULTILINE)


def text_pages(data: bytes) -> list[str]:
    """Pages of a text-first source: UTF-8, pages separated by a form feed or by a line that is
    exactly ``<<<page-break>>>``."""
    return PAGE_BREAK.split(data.decode("utf-8"))


def _pdfium_pages(path: str) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        out: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            tp = page.get_textpage()
            out.append(str(tp.get_text_range()))
            tp.close()
            page.close()
        return out
    finally:
        pdf.close()


def _pdfminer_page(path: str, index: int) -> str:
    from pdfminer.high_level import extract_text

    return str(extract_text(path, page_numbers=[index]))


def _extract_worker(path: str) -> list[str]:
    pages = _pdfium_pages(path)
    for i, raw in enumerate(pages):
        if classify_page(raw).status != "ok":
            try:
                alt = _pdfminer_page(path, i)
            except Exception:
                continue
            if classify_page(alt).status == "ok":
                pages[i] = alt
    return pages


def pdf_pages(path: Path, timeout_s: float = EXTRACT_TIMEOUT_S, isolate: bool = True) -> list[str]:
    """Raw page texts of a PDF (child process with a timeout unless ``isolate=False``)."""
    if not isolate:
        return _extract_worker(str(path))
    with cf.ProcessPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_extract_worker, str(path))
        try:
            return fut.result(timeout=timeout_s)
        except cf.TimeoutError as exc:
            raise RuntimeError(
                f"PDF extraction timed out after {timeout_s} s: {path.name}"
            ) from exc
