"""Internal claim model (design 5.1). Richer than the contract ``Claim``; projected at assembly."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from stitch_common.brain import Claim, ClaimLabel
from stitch_common.types import EvidenceRef

SectionId = Literal["extent", "forecast", "guidance", "allocation", "caveats"]
SECTION_ORDER: tuple[SectionId, ...] = ("extent", "forecast", "guidance", "allocation", "caveats")
Kind = Literal["number", "statement", "recommendation"]
Fmt = Literal["int", "dec", "pct", "date", "text"]
TextSource = Literal["template", "phrased", "translated", "verbatim"]
NUMERIC_FMTS = frozenset({"int", "dec", "pct"})

_ID_TOKEN = re.compile(r"[^a-z0-9_]+")


def id_token(value: str) -> str:
    """A claim-id segment from a subject (district id, commodity id): ``[a-z0-9_]``."""
    tok = _ID_TOKEN.sub("_", value.lower()).strip("_")
    return tok or "x"


class DerivationCall(BaseModel):
    """A named pure function from ``core.derive.DERIVATIONS`` over the slot's refs (in order)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    fn: str
    params: dict[str, Any] = Field(default_factory=dict)


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    name: str
    value: Decimal | str | date
    unit: str | None = None
    decimals: int | None = None
    fmt: Fmt = "text"
    refs: list[EvidenceRef] = Field(min_length=1)
    derivation: DerivationCall | None = None

    @property
    def numeric(self) -> bool:
        return self.fmt in NUMERIC_FMTS


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    section: SectionId
    kind: Kind
    template_id: str
    slots: dict[str, Slot] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(min_length=1)
    verbatim: bool = False
    verbatim_foreign: bool = False
    text: dict[str, str] = Field(default_factory=dict)  # rendered template text per language
    final_text: str = ""
    text_source: TextSource = "template"
    disputed_by: list[str] = Field(default_factory=list)
    labels: list[ClaimLabel] = Field(default_factory=list)
    order: int = 0  # position in the section table (design 5.3)

    def template_text(self, lang: str) -> str:
        return self.text.get(lang) or self.text.get("en") or ""

    def to_contract(self) -> Claim:
        seen: set[tuple[str, str, str, str]] = set()
        refs: list[EvidenceRef] = []
        for r in self.evidence:
            k = (r.run_id, r.organ, r.tool, r.json_pointer)
            if k not in seen:
                seen.add(k)
                refs.append(r)
        labels = sorted(set(self.labels), key=_LABEL_ORDER.index)
        return Claim(id=self.id, text=self.final_text, evidence=refs, kind=self.kind, labels=labels)


_LABEL_ORDER: list[str] = ["modeled", "unvalidated", "recorded", "demo", "refusal", "disputed"]
