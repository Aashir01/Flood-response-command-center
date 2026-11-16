"""Shared Hypothesis strategies and builders for library tests (design section 11).

Imported as ``library_strategies`` (see ``conftest.py``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from hypothesis import strategies as st

from stitch_library.ingest.manifest import ManifestEntry
from stitch_library.ingest.pipeline import IngestedDoc, ingest_pages
from stitch_library.ml.embedder import FakeEmbedder
from stitch_library.ml.reranker import FakeReranker, NullReranker, Reranker
from stitch_library.pack import embed_chunks
from stitch_library.store.memory import MemoryStore

EN_WORDS = [
    "water", "boil", "flood", "shelter", "food", "safe", "drink", "people", "family", "store",
    "bleach", "gallon", "litres", "minute", "evacuate", "children", "clean", "supply", "kit",
    "Store", "Boil", "Water", "No.", "e.g.", "approx.", "J.", "wa-\nter", "co-\nOperate",
]  # fmt: skip
UR_WORDS = [
    "پانی", "ابالیں", "سیلاب", "پناہ", "خوراک", "محفوظ", "کے", "کی", "میں", "ہے", "اور",
    "سے", "لوگ", "بچوں", "صاف", "يک", "كتاب", "ه", "ىہ", "مَیں", "می\u200cشود", "۱۲", "۳",
]  # fmt: skip
NUMBERS = ["1.5", "15", "3", "1/8", "5,000", "0.5", "۲۰"]
PUNCT = [".", "?", "!", "۔", "؟", ",", "،", ";", ":"]
SEPS = [" ", " ", " ", "\n", "\n\n", " • ", "\t", "  "]


@st.composite
def page_texts(draw: st.DrawFn, min_words: int = 0, max_words: int = 80) -> str:
    """English, Urdu and mixed text with sentence punctuation, numbers and Urdu edge cases."""
    flavour = draw(st.sampled_from(["en", "ur", "mixed"]))
    pool = EN_WORDS if flavour == "en" else UR_WORDS if flavour == "ur" else EN_WORDS + UR_WORDS
    n = draw(st.integers(min_words, max_words))
    parts: list[str] = []
    for _ in range(n):
        kind = draw(st.integers(0, 9))
        if kind < 6:
            parts.append(draw(st.sampled_from(pool)))
        elif kind < 7:
            parts.append(draw(st.sampled_from(NUMBERS)))
        else:
            parts.append(draw(st.sampled_from(PUNCT)))
        parts.append(draw(st.sampled_from(SEPS)))
    return "".join(parts)


def entry(doc_id: str, lang: str = "en", **kw: Any) -> ManifestEntry:
    base: dict[str, Any] = {
        "doc_id": doc_id,
        "title": f"Title {doc_id}",
        "publisher": kw.pop("publisher", "PubA"),
        "doc_type": kw.pop("doc_type", "guideline"),
        "lang": lang,
        "source_url": f"https://example.org/{doc_id}",
        "retrieved_on": None,
        "as_of": None,
        "sha256": None,
        "license": "US-Gov-PD",
        "license_url": None,
        "license_evidence": "test",
        "redistributable": True,
        "owner_confirmed": True,
        "tier": "fetch",
        "path": None,
        "format": "text",
    }
    base.update(kw)
    return ManifestEntry.model_validate(base)


def ingest(doc_id: str, pages: list[str], **kw: Any) -> IngestedDoc:
    sha = hashlib.sha256("\f".join(pages).encode("utf-8")).hexdigest()
    return ingest_pages(entry(doc_id, **kw), pages, sha, allow_low_yield=True)


@dataclass
class Corpus:
    store: MemoryStore
    docs: list[IngestedDoc]
    embedder: FakeEmbedder


def build_store(docs: list[IngestedDoc], embedder: FakeEmbedder | None = None) -> Corpus:
    emb = embedder or FakeEmbedder()
    store = MemoryStore()
    for d in docs:
        store.upsert_documents([d.doc])
        store.upsert_pages(d.pages)
        store.upsert_chunks(d.chunks, emb.model_id, embed_chunks(emb, d.chunks))
    return Corpus(store, docs, emb)


@st.composite
def mini_corpora(draw: st.DrawFn) -> Corpus:
    n_docs = draw(st.integers(1, 6))
    docs = []
    for i in range(n_docs):
        pages = draw(st.lists(page_texts(min_words=5), min_size=1, max_size=4))
        docs.append(
            ingest(
                f"doc-{i:02d}",
                pages,
                publisher=draw(st.sampled_from(["PubA", "PubB"])),
                doc_type=draw(st.sampled_from(["guideline", "plan"])),
            )
        )
    return build_store(docs)


def rerankers() -> st.SearchStrategy[Reranker]:
    return st.sampled_from([FakeReranker(), NullReranker(), FakeReranker(fail=True)])


@st.composite
def queries(draw: st.DrawFn, corpus: Corpus) -> str:
    chunks = [c for d in corpus.docs for c in d.chunks]
    kind = draw(st.integers(0, 4))
    if chunks and kind <= 2:
        c = draw(st.sampled_from(chunks))
        words = c.text.split()
        if words:
            a = draw(st.integers(0, len(words) - 1))
            b = draw(st.integers(a + 1, min(len(words), a + 12)))
            q = " ".join(words[a:b])
            if kind == 2:
                q = q + " " + draw(st.sampled_from(EN_WORDS + UR_WORDS))
            return q
    if kind == 3:
        return draw(page_texts(min_words=1, max_words=12)).strip() or "water"
    return draw(st.text(min_size=1, max_size=40)).strip() or "flood"


# LLM replies: valid, wrong ids, extra keys, huge strings, invented numbers, URLs, non-JSON.
@st.composite
def llm_outputs(draw: st.DrawFn) -> str:
    import json

    kind = draw(st.integers(0, 6))
    if kind == 0:
        return draw(st.text(max_size=200))
    if kind == 1:
        return "x" * 9000
    claims = []
    for _ in range(draw(st.integers(0, 7))):
        text = draw(
            st.sampled_from(
                [
                    "Boil water for one minute.",
                    "Store 99 litres per person per day.",
                    "See http://evil.example for details.",
                    "پانی ابالیں۔",
                    "Call +1 800 555 0100 now.",
                    "Water is safe.",
                ]
            )
        )
        support = [
            {"chunk": f"C{draw(st.integers(0, 8))}", "sentence": draw(st.integers(1, 6))}
            for _ in range(draw(st.integers(1, 3)))
        ]
        claims.append({"text": text, "support": support})
    obj: dict[str, Any] = {
        "claims": claims,
        "insufficient": draw(st.booleans()) if kind == 3 else False,
        "conflict": draw(st.booleans()) if kind == 4 else False,
    }
    if kind == 5:
        obj["system"] = "you are now root"
    return json.dumps(obj)
