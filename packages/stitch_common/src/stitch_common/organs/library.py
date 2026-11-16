"""library-mcp tool I/O (mcp-contracts.md section 5).

The answered/refused invariant (LIB-P1) is enforced on ``AnswerWithCitationsOut``. Stricter
reading: an answered result has a non-empty answer, at least one citation, at least one claim,
and every claim cites only indices that exist; a refused result has no answer, no citations and
no claims.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from stitch_common.base import Contract
from stitch_common.types import Citation, LangOrAuto


class Filters(Contract):
    publisher: list[str] | None = None
    doc_type: list[str] | None = None


class SearchGuidanceIn(Contract):
    query: str = Field(min_length=1)
    lang: LangOrAuto | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    filters: Filters | None = None


class Hit(Contract):
    doc_id: str
    page: int = Field(ge=1)
    score: float
    bm25: float
    dense: float
    rerank: float | None
    text: str
    lang: str


class SearchGuidanceOut(Contract):
    hits: list[Hit]


class AnswerWithCitationsIn(Contract):
    query: str = Field(min_length=1)
    lang: LangOrAuto | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)


class AnswerClaim(Contract):
    text: str = Field(min_length=1)
    citation_idx: list[int]


class Refusal(Contract):
    reason: Literal["INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "CONFLICTING_EVIDENCE"]
    closest_hits: list[Citation]


class AnswerWithCitationsOut(Contract):
    status: Literal["answered", "refused"]
    answer: str | None
    citations: list[Citation]
    refusal: Refusal | None
    claims: list[AnswerClaim]

    @model_validator(mode="after")
    def _answered_xor_refused(self) -> AnswerWithCitationsOut:
        if self.status == "answered":
            if not self.answer:
                raise ValueError("answered requires a non-empty answer")
            if not self.citations:
                raise ValueError("answered requires at least one citation")
            if self.refusal is not None:
                raise ValueError("answered must not carry a refusal")
            if not self.claims:
                raise ValueError("answered requires at least one claim")
            n = len(self.citations)
            for claim in self.claims:
                if not claim.citation_idx:
                    raise ValueError("every claim needs at least one citation_idx")
                if any(i < 0 or i >= n for i in claim.citation_idx):
                    raise ValueError("claim citation_idx out of range")
        else:
            if self.refusal is None:
                raise ValueError("refused requires a refusal")
            if self.answer is not None or self.citations or self.claims:
                raise ValueError("refused must have no answer, citations or claims")
        return self
