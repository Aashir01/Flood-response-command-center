"""Brain models (mcp-contracts.md section 8): ``Briefing``, ``Claim``, ``Conflict``, ``TaskEvent``.

Contract v0.4 additions are all optional (defaults keep v0.3 payloads valid). Browser-facing HTTP
models live in ``stitch_common.brain_api``.

Single-object part of BRN-P1: every ``Claim`` carries at least one ``EvidenceRef``. Resolving
each reference against the run's evidence store is the Brain's job.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from stitch_common.base import Contract
from stitch_common.types import EvidenceRef, Lang, Mode, OrganName, Unit

ClaimLabel = Literal["modeled", "unvalidated", "recorded", "demo", "refusal", "disputed"]
OrganStatus = Literal["ready", "degraded", "unwell", "disabled", "incompatible"]
ServedBy = Literal["real", "recorded"]


class Claim(Contract):
    id: str = Field(min_length=1)
    text: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    kind: Literal["number", "statement", "recommendation"]
    labels: list[ClaimLabel] = Field(default_factory=list)  # v0.4: honesty labels for the UI


class Section(Contract):
    id: Literal["extent", "forecast", "guidance", "allocation", "caveats"]
    title: str
    status: Literal["ok", "partial", "unavailable"]
    claims: list[Claim]
    missing: list[str] = Field(default_factory=list)  # v0.4: what is missing, by name


class Conflict(Contract):
    id: str = Field(min_length=1)
    description: str
    organs: list[str]
    resolution: Literal["flagged", "reconciled", "escalated"]
    evidence: list[EvidenceRef]
    rule_id: str | None = None  # v0.4
    status: Literal["detected", "reconciling", "final"] | None = None  # v0.4
    subjects: list[str] = Field(default_factory=list)  # v0.4: affected keys, e.g. district ids


class CriticVerdict(Contract):
    passed: bool
    removed_claims: list[str]
    notes: list[str]


class BriefingOrgan(Contract):
    """v0.4: which organ served the briefing, and whether it was a real call or a recording."""

    organ: OrganName
    status: OrganStatus
    served_by: ServedBy | None = None


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
    organs: list[BriefingOrgan] = Field(default_factory=list)  # v0.4
    disclaimer: str | None = None  # v0.4

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
    event: Literal[
        "plan", "organ_call", "organ_result", "conflict", "critic", "briefing", "error", "notice"
    ]
    ts: AwareDatetime
    task_id: str = Field(min_length=1)
    organ: str | None = None
    tool: str | None = None
    payload: dict[str, Any]
