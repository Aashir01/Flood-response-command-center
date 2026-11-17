"""Voice eval: WER function, normalization, seeded sentence choice, and ``not_run`` without a key
(no network; the live round trip itself runs only through ``python -m evals.run``)."""

from __future__ import annotations

import pytest

from evals import voice as ev
from evals.models import OrganResult


def test_wer_identical_is_zero_and_full_substitution_is_one() -> None:
    assert ev.wer(["the river is rising"], ["The river, is rising."]) == 0.0
    assert ev.wer(["a b c"], ["x y z"]) == 1.0


def test_wer_counts_insertions_and_deletions() -> None:
    assert ev.wer(["a b c d"], ["a b x c d"]) == pytest.approx(0.25)
    assert ev.wer(["a b c d"], ["a d"]) == pytest.approx(0.5)
    assert ev.wer([""], [""]) == 0.0


def test_urdu_normalization() -> None:
    # Arabic yeh and kaf map to Urdu forms; diacritics and Urdu punctuation are removed.
    arabic = "\u0643\u064a\u0627\u064e \u06d4"
    urdu = "\u06a9\u06cc\u0627"
    assert ev.wer_normalize(arabic) == [urdu]
    assert ev.wer_normalize("\u06f4\u06f5 \u061f") == ["45"]


def test_sentence_choice_is_seeded() -> None:
    text = ev.SCRIPT_EN.read_text(encoding="utf-8")
    a = ev.pick_sentences(text, 3, seed=0)
    assert a == ev.pick_sentences(text, 3, seed=0)
    assert len(a) == 3 and all(len(s.split()) >= 4 for s in a)


def test_not_run_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    out = ev.run(fast=True, seed=0)
    assert isinstance(out, OrganResult) and out.status == "not_run" and not out.metrics
