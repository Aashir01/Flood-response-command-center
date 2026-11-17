"""LIB-P6: no committed file or derived artifact belongs to a document with
``redistributable = false`` (``scripts/check_corpus_licenses.py``, design 3.3 rules 1 to 5).

The Hypothesis test builds random manifests and tracked-file sets and compares the checker's
error verdict with an oracle written independently from the rules."""

from __future__ import annotations

from typing import Any

import check_corpus_licenses as clc
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

LIB = clc.LIB
SHA = "a" * 64


def _entry(i: int, **kw: Any) -> dict[str, Any]:
    tier = kw.pop("tier", "committed")
    e: dict[str, Any] = {
        "doc_id": f"doc-{i:02d}",
        "title": f"Doc {i}",
        "publisher": "FEMA",
        "doc_type": "guideline",
        "lang": "en",
        "source_url": "https://example.gov/x",
        "retrieved_on": None,
        "as_of": None,
        "sha256": SHA,
        "license": "US-Gov-PD",
        "license_url": None,
        "license_evidence": "17 U.S.C. 105",
        "redistributable": True,
        "owner_confirmed": True,
        "tier": tier,
        "path": f"corpus/doc-{i:02d}.txt" if tier == "committed" else None,
        "format": "text",
    }
    e.update(kw)
    return e


@st.composite
def worlds(draw: st.DrawFn) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    n = draw(st.integers(0, 5))
    entries = []
    for i in range(n):
        e = _entry(
            i,
            tier=draw(st.sampled_from(["committed", "fetch"])),
            redistributable=draw(st.booleans()),
            owner_confirmed=draw(st.booleans()),
            license_evidence=draw(st.sampled_from(["", "  ", "evidence"])),
        )
        if draw(st.integers(0, 6)) == 0:
            del e[draw(st.sampled_from(["license", "source_url", "redistributable", "title"]))]
        entries.append(e)
    names = [f"doc-{i:02d}" for i in range(7)]
    tracked = draw(
        st.lists(
            st.sampled_from([f"{LIB}/corpus/{d}.txt" for d in names] + ["data/raw/library/x.pdf"]),
            unique=True,
            max_size=6,
        )
    )
    pack = draw(st.lists(st.sampled_from(names), unique=True, max_size=4))
    return entries, tracked, pack


REQUIRED = ("license", "source_url", "redistributable", "title")


def oracle(entries: list[dict[str, Any]], tracked: list[str], pack: list[str]) -> bool:
    """True when the world has at least one error under rules 1, 2, 3 and 5."""
    bad = False
    ok_entries = []
    for e in entries:
        if any(k not in e for k in REQUIRED):
            bad = True  # rule 1
        else:
            ok_entries.append(e)
    allowed = set()
    for e in ok_entries:
        if e["tier"] != "committed":
            continue
        if not e["redistributable"] or not e["license_evidence"].strip():
            bad = True  # rule 2
        if e["redistributable"]:
            allowed.add(e["doc_id"])
    for f in tracked:
        if f.startswith("data/raw/"):
            bad = True  # rule 5
        elif f.startswith(f"{LIB}/corpus/"):
            doc = f.rsplit("/", 1)[-1].removesuffix(".txt")
            if doc not in allowed:
                bad = True  # rule 3
    if any(d not in allowed for d in pack):
        bad = True  # rule 3, derived artifacts
    return bad


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(worlds())
def test_p6_checker_verdict_matches_the_oracle(
    world: tuple[list[dict[str, Any]], list[str], list[str]],
) -> None:
    entries, tracked, pack = world
    problems = clc.check(entries, tracked, pack)
    errors = [p for p in problems if not p.warning]
    assert bool(errors) == oracle(entries, tracked, pack), problems
    # A non-redistributable document can never be committed or shipped in the pack silently.
    for e in entries:
        if not e.get("redistributable", True) and (
            f"{LIB}/corpus/{e['doc_id']}.txt" in tracked or e["doc_id"] in pack
        ):
            assert errors


def test_rule_2_owner_confirmation_is_a_warning_unless_required() -> None:
    e = [_entry(0, owner_confirmed=False)]
    assert all(p.warning for p in clc.check(e, [], []))
    assert any(not p.warning and p.rule == 2 for p in clc.check(e, [], [], require_owner=True))


@pytest.mark.parametrize(
    ("entries", "tracked", "pack", "rule"),
    [
        ([{"doc_id": "doc-00"}], [], [], 1),
        ([_entry(0, redistributable=False)], [], [], 2),
        ([_entry(0, license_evidence="")], [], [], 2),
        ([_entry(0, tier="fetch")], [f"{LIB}/corpus/doc-00.txt"], [], 3),
        ([_entry(0, tier="fetch")], [], ["doc-00"], 3),
        ([_entry(0)], ["data/raw/library/doc-00.pdf"], [], 5),
    ],
)
def test_each_failure_rule(
    entries: list[dict[str, Any]], tracked: list[str], pack: list[str], rule: int
) -> None:
    errors = [p for p in clc.check(entries, tracked, pack) if not p.warning]
    assert any(p.rule == rule for p in errors), errors


def test_rule_4_hash_mismatch_and_missing_file() -> None:
    e = [_entry(0)]
    path = f"{LIB}/corpus/doc-00.txt"
    assert any(p.rule == 4 for p in clc.check(e, [path], [], {path: "b" * 64}))
    assert any(p.rule == 4 for p in clc.check(e, [path], [], {}))
    assert not clc.check(e, [path], ["doc-00"], {path: SHA})


def test_the_real_repository_passes() -> None:
    assert clc.main([]) == 0
