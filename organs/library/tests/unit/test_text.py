"""Normalization, language detection, sentences, chunks, tokenizer (design 4.2 to 4.4, 6.2)."""

from __future__ import annotations

import itertools
import math

import pytest

from stitch_library.core.bm25 import BM25Index
from stitch_library.core.chunk import CHUNKER_VERSION, MAX_CHARS, chunk_id, chunk_page
from stitch_library.core.lang import detect_lang, detect_query_lang
from stitch_library.core.normalize import normalize_text, search_text
from stitch_library.core.sentences import split_sentences
from stitch_library.core.tokenize import concept_tokens, light_stem, tokenize


def sents(text: str) -> list[str]:
    return [text[s:e] for s, e in split_sentences(text)]


def test_normalize_folds_and_whitespace() -> None:
    raw = "\u200fيک\u0640 كتاب ه\r\nline  two\n\npara\tthree wa-\nter Co-\nOp"
    out = normalize_text(raw)
    assert "\u200f" not in out and "\u0640" not in out
    assert "یک" in out and "کتاب" in out and "ہ" in out
    assert "line two" in out and "\n\npara three water Co- Op" in out


def test_normalize_keeps_digits_and_zwnj() -> None:
    assert normalize_text("۱۲ litres") == "۱۲ litres"
    assert "\u200c" in normalize_text("می\u200cشود")


def test_presentation_forms_fold() -> None:
    assert normalize_text("\ufefb") == "لا"


def test_search_text() -> None:
    s = search_text("مَیں ۱۲ Litres\u200cX ﬁle")
    assert s == "میں 12 litresx file"


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Store water for several days.", "en"),
        ("پانی کو ابالیں اور محفوظ رکھیں۔", "ur"),
        ("الماء ضروري للحياة والصحة", "other"),  # Arabic, no Urdu markers
        ("پانی water پانی میں ہے", "ur"),
        ("1234 !!!", "other"),
    ],
)
def test_detect_lang(text: str, lang: str) -> None:
    assert detect_lang(text) == lang


def test_query_lang_short_urdu() -> None:
    assert detect_query_lang("پانی کتنا؟") == "ur"
    assert detect_query_lang("how much water") == "en"


def test_sentence_cases_from_docstring() -> None:
    assert sents("Store 1.5 litres. Boil it.") == ["Store 1.5 litres.", "Boil it."]
    assert sents("See No. 5 for details.") == ["See No. 5 for details."]
    assert sents("پانی ابالیں۔ کیا یہ محفوظ ہے؟ ہاں") == ["پانی ابالیں۔", "کیا یہ محفوظ ہے؟", "ہاں"]
    assert sents("Kit: • Water • Food") == ["Kit:", "• Water", "• Food"]
    assert sents("Use e.g. bleach. J. Smith said so.") == ["Use e.g. bleach.", "J. Smith said so."]
    assert sents("Line one\n\nLine two") == ["Line one", "Line two"]


def test_long_sentence_is_cut_at_400() -> None:
    text = ("word " * 120).strip() + "."
    spans = split_sentences(text)
    assert all(e - s <= 400 for s, e in spans) and len(spans) >= 2


def test_chunks_cover_and_respect_limits() -> None:
    text = " ".join(f"Sentence number {i} is about water storage." for i in range(60))
    chunks = chunk_page(text)
    assert all(c.end - c.start <= MAX_CHARS for c in chunks)
    assert chunks[0].start == 0 and chunks[-1].end == len(text)
    assert all(a.end <= b.start for a, b in itertools.pairwise(chunks))


def test_chunk_id_is_stable() -> None:
    a = chunk_id("abc", 1, 0, 10)
    assert a == chunk_id("abc", 1, 0, 10) and a.startswith("c_") and len(a) == 22
    assert a != chunk_id("abc", 2, 0, 10)
    assert CHUNKER_VERSION == "1"


def test_tokenize_routes_and_stems() -> None:
    assert tokenize("store the gallons of water", "en") == ["store", "gallon", "water"]
    assert tokenize("store the gallons", "en", stem=False) == ["store", "gallons"]
    assert tokenize(search_text("پانی کے لیے"), "ur") == ["پانی"]
    assert light_stem("supplies") == "supply" and light_stem("glass") == "glass"


def test_concept_tokens_cross_language() -> None:
    assert "water" in concept_tokens(search_text("پانی"))
    assert "litre" in concept_tokens("liters")


def test_bm25_hand_computed() -> None:
    docs = [("a", ["water", "boil"]), ("b", ["water", "water", "food"]), ("c", ["shelter"])]
    idx = BM25Index(docs)
    n, avgdl, k1, b = 3, 6 / 3, 1.2, 0.75

    def idf(df: int) -> float:
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def term(tf: int, dl: int, df: int) -> float:
        return idf(df) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))

    s = idx.scores(["water", "boil"])
    assert s["a"] == pytest.approx(term(1, 2, 2) + term(1, 2, 1), abs=1e-9)
    assert s["b"] == pytest.approx(term(2, 3, 2), abs=1e-9)
    assert "c" not in s
    assert idx.score_one("b", ["water", "boil"]) == pytest.approx(s["b"], abs=1e-12)
    assert idx.top(["water"], 5) == sorted(idx.top(["water"], 5), key=lambda x: (-x[1], x[0]))


def test_bm25_urdu_fold_equivalence_and_fingerprint() -> None:
    folded = tokenize(search_text(normalize_text("كتاب")), "ur")
    plain = tokenize(search_text(normalize_text("کتاب")), "ur")
    assert folded == plain
    a = BM25Index([("x", ["a"]), ("y", ["b"])])
    b = BM25Index([("y", ["b"]), ("x", ["a"])])
    assert a.fingerprint == b.fingerprint
