"""Library guidance claims and refusals (task 11; BRN-R5.1, R7.4, BRN-P1 extended)."""

from __future__ import annotations

from brain_testkit import fixture_result, render_world, world_store

from stitch_brain.config import load_i18n
from stitch_brain.core.checks import claim_issues


def test_every_guidance_claim_has_a_resolving_citation() -> None:
    store = world_store()
    drafts = [d for d in render_world(store) if d.section == "guidance"]
    answered = [d for d in drafts if d.template_id == "guidance.claim"]
    assert {d.id for d in answered} == {"guidance.water.0", "guidance.food.0"}
    for d in answered:
        cites = [r for r in d.evidence if r.json_pointer.startswith("/data/citations/")]
        assert cites and all(store.resolves(r) for r in cites)
        assert d.verbatim and d.final_text == store.value(d.slots["text"].refs[0])
        assert claim_issues(d, store, load_i18n(), "en") == []


def test_bad_citation_idx_is_dropped_and_reported() -> None:
    from stitch_brain.config import load_scenarios
    from stitch_brain.core.templates.common import RenderCtx
    from stitch_brain.core.templates.guidance import render_guidance

    bad = fixture_result("library", "answer_with_citations", "water-en")
    bad["data"]["claims"].append({"text": "Unsupported sentence.", "citation_idx": [7]})
    bad["data"]["claims"].append({"text": "Uncited sentence.", "citation_idx": []})
    store = world_store({"library.water": bad})
    ctx = RenderCtx(store=store, scenario=load_scenarios()["demo-sindh-2022"], i18n=load_i18n())
    ids = [d.id for d in render_guidance(ctx)]
    assert "guidance.water.0" in ids and "guidance.water.1" not in ids
    assert "guidance.water.2" not in ids
    assert any("guidance.water.1" in i for i in ctx.issues)
    assert any("guidance.water.2" in i for i in ctx.issues)


def test_refusal_is_rendered_and_never_filled_in() -> None:
    store = world_store()
    drafts = [d for d in render_world(store) if d.id.startswith("guidance.shelter")]
    assert [d.id for d in drafts] == ["guidance.shelter.refusal"]
    text = drafts[0].final_text
    assert "declined to answer" in text and "No guidance is given from memory" in text
    assert "no sufficiently supported passage was found" in text
    assert any("/closest_hits/" in r.json_pointer for r in drafts[0].evidence)
    assert claim_issues(drafts[0], store, load_i18n(), "en") == []


def test_library_down_gives_no_guidance_claims() -> None:
    store = world_store({"library.water": None, "library.food": None, "library.shelter": None})
    assert not [d for d in render_world(store) if d.section == "guidance"]
