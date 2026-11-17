"""ORA-P8 / ORA-R8.2 wording lint: Oracle sources, tool descriptions, templates, docs and evals
never call the target gauge data, observations or measurements.

A line that uses one of the words passes only when it (or the line before it, for wrapped
sentences) negates it ("never a gauge record", "not an observation") or uses the allowlisted
stretch label "observed gauge validation (small n)" / the ``observed_validation`` report key."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stitch_oracle.core.explain import LABELS
from stitch_oracle.server import DESCRIPTIONS

REPO = Path(__file__).resolve().parents[4]
ORGAN = REPO / "organs" / "oracle"
FORBIDDEN = re.compile(
    r"\b(gauges?|gauged|observed|observations?|measured|measurements?)\b", re.IGNORECASE
)
NEGATION = re.compile(r"\b(never|not|no|nothing|without|isn't|is not)\b", re.IGNORECASE)
ALLOW = ("observed gauge validation (small n)", "observed_validation")


def _files() -> list[Path]:
    globs = [
        (ORGAN / "src", "**/*.py"),
        (ORGAN / "training", "*.py"),
        (ORGAN / "training", "*.md"),
        (ORGAN / "training", "*.yaml"),
        (ORGAN / "models", "*.md"),
        (ORGAN, "README.md"),
        (REPO / "evals" / "oracle", "*.py"),
        (REPO / "data" / "demo" / "oracle", "*.md"),
        (REPO / "docs", "oracle-model.md"),
    ]
    out = [p for base, pat in globs for p in sorted(base.glob(pat))]
    assert len(out) > 20
    return out


def violations(text: str) -> list[str]:
    bad = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not FORBIDDEN.search(line):
            continue
        context = (lines[i - 1] if i else "") + " " + line
        low = context.lower()
        if any(a in low for a in ALLOW) or NEGATION.search(context):
            continue
        bad.append(line.strip())
    return bad


def test_lint_rule_itself() -> None:
    assert violations("the gauge reading at Sukkur") == ["the gauge reading at Sukkur"]
    assert violations("observed discharge") == ["observed discharge"]
    assert violations("modeled discharge, never a gauge record") == []
    assert violations("observed gauge validation (small n)") == []


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_gauge_or_observation_wording(path: Path) -> None:
    assert violations(path.read_text(encoding="utf-8")) == []


def test_tool_descriptions_and_feature_labels() -> None:
    for text in DESCRIPTIONS.values():
        assert not FORBIDDEN.search(text)
        assert "modeled" in text.lower()
    for label in LABELS.values():
        assert not FORBIDDEN.search(label)
