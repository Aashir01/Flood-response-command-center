"""Critic (task 17): checks C1 to C7 and S1 to S7, the repair loop, BRN-P7 (idempotent) and
BRN-P12 (no additions)."""

from __future__ import annotations

from typing import Any

from brain_testkit import all_claims, render_world, run_briefing, world_store
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.config import load_i18n, load_scenarios
from stitch_brain.core.claims import ClaimDraft
from stitch_brain.core.critic import CriticResult, run_critic
from stitch_common.types import EvidenceRef

SC = load_scenarios()["demo-sindh-2022"]
I18N = load_i18n()


def _crit(drafts: list[ClaimDraft], store: Any, **kw: Any) -> CriticResult:
    return run_critic(drafts, store, I18N, "en", SC, **kw)


def _base() -> tuple[Any, list[ClaimDraft]]:
    store = world_store()
    return store, render_world(store)


def _by_id(drafts: list[ClaimDraft], cid: str) -> ClaimDraft:
    return next(d for d in drafts if d.id == cid)


def test_clean_world_passes_without_changes() -> None:
    store, drafts = _base()
    res = _crit(drafts, store)
    assert res.verdict.passed, [p.payload() for p in res.passes]
    assert [d.final_text for d in res.drafts] == [d.final_text for d in drafts]
    assert len(res.passes) == 1


def test_c1_unresolved_ref_removes_the_claim() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "allocation.summary")
    d.evidence = [EvidenceRef(run_id="nope", organ="ledger", tool="x", json_pointer="/data")]
    res = _crit(drafts, store)
    assert "allocation.summary" in res.verdict.removed_claims
    assert any(n.startswith("allocation.summary: C1") for n in res.verdict.notes)
    assert res.verdict.passed  # the briefing is consistent after the removal


def test_c2_wrong_number_in_template_text_is_removed() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "extent.flood_area")
    d.final_text = d.final_text.replace("km2", "km2 and 999999 more", 1)
    res = _crit(drafts, store)
    assert "extent.flood_area" in res.verdict.removed_claims
    assert any("C2" in n for n in res.verdict.notes)


def test_c2_wrong_number_in_phrased_text_reverts_to_template() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "allocation.summary")
    template = d.final_text
    d.final_text = "Roughly 12345678 people are covered."
    d.text_source = "phrased"
    res = _crit(drafts, store, judge=lambda *_: True)
    out = _by_id(res.drafts, "allocation.summary")
    assert out.final_text == template and out.text_source == "template"
    assert res.reverted == ["allocation.summary"]
    assert res.verdict.passed and not res.verdict.removed_claims


def test_c3_swapped_unit_is_caught() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "extent.flood_area")
    d.final_text = d.final_text.replace("km2", "m3/s", 1)
    res = _crit(drafts, store)
    issues = [i for p in res.passes for i in p.issues if i.claim_id == "extent.flood_area"]
    assert any(i.check in ("C2", "C3") for i in issues)
    assert "extent.flood_area" in res.verdict.removed_claims


def test_c4_guidance_without_citation_is_removed() -> None:
    store, drafts = _base()
    g = next(d for d in drafts if d.section == "guidance" and d.template_id == "guidance.claim")
    g.evidence = [r for r in g.evidence if "/citations/" not in r.json_pointer]
    res = _crit(drafts, store)
    assert g.id in res.verdict.removed_claims
    assert any(n.startswith(f"{g.id}: C4") for n in res.verdict.notes)


def test_c5_wrong_language_reverts_phrased_and_removes_template() -> None:
    store, drafts = _base()
    a = _by_id(drafts, "caveat.disclaimer")
    a.final_text = "یہ ایک فیصلہ سازی میں مدد کا نظام ہے"
    res = _crit(drafts, store)
    assert "caveat.disclaimer" in res.verdict.removed_claims
    assert not res.verdict.passed  # S6 now fails: the disclaimer is required


def test_c6_not_entailed_rewrite_reverts() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "allocation.summary")
    template = d.final_text
    d.text_source = "phrased"  # same text, but the judge says no
    res = _crit(drafts, store, judge=lambda *_: False)
    assert _by_id(res.drafts, "allocation.summary").final_text == template
    assert res.reverted == ["allocation.summary"]


def test_c6_judge_exception_counts_as_not_entailed() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "allocation.summary")
    d.text_source = "phrased"

    def boom(*_: Any) -> bool:
        raise RuntimeError("judge down")

    res = _crit(drafts, store, judge=boom)
    assert res.reverted == ["allocation.summary"]


def test_c7_oracle_claim_with_forbidden_term_is_removed() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "forecast.peak")
    d.final_text = d.final_text.replace("Modeled", "Observed gauge", 1)
    res = _crit(drafts, store)
    assert "forecast.peak" in res.verdict.removed_claims
    assert any("C7" in n for n in res.verdict.notes if n.startswith("forecast.peak"))


def test_c7_missing_disputed_marker() -> None:
    store, drafts = _base()
    d = _by_id(drafts, "allocation.summary")
    d.disputed_by = ["C1"]
    res = _crit(drafts, store, conflict_ids=["C1"])
    assert "allocation.summary" in res.verdict.removed_claims


