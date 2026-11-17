"""Confidence (task 18): design 11 worked examples A, B, C and BRN-P16."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.config import load_confidence
from stitch_brain.core.confidence import ORGANS, ConfidenceParams, confidence

P = load_confidence()
A = {"eyes": 0.82 * 0.7, "oracle": 0.65, "library": 1.0, "ledger": 1.0}


def test_weights_load_and_sum_to_one() -> None:
    assert abs(sum(P.weights.values()) - 1.0) < 1e-12
    assert set(P.weights) == set(ORGANS)


def test_weights_that_do_not_sum_to_one_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ConfidenceParams(weights={"eyes": 0.5, "oracle": 0.5, "library": 0.5, "ledger": 0.5})


def test_example_a_all_organs_no_conflict() -> None:
    assert confidence(A, [], True, 0, P) == 0.78


def test_example_b_oracle_down() -> None:
    assert confidence({**A, "oracle": 0.0}, [], True, 0, P) == 0.62


def test_example_c_reconciled_and_flagged() -> None:
    assert confidence(A, ["reconciled", "flagged"], True, 0, P) == 0.63


unit = st.floats(0, 1, allow_nan=False)
organ_conf = st.fixed_dictionaries({o: unit for o in ORGANS})
resolutions = st.lists(st.sampled_from(["flagged", "reconciled", "escalated"]), max_size=4)


@settings(deadline=None)
@given(organ_conf, resolutions, st.booleans(), st.integers(0, 10))
def test_brn_p16_bounded(c: dict[str, float], res: list[str], passed: bool, removed: int) -> None:
    assert 0.0 <= confidence(c, res, passed, removed, P) <= 1.0


@settings(deadline=None)
@given(organ_conf, resolutions, st.booleans(), st.integers(0, 10), st.sampled_from(ORGANS), unit)
def test_brn_p16_monotone(
    c: dict[str, float], res: list[str], passed: bool, removed: int, organ: str, more: float
) -> None:
    base = confidence(c, res, passed, removed, P)
    up = {**c, organ: max(c[organ], more)}
    assert confidence(up, res, passed, removed, P) >= base
    assert confidence({**c, organ: 0.0}, res, passed, removed, P) <= base
    assert confidence(c, [*res, "flagged"], passed, removed, P) <= base
    assert confidence(c, [*res, "reconciled"], passed, removed, P) <= base
    assert confidence(c, res, passed, removed + 1, P) <= base
    assert confidence(c, res, False, removed, P) <= base
