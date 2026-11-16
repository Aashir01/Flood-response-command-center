"""Eyes and Oracle templates, honesty labels (task 12; BRN-P24, BRN-R5, R7.1, R7.3)."""

from __future__ import annotations

import pytest
from brain_testkit import fixture_result, render_world, world_store
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.config import load_i18n
from stitch_brain.core.checks import claim_issues


def _oracle_world(scale: float, widths: list[float], lang: str) -> list[object]:
    fc = fixture_result("oracle", "forecast_river", "indus-kotri-2022-08-25")
    for p, w in zip(fc["data"]["forecast"], widths, strict=False):
        m = max(1.0, p["discharge"]["p50"] * scale)
        p["discharge"] = {"p10": m * (1 - w), "p50": m, "p90": m * (1 + w)}
    fc["data"]["danger_threshold_m3s"] = fc["data"]["danger_threshold_m3s"] * scale
    store = world_store({"oracle.forecast": fc})
    return [store, render_world(store, lang)]


@settings(max_examples=40, deadline=None)
@given(
    st.floats(0.01, 50),
    st.lists(st.floats(0, 0.9), min_size=7, max_size=7),
    st.sampled_from(["en"]),
)
def test_brn_p24_oracle_claims_are_labelled_modeled(
    scale: float, widths: list[float], lang: str
) -> None:
    store, drafts = _oracle_world(scale, widths, lang)
    pack = load_i18n().pack(lang)
    oracle_claims = [
        d
        for d in drafts
        if any(r.organ == "oracle" and r.json_pointer.startswith("/data") for r in d.evidence)
    ]  # type: ignore[attr-defined]
    assert {d.id for d in oracle_claims} >= {"forecast.peak", "forecast.calibration"}
    for d in oracle_claims:
        assert any(m in d.final_text for m in pack.modeled_terms), d.id
        low = d.final_text.lower()
        assert not any(f" {t} " in f" {low} " for t in pack.forbidden_oracle_terms), d.id
        assert claim_issues(d, store, load_i18n(), lang) == [], (d.id, d.final_text)


def test_forbidden_term_in_text_fails_c7() -> None:
    store, drafts = _oracle_world(1.0, [0.1] * 7, "en")
    peak = next(d for d in drafts if d.id == "forecast.peak")  # type: ignore[attr-defined]
    bad = peak.final_text.replace("Modeled river discharge", "Observed gauge discharge")
    kinds = [i.check for i in claim_issues(peak, store, load_i18n(), "en", text=bad)]
    assert "C7" in kinds


def test_unvalidated_and_recorded_caveats_appear() -> None:
    drafts = render_world(world_store())
    ids = {d.id for d in drafts}
    assert "caveat.eyes_unvalidated" in ids and "caveat.oracle_modeled" in ids
    assert {
        "caveat.recorded.eyes",
        "caveat.recorded.oracle",
        "caveat.recorded.library",
        "caveat.recorded.ledger",
    } <= ids
    rec = next(d for d in drafts if d.id == "caveat.recorded.eyes")
    assert any(r.json_pointer.startswith("/warnings/") for r in rec.evidence)


def test_null_threshold_omits_the_exceedance_claim() -> None:
    fc = fixture_result("oracle", "forecast_river", "indus-kotri-2022-08-25")
    fc["data"]["danger_threshold_m3s"] = None
    ids = {d.id for d in render_world(world_store({"oracle.forecast": fc}))}
    assert "forecast.exceedance" not in ids and "forecast.peak" in ids


def test_non_modeled_target_kind_renders_nothing() -> None:
    fc = fixture_result("oracle", "forecast_river", "indus-kotri-2022-08-25")
    fc["data"]["target_kind"] = "gauge"
    ids = {d.id for d in render_world(world_store({"oracle.forecast": fc}))}
    assert not any(i.startswith("forecast.") for i in ids)


@pytest.mark.parametrize("node", ["eyes.segment", "eyes.compare"])
def test_extent_renders_with_one_eyes_tool(node: str) -> None:
    drafts = render_world(world_store({node: None}))
    store = world_store({node: None})
    ext = [d for d in drafts if d.section == "extent"]
    assert ext
    for d in render_world(store):
        if d.section == "extent":
            assert claim_issues(d, store, load_i18n(), "en") == [], d.id
