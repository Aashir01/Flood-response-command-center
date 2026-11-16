"""Numbers, quantities, the conflict detector, refusal gates and the quantity rule."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from stitch_library.core.conflict import SentenceRef, detect_conflict
from stitch_library.core.decide import Signals, Thresholds, decide
from stitch_library.core.fusion import rrf
from stitch_library.core.quantities import extract_quantities, numbers_in
from stitch_library.core.scope import (
    asked_per,
    is_quantity_query,
    quantity_supported,
    scope_score,
)


def test_numbers_digits_words_fractions() -> None:
    assert numbers_in("Add 1/8 teaspoon to 5,000 litres, 1.50 kg") == {
        Decimal("0.125"),
        Decimal(5000),
        Decimal("1.5"),
    }
    assert numbers_in("one gallon and three quarters of a gallon") == {Decimal(1), Decimal("0.75")}
    assert numbers_in("Twenty-five pounds") == {Decimal(25)}
    assert numbers_in("۱۵ لیٹر اور ایک گیلن") == {Decimal(15), Decimal(1)}
    assert numbers_in("6.0 percent") == {Decimal(6)}


def test_quantities_units_and_per() -> None:
    q = extract_quantities("Store at least one gallon of water per person per day.")
    assert [(x.value, x.unit, x.per) for x in q] == [(1.0, "gal_us", "person_day")]
    q = extract_quantities("Total 7.5 to 15 lpd")
    assert (q[-1].value, q[-1].unit, q[-1].per) == (15.0, "L", "person_day")
    q = extract_quantities("15 litres/person/day")
    assert q[0].per == "person_day"
    q = extract_quantities("فی کس روزانہ ۱۵ لیٹر پانی")
    assert q[0].unit == "L" and q[0].value == 15.0
    assert extract_quantities("wait two hours")[0].unit == "hour"


def _ref(doc: str, text: str) -> SentenceRef:
    return SentenceRef(doc, f"c_{doc}", 1, 0, len(text), text)


def test_conflict_litres_vs_gallons() -> None:
    q = "How much drinking water per person per day?"
    a = _ref("fema", "Store one gallon of drinking water per person per day.")
    b = _ref("who", "Provide 15 litres of drinking water per person per day.")
    c = detect_conflict(q, [a, b])
    assert c is not None and {c.a.doc_id, c.b.doc_id} == {"fema", "who"}


def test_no_conflict_same_doc_equal_values_or_other_dimension() -> None:
    q = "How much drinking water per person per day?"
    a = _ref("fema", "Store one gallon of drinking water per person per day.")
    same_doc = _ref("fema", "Keep 15 litres of drinking water per person per day.")
    equal = _ref("ur", "Store 3.8 litres of drinking water per person per day.")
    other_dim = _ref("who", "Boil drinking water for one minute per person per day.")
    assert detect_conflict(q, [a, same_doc]) is None
    assert detect_conflict(q, [a, equal]) is None
    assert detect_conflict(q, [a, other_dim]) is None


def test_decide_gates_in_order() -> None:
    th = Thresholds(tau_scope=0.5, tau_evid=1.0)
    assert decide(Signals(0.1, 5.0), th).reason == "OUT_OF_SCOPE"
    assert decide(Signals(0.9, None), th).reason == "INSUFFICIENT_EVIDENCE"
    assert decide(Signals(0.9, 0.5), th).reason == "INSUFFICIENT_EVIDENCE"
    v = decide(Signals(0.9, 2.0, quantity_query=True, quantity_supported=False), th)
    assert v.reason == "INSUFFICIENT_EVIDENCE" and v.gate == "quantity"
    assert decide(Signals(0.9, 2.0, conflict=True), th).reason == "CONFLICTING_EVIDENCE"
    assert decide(Signals(0.9, 2.0), th).proceed


def test_quantity_rule_english_and_urdu() -> None:
    assert is_quantity_query("How much water per person per day?")
    assert is_quantity_query("فی کس روزانہ کتنا پانی؟")
    assert not is_quantity_query("What should people bring to a shelter?")
    assert asked_per("How much water per person per day?") == {"person", "day"}
    water = ["Store at least one gallon of water per person per day for several days."]
    food = ["Throw away any food that has been at room temperature for two hours or more."]
    assert quantity_supported("How much water per person per day?", water)
    assert quantity_supported("فی کس روزانہ کتنا پانی فراہم کیا جائے؟", water)
    assert not quantity_supported("What food ration should be given per person per day?", food)
    assert not quantity_supported("What food ration per person per day?", water)
    assert quantity_supported("How long should water be boiled?", ["Boil water for one minute."])


def test_scope_score_is_max_cosine() -> None:
    anchors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert scope_score(np.array([1.0, 0.0], dtype=np.float32), anchors) == 1.0
    assert scope_score(np.array([1.0, 0.0], dtype=np.float32), np.zeros((0, 0), np.float32)) == 1.0


def test_rrf_hand_built() -> None:
    fused = dict(rrf([[("a", 3.0), ("b", 2.0)], [("b", 0.9), ("c", 0.5)]], k=60))
    assert fused["b"] == 1 / 62 + 1 / 61
    assert fused["a"] == 1 / 61 and fused["c"] == 1 / 62
    assert next(x for x, _ in rrf([[("a", 3.0), ("b", 2.0)], [("b", 0.9), ("c", 0.5)]])) == "b"
