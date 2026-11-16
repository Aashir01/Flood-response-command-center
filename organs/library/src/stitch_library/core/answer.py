"""Claim verification and answer assembly (design 7.3). Pure apart from page lookups.

Each draft claim names the page spans that support it. In order, a claim is dropped (with a
warning) when:

1. ``resolve``: a support does not refer to a known chunk sentence (LLM path, done by the caller);
2. ``verbatim``: the quote sliced from the stored page is not ``page.text[start:end]``;
3. ``numbers``: a number in the claim does not occur in its quotes (LIB-P14);
4. ``lexical``: same-language claims need at least half of their content terms in the quotes;
   cross-language claims skip this check and rely on the number check (a known, weaker case);
5. ``links``: a URL, e-mail address or phone number in the claim does not occur in its quotes.

The answer text is the surviving claim texts joined with a space, so every answer sentence has a
``claims[]`` entry. ``assemble_answer`` never returns ``answered`` without citations (LIB-P1).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from stitch_common.organs.library import (
    AnswerClaim,
    AnswerWithCitationsOut,
    Generation,
    Quantity,
    Refusal,
)
from stitch_common.types import Citation
from stitch_library.core.citations import is_verbatim, make_citation
from stitch_library.core.decide import RefusalReason
from stitch_library.core.lang import detect_query_lang
from stitch_library.core.normalize import search_text
from stitch_library.core.quantities import extract_quantities, numbers_in
from stitch_library.core.tokenize import content_tokens
from stitch_library.store.base import DocRow, PageRow

LEXICAL_MIN = 0.5
_LINK = re.compile(
    r"(https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{7,}\d|\b[a-z0-9-]+\.(?:com|org|net|gov|int|pk|io)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Support:
    doc_id: str
    page: int
    start: int
    end: int


@dataclass(frozen=True)
class DraftClaim:
    text: str
    supports: tuple[Support, ...]


@dataclass
class VerifiedClaim:
    text: str
    citations: list[Citation]


@dataclass
class Verification:
    claims: list[VerifiedClaim] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


PageLookup = Callable[[str, int], PageRow | None]
DocLookup = Callable[[str], DocRow | None]


def links_in(text: str) -> set[str]:
    return {m.group(0).rstrip(".,;)") for m in _LINK.finditer(text)}


def claim_checks(text: str, quotes: Sequence[Citation]) -> str | None:
    """Return the failing check name, or None if the claim passes steps 3 to 5."""
    joined = " ".join(q.quote for q in quotes)
    if not numbers_in(text) <= numbers_in(joined):
        return "numbers"
    claim_lang = detect_query_lang(text)
    if all(q.lang == claim_lang for q in quotes):
        terms = content_tokens(search_text(text))
        if terms:
            have = content_tokens(search_text(joined))
            if len(terms & have) / len(terms) < LEXICAL_MIN:
                return "lexical"
    for link in links_in(text):
        if link not in joined:
            return "links"
    return None


def verify_claims(drafts: Sequence[DraftClaim], pages: PageLookup, docs: DocLookup) -> Verification:
    out = Verification()
    for i, d in enumerate(drafts):
        cites: list[Citation] = []
        failed: str | None = None
        if not d.supports:
            failed = "resolve"
        for sup in d.supports:
            page, doc = pages(sup.doc_id, sup.page), docs(sup.doc_id)
            if page is None or doc is None or page.status != "ok":
                failed = "resolve"
                break
            c = make_citation(doc, page, sup.start, sup.end)
            if not c.quote or not is_verbatim(page, c):
                failed = "verbatim"
                break
            cites.append(c)
        if failed is None:
            failed = claim_checks(d.text, cites)
        if failed is not None:
            out.warnings.append(f"CLAIM_DROPPED:{i}:{failed}")
            continue
        out.claims.append(VerifiedClaim(d.text.strip(), cites))
    return out


def quantities_for(claims: Sequence[VerifiedClaim]) -> list[Quantity]:
    out: list[Quantity] = []
    for i, c in enumerate(claims):
        for q in extract_quantities(c.text):
            out.append(Quantity(value=q.value, unit=q.unit, per=q.per, claim_idx=i))
    return out


def refusal(
    reason: RefusalReason, closest: Sequence[Citation], generation: Generation | None
) -> AnswerWithCitationsOut:
    return AnswerWithCitationsOut(
        status="refused",
        answer=None,
        citations=[],
        refusal=Refusal(reason=reason, closest_hits=list(closest)[:5]),
        claims=[],
        generation=generation,
        quantities=[],
    )


def assemble_answer(
    claims: Sequence[VerifiedClaim],
    closest: Sequence[Citation],
    generation: Generation | None,
) -> AnswerWithCitationsOut:
    citations: list[Citation] = []
    index: dict[tuple[str, int, int, int], int] = {}
    out_claims: list[AnswerClaim] = []
    kept: list[VerifiedClaim] = []
    for c in claims:
        idx: list[int] = []
        for cit in c.citations:
            key = (cit.doc_id, cit.page, cit.span[0], cit.span[1])
            if key not in index:
                index[key] = len(citations)
                citations.append(cit)
            if index[key] not in idx:
                idx.append(index[key])
        if c.text and idx:
            out_claims.append(AnswerClaim(text=c.text, citation_idx=idx))
            kept.append(c)
    if not out_claims or not citations:
        return refusal("INSUFFICIENT_EVIDENCE", closest, generation)
    return AnswerWithCitationsOut(
        status="answered",
        answer=" ".join(c.text for c in out_claims),
        citations=citations,
        refusal=None,
        claims=out_claims,
        generation=generation,
        quantities=quantities_for(kept),
    )
