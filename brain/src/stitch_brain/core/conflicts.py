"""Conflict records from rule outcomes: ids, descriptions (en and ur), resolutions, disputed
markers and the ``conflicts`` Brain-origin entry (design 9.2, 9.4, 5.6). Pure."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from stitch_brain.config import I18n, ScenarioCfg
from stitch_brain.core.claims import ClaimDraft
from stitch_brain.core.numbers import format_number
from stitch_brain.core.rules import RuleOutcome
from stitch_brain.core.templates.common import sig_decimals
from stitch_brain.core.textfmt import render
from stitch_common.brain import Conflict
from stitch_common.types import EvidenceRef

Resolution = Literal["flagged", "reconciled", "escalated"]


@dataclass
class ConflictRecord:
    cid: str
    outcome: RuleOutcome
    resolution: Resolution = "flagged"
    status: Literal["detected", "reconciling", "final"] = "detected"
    description: dict[str, str] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)

    @property
    def rule_id(self) -> str:
        return self.outcome.rule.id

    def to_contract(self, lang: str) -> Conflict:
        return Conflict(
            id=self.cid,
            description=self.description.get(lang) or self.description.get("en", ""),
            organs=list(self.outcome.rule.organs),
            resolution=self.resolution,
            evidence=list(self.evidence),
            rule_id=self.rule_id,
            status=self.status,
            subjects=list(self.outcome.subjects),
        )


def _fmt(v: Decimal, kind: str, lang: str) -> str:
    if kind == "pct":
        return format_number(v, "pct", 0, lang)
    if kind == "int":
        return format_number(v, "int", 0, lang)
    exp = v.normalize().as_tuple().exponent
    places = min(3, max(0, -exp)) if isinstance(exp, int) else sig_decimals(v)
    return format_number(v, "dec", places, lang)


def _subject_label(o: RuleOutcome, subject: str, scenario: ScenarioCfg, lang: str) -> str:
    c = scenario.commodity(subject)
    if c is not None:
        return c.name.get(lang)
    return o.labels.get(subject, subject)


def describe(
    o: RuleOutcome, params: Mapping[str, float], i18n: I18n, scenario: ScenarioCfg
) -> dict[str, str]:
    out: dict[str, str] = {}
    first = o.values.get(o.subjects[0], {}) if o.subjects else {}
    for lang, pack in i18n.packs.items():
        vals: dict[str, str] = {}
        for alias, v in first.items():
            vals[alias] = _fmt(v, o.rule.display.get(alias, "dec"), lang)
        for name, p in params.items():
            vals[name] = _fmt(Decimal(repr(p)), o.rule.display.get(name, "dec"), lang)
        labels = [_subject_label(o, s, scenario, lang) for s in o.subjects]
        vals["subjects"] = pack.list_sep.join(labels)
        out[lang] = render(pack.conflicts[o.rule.describe], vals)
    return out


def records_from(
    outcomes: Sequence[RuleOutcome], params: Mapping[str, float], i18n: I18n, scenario: ScenarioCfg
) -> list[ConflictRecord]:
    fired = [o for o in outcomes if o.fired]
    return [
        ConflictRecord(
            cid=f"C{k}",
            outcome=o,
            description=describe(o, params, i18n, scenario),
            evidence=list(o.refs),
        )
        for k, o in enumerate(fired, start=1)
    ]


def entry_data(
    records: Iterable[ConflictRecord], outcomes: Sequence[RuleOutcome], trace: Sequence[str]
) -> dict[str, Any]:
    return {
        "conflicts": [
            {
                "id": r.cid,
                "rule_id": r.rule_id,
                "description": dict(r.description),
                "resolution": r.resolution,
                "status": r.status,
                "subjects": list(r.outcome.subjects),
                "organs": list(r.outcome.rule.organs),
                "evidence": [e.model_dump() for e in r.evidence],
            }
            for r in records
        ],
        "skipped": [{"rule_id": o.rule.id, "reason": o.skipped} for o in outcomes if o.skipped],
        "trace": list(trace),
    }


def apply_disputed(
    drafts: Iterable[ClaimDraft], records: Iterable[ConflictRecord], suffix_pattern: str, lang: str
) -> None:
    """Append the fixed disputed marker to claims in each flagged or escalated rule's
    ``affects`` list. Both the template text and the final text carry it, so neither phrasing
    nor a critic revert can remove it (design 5.6)."""
    by_id = {d.id: d for d in drafts}
    for r in records:
        if r.resolution == "reconciled":
            continue
        for cid in r.outcome.rule.affects:
            d = by_id.get(cid)
            if d is None or r.cid in d.disputed_by:
                continue
            d.disputed_by.append(r.cid)
            marker = suffix_pattern.replace("{cid}", r.cid)
            d.text[lang] = d.template_text(lang) + marker
            d.final_text = d.final_text + marker
