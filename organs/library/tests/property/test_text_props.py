"""Text properties (design 11): LIB-P9 (normalization), LIB-P13 (sentence spans) and the chunk
span rules of design 4.4 (``chunk == text[start:end]``, chunks never cross a page)."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from library_strategies import ingest, page_texts

from stitch_library.core.chunk import chunk_page
from stitch_library.core.normalize import normalize_text, search_text
from stitch_library.core.sentences import split_sentences

SLOW = settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
raw_texts = page_texts() | st.text(max_size=300)


@SLOW
@given(raw_texts)
def test_p9_normalization_is_idempotent(raw: str) -> None:
    once = normalize_text(raw)
    assert normalize_text(once) == once
    s = search_text(once)
    assert search_text(s) == s


@SLOW
@given(raw_texts)
def test_p9_sentence_quotes_stay_verbatim_after_normalization(raw: str) -> None:
    """A quote is a slice of the normalized page text; normalizing it again changes nothing,
    so a quote checked against stored text cannot drift."""
    text = normalize_text(raw)
    for start, end in split_sentences(text):
        quote = text[start:end]
        assert normalize_text(quote) == quote


@SLOW
@given(raw_texts)
def test_p13_sentence_spans_are_ordered_and_cover_the_text(raw: str) -> None:
    text = normalize_text(raw)
    spans = split_sentences(text)
    prev_end = 0
    covered = [False] * len(text)
    for start, end in spans:
        assert 0 <= prev_end <= start < end <= len(text)
        assert text[start:end] == text[start:end].strip()
        assert end - start <= 400
        for i in range(start, end):
            covered[i] = True
        prev_end = end
    missing = [text[i] for i in range(len(text)) if not covered[i] and not text[i].isspace()]
    assert missing == [], missing


@SLOW
@given(page_texts())
def test_chunks_are_slices_with_size_limits(raw: str) -> None:
    text = normalize_text(raw)
    spans = chunk_page(text)
    prev = 0
    for sp in spans:
        assert prev <= sp.start < sp.end <= len(text)
        assert len(text[sp.start : sp.end]) <= 900
        prev = sp.end


@SLOW
@given(st.lists(page_texts(min_words=5), min_size=1, max_size=4))
def test_chunks_never_cross_a_page(pages: list[str]) -> None:
    doc = ingest("doc-pages", pages)
    by_page = {p.page: p for p in doc.pages}
    for c in doc.chunks:
        page = by_page[c.page]
        assert page.status == "ok"
        assert page.text[c.start : c.end] == c.text
