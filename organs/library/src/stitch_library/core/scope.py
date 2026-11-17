"""OUT_OF_SCOPE gate: max cosine between the query and the anchor phrases (design 8.1 step 1),
and the quantity-question rule (step 4). Pure.

Quantity rule (tightened from the design, see ``docs/decisions.md``): a question that asks for a
quantity needs, among the top hits, a sentence that contains a number and shares at least two
content terms with the question. A number elsewhere on the page does not count.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import numpy as np

from stitch_library.core.normalize import search_text
from stitch_library.core.quantities import extract_quantities, numbers_in
from stitch_library.core.tokenize import concept_tokens
from stitch_library.store.base import Vectors

_QUANTITY_PATTERNS = re.compile(
    r"\b(how many|how much|how long|minimum|maximum|at least|per person|per day|per capita|"
    r"quantity|amount|ration|litres|liters|gallons|kg|grams|calories)\b"
    r"|کتنا|کتنی|کتنے|کم از کم|زیادہ سے زیادہ|فی کس|فی شخص|مقدار|راشن",
)
# Words that make a question a quantity question; they are not content terms for the rule.
_QUANTITY_WORDS = frozenset(
    [
        "how",
        "many",
        "much",
        "long",
        "minimum",
        "maximum",
        "least",
        "amount",
        "quantity",
        "per",
        "capita",
        "kitna",
        # Urdu question words for amounts (folded forms); agent-authored, needs native review.
        "کتنا",
        "کتنی",
        "کتنے",
        "فی",
        "کم",
        "از",
        "زیادہ",
        "مقدار",
    ]
)
_DENOMINATORS = frozenset(["person", "day", "each", "every", "household", "family"])
_GENERIC = frozenset(
    [
        "provide",
        "provided",
        "distribute",
        "distributed",
        "give",
        "given",
        "need",
        "needed",
        "require",
        "required",
        "recommend",
        "recommended",
        "should",
        "use",
        "used",
        "get",
        "kept",
        "keep",
        # Urdu auxiliaries and generic verbs (agent-authored, needs native review).
        "چاہیے",
        "چاہئے",
        "چاہئیں",
        "جائے",
        "جائیں",
        "دیا",
        "دی",
        "دیے",
        "فراہم",
        "درکار",
        "ہوتا",
        "ہوتی",
        "ہوتے",
        "ملنا",
        "کیا",
    ]
)
_PER_PERSON_Q = re.compile(
    r"per (person|capita|head)|each person|every person|فی کس|فی شخص|فی فرد|ہر شخص|ہر فرد"
)
_PER_DAY_Q = re.compile(r"per day|a day|each day|every day|daily|روزانہ|یومیہ|فی دن|ہر روز")


def scope_score(qvec: Vectors, anchors: Vectors) -> float:
    if anchors.size == 0:
        return 1.0
    q = np.asarray(qvec, dtype=np.float64).reshape(-1)
    a = np.asarray(anchors, dtype=np.float64)
    norms = np.linalg.norm(a, axis=1) * (np.linalg.norm(q) or 1.0)
    return float(np.max((a @ q) / np.where(norms == 0, 1.0, norms)))


def is_quantity_query(query: str) -> bool:
    return bool(_QUANTITY_PATTERNS.search(search_text(query)))


def query_terms(query: str) -> set[str]:
    return concept_tokens(search_text(query)) - _QUANTITY_WORDS


def asked_per(query: str) -> frozenset[str]:
    """Denominators the question asks for: ``person`` and/or ``day``."""
    s = search_text(query)
    out: set[str] = set()
    if _PER_PERSON_Q.search(s):
        out.add("person")
    if _PER_DAY_Q.search(s):
        out.add("day")
    return frozenset(out)


def topic_terms(query: str) -> set[str]:
    """Query terms without quantity words, denominators and generic verbs."""
    return query_terms(query) - _DENOMINATORS - _GENERIC


def quantity_supported(query: str, sentences: Iterable[str]) -> bool:
    """True when some sentence states a quantity on the question's topic.

    The sentence must share a topic term with the question and contain a number; when the
    question asks "per person" and/or "per day", the sentence needs a quantity whose
    denominator covers what was asked (``one gallon per person per day`` answers a per-person
    per-day question, ``two hours`` does not).
    """
    return any(states_quantity(query, s) for s in sentences)


def _root(tok: str) -> str:
    """English ``-ed`` / ``-ing`` stripped (``boiled`` and ``boil`` match); others unchanged."""
    if tok.isascii():
        if len(tok) > 5 and tok.endswith("ed"):
            return tok[:-2]
        if len(tok) > 6 and tok.endswith("ing"):
            return tok[:-3]
    return tok


def states_quantity(query: str, sentence: str) -> bool:
    """``sentence`` shares a topic term with the question and states the asked quantity."""
    terms = topic_terms(query)
    # At least two shared topic terms (one if the question has only one), as the module
    # docstring states. With one, "water" alone let a sentence about household drinking water
    # answer a question about cholera-centre water (eval q045).
    need = min(2, len(terms))
    shared = {_root(t) for t in terms} & {_root(t) for t in concept_tokens(search_text(sentence))}
    if terms and len(shared) < need:
        return False
    per = asked_per(query)
    if per:
        for q in extract_quantities(sentence):
            parts = set((q.per or "").split("_")) & {"person", "day"}
            if per <= parts:
                return True
        return False
    return bool(numbers_in(sentence))
