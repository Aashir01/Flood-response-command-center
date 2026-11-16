"""Brain models (mcp-contracts.md section 8): ``Briefing``, ``Claim``, ``Conflict``, ``TaskEvent``.

Single-object part of BRN-P1: every ``Claim`` carries at least one ``EvidenceRef``. Resolving
each reference against the run's evidence store is the Brain's job.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from stitch_common.base import Contract
from stitch_common.types import EvidenceRef, Lang, Mode, Unit


class Claim(Contract):
    id: str = Field(min_length=1)
    text: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    kind: Literal["number", "statement", "recommendation"]


class Section(Contract):
    id: Literal["extent", "forecast", "guidance", "allocation", "caveats"]
    title: str
    status: Literal["ok", "partial", "unavailable"]
    claims: list[Claim]


class Conflict(Contract):
    id: str = Field(min_length=1)
    description: str
    organs: list[str]
    resolution: Literal["flagged", "reconciled", "escalated"]
    evidence: list[EvidenceRef]


class CriticVerdict(Contract):
    passed: bool
    removed_claims: list[str]
    notes: list[str]


class Briefing(Contract):
    briefing_id: str = Field(min_length=1)
    scenario: str
    lang: Lang
    mode: Mode
    sections: list[Section]
    conflicts: list[Conflict]
    critic: CriticVerdict
    confidence: Unit
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def _unique_ids(self) -> Briefing:
        sids = [s.id for s in self.sections]
        if len(set(sids)) != len(sids):
            raise ValueError("section ids must be unique")
        cids = [c.id for s in self.sections for c in s.claims]
        if len(set(cids)) != len(cids):
            raise ValueError("claim ids must be unique within a briefing")
        return self


class TaskEvent(Contract):
    event: Literal["plan", "organ_call", "organ_result", "conflict", "critic", "briefing", "error"]
    ts: AwareDatetime
    task_id: str = Field(min_length=1)
    organ: str | None = None
    tool: str | None = None
    payload: dict[str, Any]
