"""Urdu briefings (task 21; BRN-R7.5, BRN-P14): every template id in both languages, the same
numbers and units in en and ur, offline Urdu with ``fake``, and translation acceptance."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from brain_testkit import all_claims, fixture_result, render_world, run_briefing, world_store
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.config import load_i18n
from stitch_brain.core.numbers import UnitTable, scan
from stitch_brain.core.textfmt import fields
from stitch_brain.runtime.llm_steps import LlmSteps
from stitch_common.llm import FakeLLM, LLMRequest

UNITS = UnitTable(load_i18n().unit_aliases())


def _numbers(text: str) -> Counter[tuple[str, str | None]]:
    return Counter((str(t.value.normalize()), t.unit) for t in scan(text, UNITS).tokens)


def test_every_template_id_has_both_languages_with_the_same_fields() -> None:
    packs = load_i18n().packs
    assert set(packs) == {"en", "ur"}
    en, ur = packs["en"], packs["ur"]
    for group in ("templates", "conflicts", "assumptions"):
        a, b = getattr(en, group), getattr(ur, group)
        assert set(a) == set(b), (group, set(a) ^ set(b))
    for tid, pat in en.templates.items():
        # Urdu may drop an English-only text slot (organ unit strings, labels) but never a number
        assert set(fields(ur.templates[tid])) <= set(fields(pat)), tid
    assert set(en.section_titles) == set(ur.section_titles)
    for name, table in en.tables.items():
        assert set(table) == set(ur.tables[name]), name
    assert set(en.units) == set(ur.units)


def _lang_free(refs: Any) -> list[tuple[str, str]]:
    """Refs with language keys (``/name/en`` vs ``/name/ur``) folded together."""
    out = []
    for r in refs:
        p = r.json_pointer
        out.append((r.run_id, re.sub(r"/(en|ur)(?=/|$)", "/*", p)))
    return out


_SCALE = st.floats(min_value=0.05, max_value=20.0, allow_nan=False)


@settings(deadline=None)
@given(km=_SCALE, qty=_SCALE)
def test_brn_p14_same_numbers_and_units_in_en_and_ur(km: float, qty: float) -> None:
    compare = fixture_result("eyes", "compare_with_permanent_water", "demo-sindh-2022")
    for row in compare["data"]["by_district"]:
        row["flooded_km2"] = round(row["flooded_km2"] * km, 3)
    led = fixture_result("ledger", "optimize_allocation", "demo-sindh-2022-full")
    for row in led["data"]["allocation"]:
        row["quantity"] = float(round(row["quantity"] * qty))
    store = world_store({"eyes.compare": compare, "ledger.optimize": led})
    en = {d.id: d for d in render_world(store, "en")}
    ur = {d.id: d for d in render_world(store, "ur")}
    assert set(en) == set(ur)
    for cid, d in en.items():
        assert _numbers(d.final_text) == _numbers(ur[cid].final_text), (
            cid,
            d.final_text,
            ur[cid].final_text,
        )
        assert _lang_free(d.evidence) == _lang_free(ur[cid].evidence), cid


async def test_urdu_briefing_offline_with_fake_passes_the_critic() -> None:
    res = await run_briefing(lang="ur", llm=FakeLLM())
    b = res.briefing
    assert b.lang == "ur" and b.critic.passed, b.critic.notes
    assert not b.critic.removed_claims
    pack = load_i18n().pack("ur")
    assert {s.title for s in b.sections} == set(pack.section_titles.values())
    ids = {c.id for c in all_claims(b)}
    assert "caveat.verbatim_foreign" in ids  # the English food guidance stays English


def _translator(reply: dict[str, str] | None) -> FakeLLM:
    def respond(req: LLMRequest) -> str:
        payload = json.loads(req.messages[-1].content)
        if req.purpose == "brain.judge":
            return json.dumps({"verdict": "entailed"})
        if req.purpose != "brain.translate":
            return "{}"
        claims: dict[str, str] = payload["claims"]
        if reply is None:
            return json.dumps({"claims": dict.fromkeys(claims, "ترجمہ")})
        return json.dumps({"claims": {k: reply.get(k, v) for k, v in claims.items()}})

    return FakeLLM(mode="adversarial", responder=respond)


GOOD_FOOD = (
    "عام خوراک کے راشن میں فی فرد روزانہ کم از کم 2,100 kcal ہونی چاہیے، "
    "اور منصوبہ بند راشن میں پروٹین اور چکنائی شامل ہو۔"  # noqa: RUF001
)


async def _food_claim(llm: Any) -> Any:
    res = await run_briefing(lang="ur", llm=llm)
    return next(d for d in res.drafts if d.id == "guidance.food.0")


async def test_checked_translation_is_accepted() -> None:
    d = await _food_claim(_translator({"guidance.food.0": GOOD_FOOD}))
    assert d.text_source == "translated" and d.final_text == GOOD_FOOD
    assert not d.verbatim_foreign


async def test_translation_that_changes_a_number_is_rejected() -> None:
    bad = GOOD_FOOD.replace("2,100", "2,500")
    d = await _food_claim(_translator({"guidance.food.0": bad}))
    assert d.text_source == "verbatim" and d.verbatim_foreign


async def test_translation_with_lakh_is_rejected() -> None:
    bad = GOOD_FOOD.replace("2,100", "2 لاکھ")
    d = await _food_claim(_translator({"guidance.food.0": bad}))
    assert d.text_source == "verbatim" and d.verbatim_foreign


async def test_translation_dropping_the_number_is_rejected() -> None:
    d = await _food_claim(_translator(None))
    assert d.text_source == "verbatim" and d.verbatim_foreign


def test_needs_translation_only_for_foreign_verbatim_text() -> None:
    steps = LlmSteps(None, load_i18n())
    store = world_store()
    drafts = render_world(store, "ur")
    need = {d.id for d in drafts if steps.needs_translation(d, "ur")}
    assert "guidance.food.0" in need
    assert all(d.verbatim for d in drafts if d.id in need)
