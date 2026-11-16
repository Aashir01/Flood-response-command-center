"""Ledger sensitivity and equity claims (task 14; BRN-R5, R7.1)."""

from __future__ import annotations

from brain_testkit import fixture_result, render_world, world_store

from stitch_brain.config import load_i18n
from stitch_brain.core.checks import claim_issues


def test_shadow_claims_only_for_binding_supply_constraints() -> None:
    sens = fixture_result("ledger", "sensitivity_report", "demo-sindh-2022-full")
    for p in sens["data"]["shadow_prices"]:
        if p["constraint"] == "supply:water":
            p["binding"] = False
    store = world_store({"ledger.sensitivity": sens})
    ids = {d.id for d in render_world(store)}
    assert "allocation.shadow.water" not in ids
    assert {"allocation.shadow.food", "allocation.shadow.shelter"} <= ids


def test_null_equity_cost_is_omitted() -> None:
    sens = fixture_result("ledger", "sensitivity_report", "demo-sindh-2022-full")
    sens["data"]["equity_cost"] = None
    store = world_store({"ledger.sensitivity": sens})
    eq = next(d for d in render_world(store) if d.id == "allocation.equity")
    assert eq.template_id == "allocation.equity_nocost" and "given up" not in eq.final_text
    assert claim_issues(eq, store, load_i18n(), "en") == []


def test_sensitivity_missing_keeps_equity_without_cost_and_no_shadow() -> None:
    store = world_store({"ledger.sensitivity": None})
    drafts = render_world(store)
    ids = {d.id for d in drafts}
    assert "allocation.equity" in ids and not any(i.startswith("allocation.shadow") for i in ids)


def test_equity_and_shadow_claims_cite_sensitivity() -> None:
    store = world_store()
    for d in render_world(store):
        if d.id.startswith("allocation.shadow") or d.id == "allocation.equity":
            assert any(r.tool == "sensitivity_report" for r in d.evidence), d.id
            assert claim_issues(d, store, load_i18n(), "en") == [], d.id
