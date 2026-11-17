"""Brain eval harness (brain task 28): the verifier catches corrupted claims, seeded conflict
results are a function of the seed, and the fast run reports every metric."""

from __future__ import annotations

import asyncio
import copy
from decimal import Decimal
from typing import Any

import pytest

from evals.brain import _briefing, _llm, seeded_conflicts
from evals.brain.verify import extract_numbers, lexical_judge, verify_claim, walk


@pytest.fixture(scope="module")
def demo() -> Any:
    return asyncio.run(_briefing("demo-sindh-2022", "en", llm=_llm()))


def _evidence(run: Any) -> dict[str, Any]:
    return {
        e["call_run_id"]: {"organ": e["organ"], "tool": e["tool"], "result": e["result"]}
        for e in run.store.to_json()["entries"]
    }


def _claims(run: Any) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for s in run.briefing.sections for c in s.claims]


def test_every_demo_claim_passes(demo: Any) -> None:
    ev = _evidence(demo)
    drafts = {d.id: d for d in demo.drafts}
    bad = []
    for c in _claims(demo):
        d = drafts[c["id"]]
        v = verify_claim(
            c,
            ev,
            text_source=d.text_source,
            judge=lexical_judge,
            reference_texts=[d.template_text("en")],
        )
        if not v.passed:
            bad.append((c["id"], v.problems))
    assert bad == []


def test_verifier_catches_a_corrupted_briefing(demo: Any) -> None:
    ev = _evidence(demo)
    claims = {c["id"]: c for c in _claims(demo)}
    wrong_number = copy.deepcopy(claims["allocation.summary"])
    nums = extract_numbers(wrong_number["text"])
    first = f"{nums[0].value:,}"
    wrong_number["text"] = wrong_number["text"].replace(first, "1,234,567", 1)
    assert not verify_claim(wrong_number, ev).numbers_ok
    garbled = copy.deepcopy(claims["allocation.summary"])
    garbled["text"] = garbled["text"].replace(first, first + "7", 1)  # 3,412,6987
    assert not verify_claim(garbled, ev).numbers_ok

    bad_ref = copy.deepcopy(claims["extent.flood_area"])
    bad_ref["evidence"][0]["json_pointer"] = "/data/no_such_field"
    assert not verify_claim(bad_ref, ev).provenance_ok

    no_ref = copy.deepcopy(claims["caveat.disclaimer"])
    no_ref["evidence"] = []
    assert not verify_claim(no_ref, ev).passed

    swapped = copy.deepcopy(claims["extent.flood_area"])
    swapped["text"] = swapped["text"].replace("km2", "m3/s", 1)
    v = verify_claim(swapped, ev)
    assert not v.passed and not v.units_ok

    invented = copy.deepcopy(claims["forecast.peak"])
    invented["text"] += " Expect 999,999 m3/s by tomorrow."
    assert not verify_claim(invented, ev).numbers_ok

    rewrite = copy.deepcopy(claims["caveat.disclaimer"])
    rewrite["text"] = "Evacuate everyone immediately; the dam has burst."
    assert verify_claim(rewrite, ev, text_source="phrased", judge=lexical_judge).entailed is False


def test_number_extraction_and_pointer_walk() -> None:
    assert [n.value for n in extract_numbers("New flood 16,896 km2 on 2022-08-30, p90 12")] == [
        16896,
        12,
    ]
    urdu = "".join(map(chr, (0x6F1, 0x6F2, 0x66B, 0x6F5))) + " km2"  # 12.5 in Urdu digits
    assert extract_numbers(urdu)[0].value == Decimal("12.5")
    assert extract_numbers("Sentinel-1 scene demo-s1-x 7%")[0].percent
    doc = {"a/b": [{"~x": 3}]}
    assert walk(doc, "/a~1b/0/~0x") == 3


def test_seeded_conflicts_are_reproducible_and_complete() -> None:
    a = seeded_conflicts(0)
    assert a == seeded_conflicts(0)
    expected, found, controls, fps, misses = a
    assert expected == found and controls == 9 and fps == 0 and misses == []
    other = seeded_conflicts(1)
    assert other[1] == other[0] and other[3] == 0
