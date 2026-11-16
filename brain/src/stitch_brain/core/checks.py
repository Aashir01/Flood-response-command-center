"""Per-claim checks C1 to C5 and C7 (design 10.1). Pure: claim + evidence store + i18n.

C6 (statement entailment for rewritten text) needs the judge and lives in ``critic``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from stitch_brain.config import I18n
from stitch_brain.core.claims import ClaimDraft, Slot
from stitch_brain.core.derive import slot_matches
from stitch_brain.core.evidence import EvidenceStore, ResolvedRef
from stitch_brain.core.numbers import (
    SlotSpec,
    UnitTable,
    check_text,
    identifiers,
    language_ok,
    leaf_numbers,
)
from stitch_brain.core.pointer import parse


@dataclass(frozen=True)
class ClaimIssue:
    claim_id: str
    check: str
    detail: str


def _spec(s: Slot) -> SlotSpec:
    assert isinstance(s.value, Decimal)
    return SlotSpec(s.name, s.value, s.unit, s.decimals, s.fmt)


def text_exempt(draft: ClaimDraft) -> list[str]:
    """Text slot values (names, organ-authored strings) are not re-checked for numbers or
    language: they are evidence values, cited by refs and verified by recompute (C2a)."""
    return [str(s.value) for s in draft.slots.values() if s.fmt == "text" and str(s.value)]


def evidence_values(draft: ClaimDraft, store: EvidenceStore) -> list[Any]:
    out: list[Any] = []
    for r in draft.evidence:
        res = store.resolve(r)
        if isinstance(res, ResolvedRef):
            out.append(res.value)
    return out


def number_issues(
    draft: ClaimDraft,
    text: str,
    store: EvidenceStore,
    units: UnitTable,
    extra_idents: Iterable[str] = (),
) -> list[ClaimIssue]:
    """C2 (numbers, dates, identifiers) and C3 (units) of ``text`` against the claim."""
    nums: list[Decimal] = []
    dates: list[str] = []
    idents: set[str] = set(extra_idents)
    for v in evidence_values(draft, store):
        n, d = leaf_numbers(v, units)
        nums += n
        dates += d
        for s in _strings(v):
            idents.update(identifiers(s, units))
    for s in text_exempt(draft):
        idents.update(identifiers(s, units))
    numeric = [_spec(s) for s in draft.slots.values() if s.numeric]
    slot_dates = [str(s.value)[:10] for s in draft.slots.values() if s.fmt == "date"]
    found = check_text(
        text,
        numeric,
        units,
        extra_numbers=nums,
        extra_dates=dates,
        slot_dates=slot_dates,
        exempt=text_exempt(draft),
        known_idents=idents,
    )
    return [ClaimIssue(draft.id, i.check, f"{i.kind}: {i.detail}") for i in found]


def _strings(v: Any) -> Iterable[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def _has_term(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE) is not None


def claim_issues(
    draft: ClaimDraft,
    store: EvidenceStore,
    i18n: I18n,
    lang: str,
    *,
    text: str | None = None,
    conflict_ids: Iterable[str] = (),
) -> list[ClaimIssue]:
    """Checks C1, C2, C3, C4, C5 and C7 for ``text`` (default: the claim's final text)."""
    t = draft.final_text if text is None else text
    units = UnitTable(i18n.unit_aliases())
    issues: list[ClaimIssue] = []
    # C1 provenance
    if not draft.evidence:
        return [ClaimIssue(draft.id, "C1", "no evidence refs")]
    bad = [r.json_pointer for r in draft.evidence if not store.resolves(r)]
    if bad:
        return [ClaimIssue(draft.id, "C1", f"unresolved ref {bad[0]}")]
    # C2a slot values re-derived from evidence
    for s in draft.slots.values():
        if not slot_matches(s, store):
            issues.append(ClaimIssue(draft.id, "C2", f"slot {s.name} does not re-derive"))
    # C2b, C3 numbers and units in the text
    issues += number_issues(draft, t, store, units, extra_idents=conflict_ids)
    # C4 citations on non-refusal guidance
    is_guidance = draft.section == "guidance" and draft.template_id != "guidance.refusal"
    if is_guidance and not _has_citation(draft, store):
        issues.append(ClaimIssue(draft.id, "C4", "guidance claim without a valid citation"))
    # C5 language
    if not draft.verbatim_foreign and not language_ok(t, lang, units, text_exempt(draft)):
        issues.append(ClaimIssue(draft.id, "C5", f"text is not in {lang}"))
    # C7 labels
    pack = i18n.pack(lang)
    if any(r.organ == "oracle" and r.json_pointer.startswith("/data") for r in draft.evidence):
        if not any(_has_term(t, m) for m in pack.modeled_terms):
            issues.append(ClaimIssue(draft.id, "C7", "oracle claim lacks the modeled label"))
        hit = [f for f in pack.forbidden_oracle_terms if _has_term(t, f)]
        if hit:
            issues.append(ClaimIssue(draft.id, "C7", f"forbidden term {hit[0]!r}"))
    for cid in draft.disputed_by:
        marker = pack.disputed_suffix.replace("{cid}", cid)
        if marker not in t:
            issues.append(ClaimIssue(draft.id, "C7", f"missing disputed marker for {cid}"))
    return issues


def _has_citation(draft: ClaimDraft, store: EvidenceStore) -> bool:
    for r in draft.evidence:
        try:
            toks = parse(r.json_pointer)
        except ValueError:
            continue
        if r.organ != "library" or len(toks) != 3 or toks[:2] != ["data", "citations"]:
            continue
        res = store.resolve(r)
        if not (isinstance(res, ResolvedRef) and isinstance(res.value, dict)):
            continue
        if str(res.value.get("quote") or "").strip() and int(res.value.get("page") or 0) >= 1:
            return True
    return False
