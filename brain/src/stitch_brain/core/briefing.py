"""Briefing assembly: section statuses (design 7.4), ordering, labels, projection to the contract
``Briefing``, and id normalization for determinism checks (design 15)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from stitch_brain.core.claims import SECTION_ORDER, ClaimDraft, SectionId
from stitch_brain.core.evidence import EvidenceStore
from stitch_common.brain import (
    Briefing,
    BriefingOrgan,
    ClaimLabel,
    Conflict,
    CriticVerdict,
    Section,
)

SECTION_NODES: dict[str, tuple[str, ...]] = {
    "extent": ("eyes.segment", "eyes.compare"),
    "forecast": ("oracle.forecast",),
    "allocation": ("ledger.optimize",),
}


@dataclass
class StatusInputs:
    node_ok: Mapping[str, bool]  # by node id
    library_nodes: Sequence[str]
    refusals: int = 0
    exceedance_rendered: bool = True
    ledger_status: str | None = None
    ledger_gap: float | None = None
    removed_by_section: Mapping[str, int] = field(default_factory=dict)
    kept_by_section: Mapping[str, int] = field(default_factory=dict)


def section_status(section: str, s: StatusInputs) -> tuple[str, list[str]]:
    """Return (status, missing node names) for one section."""
    ok = s.node_ok
    missing: list[str] = []
    if section == "caveats":
        return "ok", []
    if section == "extent":
        nodes = SECTION_NODES["extent"]
        missing = [n for n in nodes if not ok.get(n)]
        status = (
            "ok" if not missing else ("unavailable" if len(missing) == len(nodes) else "partial")
        )
    elif section == "forecast":
        if not ok.get("oracle.forecast"):
            status, missing = "unavailable", ["oracle.forecast"]
        else:
            status = "ok" if s.exceedance_rendered else "partial"
            if not s.exceedance_rendered:
                missing = ["forecast.exceedance (no danger threshold)"]
    elif section == "guidance":
        missing = [n for n in s.library_nodes if not ok.get(n)]
        if not s.library_nodes or len(missing) == len(s.library_nodes):
            status = "unavailable"
        elif missing or s.refusals:
            status = "partial"
            if s.refusals:
                missing.append(f"{s.refusals} refused question(s)")
        else:
            status = "ok"
    elif section == "allocation":
        if not (ok.get("ledger.final") or ok.get("ledger.optimize")) or s.ledger_status in (
            None,
            "infeasible",
        ):
            status, missing = "unavailable", ["ledger.optimize"]
        else:
            missing = [n for n in ("eyes.compare", "oracle.forecast") if not ok.get(n)]
            gap = s.ledger_gap or 0.0
            status = "partial" if missing or (s.ledger_status == "feasible" and gap > 0) else "ok"
    else:
        raise ValueError(section)
    removed = s.removed_by_section.get(section, 0)
    kept = s.kept_by_section.get(section, 0)
    if removed:
        status = "unavailable" if kept == 0 else ("partial" if status == "ok" else status)
    if status != "unavailable" and kept == 0 and section != "caveats":
        status = "unavailable"
    return status, missing


def labels_for(
    draft: ClaimDraft, store: EvidenceStore, unvalidated_extent: bool
) -> list[ClaimLabel]:
    labels: list[ClaimLabel] = list(draft.labels)
    for ref in draft.evidence:
        e = store.get(ref.run_id)
        if e is None:
            continue
        if e.organ == "oracle" and "modeled" not in labels:
            labels.append("modeled")
        if e.served_by == "recorded" and "recorded" not in labels:
            labels.append("recorded")
        if e.organ != "brain" and e.mode == "demo" and "demo" not in labels:
            labels.append("demo")
    if draft.section == "extent" and unvalidated_extent and "unvalidated" not in labels:
        labels.append("unvalidated")
    if draft.template_id == "guidance.refusal" and "refusal" not in labels:
        labels.append("refusal")
    if draft.disputed_by and "disputed" not in labels:
        labels.append("disputed")
    return labels


def order_drafts(drafts: Iterable[ClaimDraft]) -> list[ClaimDraft]:
    rank = {s: i for i, s in enumerate(SECTION_ORDER)}
    return sorted(drafts, key=lambda c: (rank[c.section], c.order, c.id))


def assemble(
    *,
    briefing_id: str,
    scenario: str,
    lang: str,
    mode: str,
    drafts: Sequence[ClaimDraft],
    statuses: Mapping[str, tuple[str, list[str]]],
    titles: Mapping[str, str],
    conflicts: Sequence[Conflict],
    critic: CriticVerdict,
    confidence: float,
    generated_at: datetime,
    organs: Sequence[BriefingOrgan],
    disclaimer: str | None,
) -> Briefing:
    by_section: dict[SectionId, list[ClaimDraft]] = {s: [] for s in SECTION_ORDER}
    for d in order_drafts(drafts):
        by_section[d.section].append(d)
    sections = [
        Section(
            id=s,
            title=titles.get(s, s),
            status=statuses[s][0],
            claims=[d.to_contract() for d in by_section[s]],
            missing=list(statuses[s][1]),
        )
        for s in SECTION_ORDER
    ]
    return Briefing(
        briefing_id=briefing_id,
        scenario=scenario,
        lang=lang,
        mode=mode,
        sections=sections,
        conflicts=list(conflicts),
        critic=critic,
        confidence=max(0.0, min(1.0, confidence)),
        generated_at=generated_at,
        organs=list(organs),
        disclaimer=disclaimer,
    )


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


def normalize_ids(doc: Any) -> Any:
    """Replace uuids and timestamps by ordinals in first-appearance order (design 15)."""
    seen: dict[str, str] = {}

    def norm_str(s: str) -> str:
        def rep(m: re.Match[str], kind: str) -> str:
            key = m.group(0)
            if key not in seen:
                seen[key] = f"<{kind}{len(seen)}>"
            return seen[key]

        s = _UUID.sub(lambda m: rep(m, "id"), s)
        return _TS.sub(lambda m: rep(m, "ts"), s)

    def walk(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            return norm_str(x)
        return x

    return walk(doc)
