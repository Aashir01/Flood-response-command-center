"""BM25 tokenizer per language (design section 6.2). Pure.

Input is ``search_text`` (already folded, lowercased, ASCII digits). Tokens are Unicode word runs
with stopwords removed. Numbers are kept: quantities matter in relief guidance.

English uses an optional light stemmer (plural ``-s``/``-es`` stripping), on by default. The
Snowball stemmer named in the design was not added: the dev-set check in task 19 compares
plain tokens and this light stemmer (``docs/library-models.md``).

The Urdu stopword list is hand-assembled by the implementing agent from high-frequency Urdu
function words (postpositions, auxiliaries, pronouns, conjunctions); it is not taken from a
published list and needs a native-speaker review.
"""

from __future__ import annotations

import re

from stitch_library.core.glossary import GLOSSARY

_WORD = re.compile(r"\w+")

EN_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "may",
        "might",
        "must",
        "shall",
        "also",
    ]
)

UR_STOPWORDS = frozenset(
    [
        "کے",
        "کی",
        "کا",
        "کو",
        "میں",
        "سے",
        "پر",
        "نے",
        "ہے",
        "ہیں",
        "ہو",
        "ہوں",
        "ہوا",
        "ہوئی",
        "ہوئے",
        "تھا",
        "تھی",
        "تھے",
        "تھیں",
        "گا",
        "گی",
        "گے",
        "اور",
        "یا",
        "بھی",
        "تو",
        "ہی",
        "نہ",
        "نہیں",
        "جو",
        "جس",
        "جن",
        "جب",
        "تک",
        "کہ",
        "یہ",
        "وہ",
        "اس",
        "ان",
        "انہیں",
        "اسے",
        "ایک",
        "کر",
        "کرتا",
        "کرتی",
        "کرتے",
        "کریں",
        "کرنا",
        "کرنے",
        "کیا",
        "کیے",
        "گیا",
        "گئی",
        "گئے",
        "رہا",
        "رہی",
        "رہے",
        "ہونا",
        "ہونے",
        "والا",
        "والی",
        "والے",
        "لیے",
        "لئے",
        "ساتھ",
        "بعد",
        "پہلے",
        "اگر",
        "لیکن",
        "مگر",
        "چاہیے",
        "سکتا",
        "سکتی",
        "سکتے",
        "دیں",
        "دے",
        "دیا",
        "آپ",
        "ہم",
        "میں",
        "نے",
        "اپنے",
        "اپنی",
        "اپنا",
        "کسی",
        "کچھ",
        "سب",
        "ہر",
        "جا",
        "جاتا",
        "جاتی",
        "جاتے",
        "جائے",
        "جائیں",
    ]
)


ALL_STOPWORDS = EN_STOPWORDS | UR_STOPWORDS


def light_stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith(("ches", "shes", "sses", "xes")):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


def tokenize(stext: str, lang: str, *, stem: bool = True) -> list[str]:
    words = _WORD.findall(stext)
    if lang == "ur":
        return [w for w in words if w not in UR_STOPWORDS]
    out = [w for w in words if w not in ALL_STOPWORDS]
    return [light_stem(w) for w in out] if stem else out


def content_tokens(stext: str) -> set[str]:
    """Language-agnostic content tokens (both stopword lists removed, stemmed)."""
    return {light_stem(w) for w in _WORD.findall(stext) if w not in ALL_STOPWORDS}


def concept_tokens(stext: str) -> set[str]:
    """``content_tokens`` mapped through ``GLOSSARY`` (cross-language comparison)."""
    return {GLOSSARY.get(t, t) for t in content_tokens(stext)}
