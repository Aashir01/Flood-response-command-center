"""Allocation and caveat templates from the captured Ledger fixture (task 9; BRN-R5.1, R5.2,
R7.1, R7.3, BRN-P9)."""

from __future__ import annotations

import re

import pytest
from brain_testkit import run_briefing

from stitch_brain.config import load_i18n
from stitch_brain.core.checks import claim_issues
from stitch_brain.core.derive import slot_matches
from stitch_brain.core.numbers import EN_NUMBER_WORDS, UR_NUMBER_WORDS, UnitTable, scan
from stitch_brain.core.textfmt import fields, literal_text


async def test_allocation_section_renders_and_every_claim_checks() -> None:
    res = await run_briefing()
    drafts = [d for d in res.drafts if d.section in ("allocation", "caveats")]
    ids = {d.id for d in drafts}
    assert {
        "allocation.summary",
        "allocation.equity",
        "caveat.disclaimer",
        "caveat.mode",
        "caveat.assumptions",
    } <= ids
    assert any(i.startswith("allocation.water.") for i in ids)
    assert any(i.startswith("allocation.shadow.") for i in ids)
    for d in drafts:
        assert d.evidence
        for s in d.slots.values():
            assert s.refs and all(res.store.resolves(r) for r in s.refs)
            assert slot_matches(s, res.store), (d.id, s.name)
        assert claim_issues(d, res.store, load_i18n(), "en") == [], (d.id, d.final_text)


async def test_brn_p9_claim_ids_unique_and_deterministic() -> None:
    a = await run_briefing(briefing_id="00000000-0000-4000-8000-00000000000a")
    b = await run_briefing(briefing_id="00000000-0000-4000-8000-00000000000b")
    ids_a = [d.id for d in a.drafts]
    assert len(ids_a) == len(set(ids_a))
    assert ids_a == [d.id for d in b.drafts]


@pytest.mark.parametrize("lang", ["en", "ur"])
def test_patterns_contain_no_digits_or_number_words(lang: str) -> None:
    pack = load_i18n().packs.get(lang)
    if pack is None:
        pytest.skip(f"{lang} pack not present yet")
    words = set(EN_NUMBER_WORDS) | set(UR_NUMBER_WORDS)
    units = UnitTable(load_i18n().unit_aliases())
    texts = {**pack.templates, **pack.conflicts, **pack.assumptions}
    for tid, pattern in texts.items():
        fields(pattern)
        lit = literal_text(pattern)
        s = scan(lit, units)
        assert s.tokens == [], (tid, [t.text for t in s.tokens])
        assert not [m for m in s.masks if m.kind in ("ident", "date")], tid
        # digits only inside unit aliases (km2, m3/s) and quantile labels (p10)
        masked = "".join(
            " " if any(m.start <= i < m.end for m in s.masks) else ch
            for i, ch in enumerate(s.normalized)
        )
        assert not re.search(r"[0-9]", masked), tid
        tokens = set(re.findall(r"\w+", lit.lower()))
        assert not tokens & words, (tid, tokens & words)
