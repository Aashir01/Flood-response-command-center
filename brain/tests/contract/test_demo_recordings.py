"""Recorded LLM replies for the demo scenarios (task 30; design 12, 13).

``data/demo/llm/brain.jsonl`` holds Nebius replies for phrasing, Urdu translation and the
judge, recorded once by ``python -m evals.brain.record_llm --provider nebius``. Replayed under
``FakeLLM`` every reply goes through the same code checks as a live one, so these tests prove
that the offline demo uses the recorded prose where it passes and the template otherwise, and
that BRN-P1 and BRN-P2 still hold."""

from __future__ import annotations

import json
from typing import Any

import pytest
from brain_testkit import all_claims

from evals.brain.record_llm import CheckReport, check, recordings_path
from stitch_brain.config import load_i18n
from stitch_brain.core.checks import claim_issues
from stitch_brain.core.numbers import UnitTable, scan
from stitch_common.llm import load_recordings


@pytest.fixture(scope="module")
def report() -> CheckReport:
    return check()


def test_demo_recordings_current(report: CheckReport) -> None:
    """Fails with the stale keys when a template or prompt changed: re-record."""
    assert not report.misses, "stale recordings (re-run evals.brain.record_llm):\n" + "\n".join(
        f"{sc}/{lang} {purpose} {key}" for sc, lang, purpose, key in report.misses
    )


def test_recordings_are_provider_replies_with_the_brain_purposes() -> None:
    recs = load_recordings(recordings_path())
    assert recs
    assert {r.purpose for r in recs.values()} <= {"brain.phrase", "brain.translate", "brain.judge"}
    for line in recordings_path().read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert obj["provider"] == "nebius"
        assert "api_key" not in line.lower()


def _p1_p2(res: Any, lang: str) -> None:
    i18n = load_i18n()
    units = UnitTable(i18n.unit_aliases())
    by_id = {d.id: d for d in res.drafts}
    for c in all_claims(res.briefing):
        assert c.evidence, c.id  # BRN-P1: at least one ref ...
        for ref in c.evidence:
            assert res.store.resolves(ref), (c.id, ref)  # ... and each resolves
        d = by_id[c.id]
        issues = [i for i in claim_issues(d, res.store, i18n, lang) if i.check in ("C2", "C3")]
        assert not issues, (c.id, issues)  # BRN-P2: numbers and units match the evidence
        if d.text_source in ("phrased", "translated"):
            got = sorted(str(t.value.normalize()) for t in scan(c.text, units).tokens)
            want = sorted(
                str(t.value.normalize()) for t in scan(d.template_text(lang), units).tokens
            )
            assert got == want, c.id  # a rewrite keeps exactly the template's numbers


def test_replay_passes_the_checks_and_keeps_brn_p1_p2(report: CheckReport) -> None:
    assert len(report.runs) == 4
    phrased = 0
    for run in report.runs:
        b = run.result.briefing
        assert b.critic.passed, (run.scenario, run.lang, b.critic.notes)
        assert not b.critic.removed_claims
        _p1_p2(run.result, run.lang)
        phrased += sum(1 for d in run.result.drafts if d.text_source == "phrased")
    assert phrased > 0, "no recorded phrasing was accepted"


def test_replayed_rewrites_never_touch_forecast_caveats_or_disputed_claims(
    report: CheckReport,
) -> None:
    for run in report.runs:
        for d in run.result.drafts:
            if d.section in ("forecast", "caveats") or d.disputed_by:
                assert d.text_source in ("template", "verbatim", "translated"), d.id


def test_conflicts_scenario_flags_and_reconciles_in_both_languages(report: CheckReport) -> None:
    for run in report.runs:
        if run.scenario != "demo-sindh-2022-conflicts":
            assert run.result.briefing.conflicts == []
            continue
        res = {c.rule_id: c.resolution for c in run.result.briefing.conflicts}
        assert res == {
            "R2_ledger_to_dry_district": "reconciled",
            "R3_library_vs_ledger_need": "flagged",
        }


def test_urdu_briefings_are_urdu_with_the_same_numbers(report: CheckReport) -> None:
    units = UnitTable(load_i18n().unit_aliases())
    by = {(r.scenario, r.lang): r for r in report.runs}
    for sc in ("demo-sindh-2022", "demo-sindh-2022-conflicts"):
        en = {c.id: c for c in all_claims(by[sc, "en"].result.briefing)}
        ur = {c.id: c for c in all_claims(by[sc, "ur"].result.briefing)}
        assert set(ur) - set(en) <= {"caveat.verbatim_foreign"}
        assert set(en) <= set(ur)
        for cid, c in ur.items():
            if cid not in en:
                continue
            d = next(x for x in by[sc, "ur"].result.drafts if x.id == cid)
            if d.verbatim_foreign:
                continue  # shown in English with caveat.verbatim_foreign
            nums_en = sorted(str(t.value.normalize()) for t in scan(en[cid].text, units).tokens)
            nums_ur = sorted(str(t.value.normalize()) for t in scan(c.text, units).tokens)
            assert nums_en == nums_ur, cid