def test_section_checks_s1_to_s7() -> None:
    store, drafts = _base()
    keep = [
        d
        for d in drafts
        if d.id not in ("caveat.eyes_unvalidated", "caveat.recorded.eyes", "caveat.mode")
    ]
    keep.append(keep[0].model_copy(deep=True))  # duplicate id
    res = _crit(keep, store, conflict_ids=["C9"])
    checks = {i.check for i in res.passes[-1].issues}
    assert {"S1", "S2", "S3", "S6", "S7"} <= checks
    assert not res.verdict.passed


def test_s4_and_s5_failed_node_and_refusal() -> None:
    from brain_testkit import fixture_result

    failed = fixture_result("eyes", "segment_flood", "demo-sindh-2022")
    failed = {**failed, "ok": False, "data": None}
    failed["error"] = {"code": "TIMEOUT", "message": "t", "retryable": True}
    store = world_store({"eyes.segment": failed})
    drafts = [d for d in render_world(store) if not d.id.startswith("caveat.missing")]
    drafts = [d for d in drafts if not d.id.endswith(".refusal")]
    res = _crit(drafts, store)
    checks = {i.check for i in res.passes[-1].issues}
    assert "S4" in checks and "S5" in checks


async def test_critic_failure_adds_the_caveat_and_lowers_confidence() -> None:
    from stitch_brain.config import I18n

    base = await run_briefing()
    i18n = load_i18n()
    packs = dict(i18n.packs)
    en = packs["en"]
    # an i18n pack whose disclaimer pattern contains an invented number: C2 removes the
    # disclaimer, so S6 fails and the briefing must carry caveat.critic_failed
    bad = en.model_copy(
        update={"templates": {**en.templates, "caveat.disclaimer": "{text} 77 percent sure."}}
    )
    packs["en"] = bad
    res = await run_briefing(i18n=I18n(packs=packs))
    b = res.briefing
    assert b.critic.passed is False
    ids = [c.id for c in all_claims(b)]
    assert "caveat.critic_failed" in ids and "caveat.disclaimer" not in ids
    assert "caveat.disclaimer" in b.critic.removed_claims
    assert b.confidence < base.briefing.confidence
    events = [e for e in res.events if e.event == "critic"]
    assert events and events[-1].payload["passed"] is False
    assert [e.event for e in res.events].index("critic") < [e.event for e in res.events].index(
        "briefing"
    )


# --- properties --------------------------------------------------------------------------------
FAULTS = ("number", "ref", "unit", "lang", "caveat", "phrased_number", "label")


def _inject(drafts: list[ClaimDraft], fault: str, idx: int) -> list[ClaimDraft]:
    out = [d.model_copy(deep=True) for d in drafts]
    nums = [d for d in out if d.slots and any(s.numeric for s in d.slots.values())]
    d = nums[idx % len(nums)]
    if fault == "number":
        d.final_text = d.final_text + " 424242"
    elif fault == "ref":
        d.evidence = [EvidenceRef(run_id="x", organ="eyes", tool="t", json_pointer="/data/zz")]
    elif fault == "unit":
        d.final_text = d.final_text.replace("km2", "kg").replace("m3/s", "km2")
    elif fault == "lang":
        d.final_text = "سیلاب کا پانی بہت زیادہ ہے اور یہ جملہ اردو میں ہے"
    elif fault == "caveat":
        out = [x for x in out if x.id != "caveat.mode"]
    elif fault == "phrased_number":
        d.final_text = d.final_text + " 31337"
        d.text_source = "phrased"
    elif fault == "label":
        f = next(x for x in out if x.id == "forecast.peak")
        f.final_text = f.final_text.replace("Modeled", "Measured", 1)
    return out


def _snapshot(res: CriticResult) -> Any:
    return (
        [
            (d.id, d.final_text, d.text_source, [r.model_dump() for r in d.evidence])
            for d in res.drafts
        ],
        res.verdict.model_dump(),
    )


@settings(deadline=None)
@given(st.lists(st.tuples(st.sampled_from(FAULTS), st.integers(0, 50)), max_size=4))
def test_brn_p7_critic_is_idempotent(faults: list[tuple[str, int]]) -> None:
    store, drafts = _base()
    for f, i in faults:
        drafts = _inject(drafts, f, i)
    once = _crit(drafts, store, judge=lambda *_: True)
    twice = _crit(once.drafts, store, judge=lambda *_: True, prior=once.verdict)
    assert _snapshot(once) == _snapshot(twice)
    assert len(twice.passes) == 1


@settings(deadline=None)
@given(st.lists(st.tuples(st.sampled_from(FAULTS), st.integers(0, 50)), max_size=4))
def test_brn_p12_critic_never_adds(faults: list[tuple[str, int]]) -> None:
    store, drafts = _base()
    for f, i in faults:
        drafts = _inject(drafts, f, i)
    before = {d.id: d for d in drafts}
    res = _crit(drafts, store, judge=lambda *_: True)
    assert {d.id for d in res.drafts} <= set(before)
    for d in res.drafts:
        b = before[d.id]
        refs = {r.model_dump_json() for r in b.evidence}
        assert {r.model_dump_json() for r in d.evidence} <= refs
        assert d.final_text in (b.final_text, b.template_text("en"))
    # every claim that remains passes every claim check
    again = _crit(res.drafts, store, judge=lambda *_: True)
    assert not again.passes[-1].removed
    assert all(i.check.startswith("S") for i in again.passes[-1].issues)
