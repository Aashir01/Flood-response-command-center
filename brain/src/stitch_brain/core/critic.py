"""Critic (design 10): re-verifies every claim from the stored evidence, repairs or removes
failures, and reports ``passed``. Pure except for the injected judge (C6), whose verdicts are
cached so repeated passes cannot flip.

Repairs, per pass (``N = 3`` passes):
1. a claim failing C2, C3, C5, C6 or C7 whose text is ``phrased`` or ``translated`` is reverted
   to its template text;
2. a claim that still fails, or fails C1 or C4, or is already template or verbatim text, is
   removed and listed in ``removed_claims`` with a note.

The critic never adds a claim, a ref or text other than the template rendering (BRN-P12), and
running it on its own output changes nothing (BRN-P7)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from stitch_brain.config import I18n, ScenarioCfg
from stitch_brain.core.checks import ClaimIssue, claim_issues, evidence_values
from stitch_brain.core.claims import ClaimDraft, id_token
from stitch_brain.core.evidence import EvidenceStore
from stitch_brain.core.templates.caveats import RECORDED_PREFIX, node_section
from stitch_common.brain import CriticVerdict

MAX_PASSES = 3
REVERTIBLE = frozenset({"C2", "C3", "C5", "C6", "C7"})

#: ``judge(claim, evidence_strings) -> True (entailed) | False``. Exceptions count as False.
Judge = Callable[[ClaimDraft, list[str]], bool]


@dataclass
class CriticPass:
    pass_no: int
    passed: bool
    issues: list[ClaimIssue] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    reverted: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "pass": self.pass_no,
            "passed": self.passed,
            "issues": [
                {"claim_id": i.claim_id, "check": i.check, "detail": i.detail} for i in self.issues
            ],
            "removed": list(self.removed),
            "reverted": list(self.reverted),
        }


@dataclass
class CriticResult:
    drafts: list[ClaimDraft]
    verdict: CriticVerdict
    passes: list[CriticPass]
    reverted: list[str]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.append(v if isinstance(v, str) else json.dumps(v, sort_keys=True, ensure_ascii=False))
    return out


class JudgeCache:
    """Caches judge verdicts per ``(sha256(final_text), sha256(evidence strings))``."""

    def __init__(self, judge: Judge | None) -> None:
        self.judge = judge
        self.verdicts: dict[tuple[str, str], bool] = {}

    def entailed(self, draft: ClaimDraft, store: EvidenceStore) -> bool:
        ev = _strings(evidence_values(draft, store))
        key = (_sha(draft.final_text), _sha("\x1f".join(ev)))
        if key not in self.verdicts:
            if self.judge is None:
                ok = False  # no judge: a rewrite is not trusted, the claim reverts
            else:
                try:
                    ok = bool(self.judge(draft, ev))
                except Exception:
                    ok = False
            self.verdicts[key] = ok
        return self.verdicts[key]


# --- section and briefing checks (S1 to S7) ------------------------------------------------------
@dataclass(frozen=True)
class Requirement:
    check: str
    claim_id: str
    detail: str


def required_claims(
    store: EvidenceStore, scenario: ScenarioCfg, conflict_ids: Sequence[str]
) -> list[Requirement]:
    """Claims the briefing must contain, derived from the evidence (S1 to S6)."""
    req: list[Requirement] = []
    seg = store.ok_node("eyes.segment")
    if seg is not None and seg.data().get("validation", {}).get("validated_for_region") is False:
        req.append(Requirement("S1", "caveat.eyes_unvalidated", "unvalidated Eyes scene"))
    seen: set[str] = set()
    for e in store.entries():
        if e.served_by != "recorded" or not e.ok or e.organ in seen:
            continue
        warns = e.result.get("warnings") or []
        if any(isinstance(w, str) and w.startswith(RECORDED_PREFIX) for w in warns):
            seen.add(e.organ)
            req.append(Requirement("S2", f"caveat.recorded.{e.organ}", f"recorded {e.organ}"))
    for cid in conflict_ids:
        req.append(Requirement("S3", f"caveat.conflict.{id_token(cid)}", f"conflict {cid}"))
    nodes = sorted({e.node_id for e in store.entries() if e.served_by != "brain"})
    for n in nodes:
        latest = store.by_node(n)
        if latest is not None and not latest.ok and node_section(n) is not None:
            req.append(Requirement("S4", f"caveat.missing.{id_token(n)}", f"failed node {n}"))
    for q in scenario.guidance_questions:
        lib = store.ok_node(f"library.{q.id}")
        if lib is not None and lib.data().get("status") == "refused":
            req.append(
                Requirement("S5", f"guidance.{id_token(q.id)}.refusal", f"refusal of {q.id}")
            )
    req.append(Requirement("S6", "caveat.disclaimer", "disclaimer"))
    req.append(Requirement("S6", "caveat.mode", "mode caveat"))
    return req


def section_issues(
    drafts: Sequence[ClaimDraft], required: Sequence[Requirement]
) -> list[ClaimIssue]:
    ids = [d.id for d in drafts]
    out = [
        ClaimIssue(r.claim_id, r.check, f"missing claim for {r.detail}")
        for r in required
        if r.claim_id not in ids
    ]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    out += [ClaimIssue(i, "S7", "duplicate claim id") for i in dup]
    return out


# --- the loop ----------------------------------------------------------------------------------
def _claim_failures(
    d: ClaimDraft,
    store: EvidenceStore,
    i18n: I18n,
    lang: str,
    conflict_ids: Sequence[str],
    judge: JudgeCache,
) -> list[ClaimIssue]:
    issues = claim_issues(d, store, i18n, lang, conflict_ids=conflict_ids)
    rewritten = d.text_source in ("phrased", "translated")
    if not issues and rewritten and not judge.entailed(d, store):
        issues.append(ClaimIssue(d.id, "C6", "rewrite not entailed by the evidence"))
    return issues


def _revert(d: ClaimDraft, lang: str) -> None:
    """Back to the template rendering. A reverted translation of organ text shows the source
    text again, marked ``verbatim_foreign`` (the assembler adds the caveat for it)."""
    translated = d.text_source == "translated"
    d.final_text = d.template_text(lang)
    if d.verbatim:
        d.text_source = "verbatim"
        if translated:
            d.verbatim_foreign = True
    else:
        d.text_source = "template"


def run_critic(
    drafts: Sequence[ClaimDraft],
    store: EvidenceStore,
    i18n: I18n,
    lang: str,
    scenario: ScenarioCfg,
    *,
    conflict_ids: Sequence[str] = (),
    judge: Judge | None = None,
    judge_cache: JudgeCache | None = None,
    prior: CriticVerdict | None = None,
    pre_removed: Mapping[str, str] | None = None,
    max_passes: int = MAX_PASSES,
) -> CriticResult:
    """Check, repair and re-check up to ``max_passes`` times.

    ``prior`` (an earlier verdict) and ``pre_removed`` (claims the renderers already dropped,
    id -> note) are merged into ``removed_claims`` and ``notes`` in stable order, which is what
    makes the critic idempotent on its own output."""
    cache = judge_cache or JudgeCache(judge)
    work = [d.model_copy(deep=True) for d in drafts]
    removed: list[str] = list(prior.removed_claims) if prior else []
    notes: list[str] = list(prior.notes) if prior else []
    for cid, note in (pre_removed or {}).items():
        if cid not in removed:
            removed.append(cid)
        if note not in notes:
            notes.append(note)
    required = required_claims(store, scenario, conflict_ids)
    passes: list[CriticPass] = []
    reverted_all: list[str] = []
    passed = False
    for k in range(1, max_passes + 1):
        issues: list[ClaimIssue] = []
        failing: dict[str, list[ClaimIssue]] = {}
        for d in work:
            f = _claim_failures(d, store, i18n, lang, conflict_ids, cache)
            if f:
                failing[d.id] = f
                issues += f
        sec = section_issues(work, required)
        issues += sec
        if not failing:
            passed = not sec
            passes.append(CriticPass(k, passed, issues))
            break
        last = k == max_passes
        rev: list[str] = []
        rem: list[str] = []
        kept: list[ClaimDraft] = []
        for d in work:
            f = failing.get(d.id) or []
            if not f:
                kept.append(d)
                continue
            checks = {i.check for i in f}
            rewritten = d.text_source in ("phrased", "translated")
            if rewritten and checks <= REVERTIBLE and not last:
                _revert(d, lang)
                rev.append(d.id)
                kept.append(d)
                continue
            rem.append(d.id)
            if d.id not in removed:
                removed.append(d.id)
            note = f"{d.id}: {f[0].check} {f[0].detail}"
            if note not in notes:
                notes.append(note)
        work = kept
        reverted_all += [r for r in rev if r not in reverted_all]
        # the last pass removes what still fails, so no failing claim is ever emitted (BRN-P1)
        passes.append(CriticPass(k, False, issues, rem, rev))
    return CriticResult(
        drafts=work,
        verdict=CriticVerdict(passed=passed, removed_claims=removed, notes=notes),
        passes=passes,
        reverted=reverted_all,
    )


__all__ = [
    "MAX_PASSES",
    "CriticPass",
    "CriticResult",
    "Judge",
    "JudgeCache",
    "Requirement",
    "required_claims",
    "run_critic",
    "section_issues",
]
