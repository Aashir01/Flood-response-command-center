"""Citation objects, the verbatim check and quote truncation (design 7.3 step 2). Pure.

A quote is always ``page.text[start:end]`` of the stored page. Quotes over 400 characters are cut
at the last whitespace at or before 400 characters (or hard at 400) and the span is shortened to
match, so ``quote == page_text[span[0]:span[1]]`` always holds (LIB-P2).
"""

from __future__ import annotations

from stitch_common.types import Citation, Lang
from stitch_library.core.lang import detect_lang
from stitch_library.store.base import DocRow, PageRow

MAX_QUOTE = 400


def truncate_span(text: str, start: int, end: int, limit: int = MAX_QUOTE) -> tuple[int, int]:
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    if end - start > limit:
        window = text[start : start + limit + 1]
        cut = max(window.rfind(" "), window.rfind("\n"))
        end = start + cut if 0 < cut <= limit else start + limit
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def quote_lang(quote: str, fallback: str) -> Lang:
    lang = detect_lang(quote)
    if lang in ("en", "ur"):
        return "ur" if lang == "ur" else "en"
    return "ur" if fallback == "ur" else "en"


def make_citation(doc: DocRow, page: PageRow, start: int, end: int) -> Citation:
    s, e = truncate_span(page.text, start, end)
    quote = page.text[s:e]
    return Citation(
        doc_id=doc.doc_id,
        title=doc.title,
        publisher=doc.publisher,
        page=page.page,
        span=(s, e),
        quote=quote,
        lang=quote_lang(quote, page.lang),
        url=doc.source_url or None,
    )


def is_verbatim(page: PageRow | None, citation: Citation) -> bool:
    if page is None or page.status != "ok":
        return False
    s, e = citation.span
    return (
        0 <= s <= e <= len(page.text)
        and bool(citation.quote)
        and page.text[s:e] == citation.quote
        and len(citation.quote) <= MAX_QUOTE
    )
