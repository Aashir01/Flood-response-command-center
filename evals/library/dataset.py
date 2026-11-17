"""The Library question set: loading, the committed split rule and validation (design 10).

Files (all committed):

* ``questions.jsonl``: the 50-question set (30 English, 20 Urdu; 38 answerable, 12 not).
* ``dev_extra.jsonl``: extra calibration-only items (``split = "dev_only"``), never reported.
* ``split.lock``: ``sha256`` of the sorted ``id:split`` lines of ``questions.jsonl``. The split
  is assigned once by ``assign_splits`` and must never change after calibration (LIB-P12).

The split rule: within each stratum ``(lang, answerable)`` questions are ordered by
``sha256(id)``. Answerable strata send the first ``n`` to dev. Unanswerable strata take
questions round-robin over the refusal reasons (sorted by name), each reason in ``sha256``
order, so dev covers every reason where possible. Quotas give dev 20 questions (7 Urdu, 15
answerable, 5 unanswerable) and test the other 30 (13 Urdu, 23 answerable, 7 unanswerable).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.jsonl"
DEV_EXTRA = HERE / "dev_extra.jsonl"
SPLIT_LOCK = HERE / "split.lock"

Reason = Literal["INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "CONFLICTING_EVIDENCE"]
DEV_QUOTA: dict[tuple[str, bool], int] = {
    ("en", True): 10,
    ("en", False): 3,
    ("ur", True): 5,
    ("ur", False): 2,
}
EXPECTED_COUNTS = {
    "total": 50,
    "en": 30,
    "ur": 20,
    "answerable": 38,
    "INSUFFICIENT_EVIDENCE": 6,
    "OUT_OF_SCOPE": 4,
    "CONFLICTING_EVIDENCE": 2,
}
MIN_COMMITTED_SHARE = 0.70  # of answerable questions (design 10.1, LIB-R10.4)
MIN_CROSS_LINGUAL_UR = 6
MIN_DEV_EXTRA = 40


class Gold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_id: str
    page: int = Field(ge=1)
    evidence_quote: str = Field(min_length=1)


class PageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_id: str
    page: int = Field(ge=1)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[qe][0-9]{3}$")
    split: Literal["dev", "test", "dev_only"] | None
    lang: Literal["en", "ur"]
    question: str = Field(min_length=3, max_length=500)
    answerable: bool
    expected_status: Literal["answered", "refused"]
    expected_reason: Reason | None
    category: str
    tier: Literal["committed", "full"]
    gold: list[Gold]
    alt_pages: list[PageRef]
    required_facts: list[str]
    demo: bool = False
    needs_native_review: bool = False
    notes: str = ""

    def pages(self) -> set[tuple[str, int]]:
        """Gold and alternative pages that support an answer."""
        return {(g.doc_id, g.page) for g in self.gold} | {
            (p.doc_id, p.page) for p in self.alt_pages
        }


def load(path: Path = QUESTIONS) -> list[Question]:
    out: list[Question] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                out.append(Question.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path.name}:{n}: {exc}") from exc
    return out


def _h(qid: str) -> str:
    return hashlib.sha256(qid.encode("utf-8")).hexdigest()


def assign_splits(questions: Sequence[Question]) -> dict[str, str]:
    """The committed split rule (module docstring). Returns ``{id: "dev" | "test"}``."""
    out = {q.id: "test" for q in questions}
    for (lang, answerable), quota in DEV_QUOTA.items():
        stratum = sorted(
            (q for q in questions if q.lang == lang and q.answerable == answerable),
            key=lambda q: _h(q.id),
        )
        if answerable:
            chosen = stratum[:quota]
        else:
            by_reason: dict[str, list[Question]] = {}
            for q in stratum:
                by_reason.setdefault(str(q.expected_reason), []).append(q)
            queues = [by_reason[r] for r in sorted(by_reason)]
            chosen = []
            while len(chosen) < quota and any(queues):
                for queue in queues:
                    if queue and len(chosen) < quota:
                        chosen.append(queue.pop(0))
        for q in chosen:
            out[q.id] = "dev"
    return out


def split_hash(pairs: Iterable[tuple[str, str]]) -> str:
    lines = "\n".join(sorted(f"{i}:{s}" for i, s in pairs))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def ids_hash(ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


PageText = Callable[[str, int], str | None]


def validate(
    questions: Sequence[Question],
    extra: Sequence[Question],
    *,
    manifest: dict[str, str],
    page_text: PageText,
    lock: str | None,
    normalize: Callable[[str], str] = lambda s: s,
) -> list[str]:
    """Return a list of problems (empty when the set is valid).

    ``manifest`` maps ``doc_id`` to its tier (``committed`` or ``fetch``). ``page_text`` returns
    the stored text of a page, or None when the page is unknown or not available locally
    (fetch-tier documents that were never fetched are skipped, not failed).
    """
    errors: list[str] = []
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        errors.append("duplicate question ids")
    extra_ids = [q.id for q in extra]
    if len(set(extra_ids)) != len(extra_ids):
        errors.append("duplicate dev_extra ids")
    if set(ids) & set(extra_ids):
        errors.append("dev_extra ids overlap questions.jsonl")
    counts: dict[str, int] = {
        "total": len(questions),
        "en": sum(q.lang == "en" for q in questions),
        "ur": sum(q.lang == "ur" for q in questions),
        "answerable": sum(q.answerable for q in questions),
    }
    for r in ("INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "CONFLICTING_EVIDENCE"):
        counts[r] = sum(q.expected_reason == r for q in questions)
    for k, want in EXPECTED_COUNTS.items():
        if counts[k] != want:
            errors.append(f"count {k} = {counts[k]}, expected {want}")
    if len(questions) - counts["answerable"] < 10:
        errors.append("fewer than 10 unanswerable questions (LIB-R9.1)")
    answerable = [q for q in questions if q.answerable]
    committed = [q for q in answerable if q.tier == "committed"]
    if answerable and len(committed) / len(answerable) < MIN_COMMITTED_SHARE:
        errors.append(
            f"only {len(committed)}/{len(answerable)} answerable questions are committed-tier"
        )
    cross = [
        q
        for q in questions
        if q.lang == "ur"
        and q.answerable
        and q.gold
        and all(not g.doc_id.startswith("stitch-ur-") for g in q.gold)
    ]
    if len(cross) < MIN_CROSS_LINGUAL_UR:
        errors.append(f"only {len(cross)} cross-lingual Urdu questions (need 6)")
    if len(extra) < MIN_DEV_EXTRA:
        errors.append(f"dev_extra has {len(extra)} items (need {MIN_DEV_EXTRA})")
    for q in extra:
        if q.split != "dev_only":
            errors.append(f"{q.id}: dev_extra items must have split dev_only")
    for q in [*questions, *extra]:
        errors += _check_question(q, manifest, page_text, normalize)
    rule = assign_splits(questions)
    for q in questions:
        if q.split != rule[q.id]:
            errors.append(f"{q.id}: split {q.split} differs from the split rule ({rule[q.id]})")
    current = split_hash((q.id, str(q.split)) for q in questions)
    if lock is None:
        errors.append("split.lock is missing")
    elif lock != current:
        errors.append("split differs from the committed split.lock (LIB-P12)")
    return errors


def _check_question(
    q: Question, manifest: dict[str, str], page_text: PageText, normalize: Callable[[str], str]
) -> list[str]:
    errors: list[str] = []
    if q.answerable != (q.expected_status == "answered"):
        errors.append(f"{q.id}: answerable and expected_status disagree")
    if q.answerable and q.expected_reason is not None:
        errors.append(f"{q.id}: answerable question with a refusal reason")
    if not q.answerable and q.expected_reason is None:
        errors.append(f"{q.id}: unanswerable question without a reason")
    if q.answerable and not q.gold:
        errors.append(f"{q.id}: answerable question without gold evidence")
    if q.expected_reason == "CONFLICTING_EVIDENCE" and len({g.doc_id for g in q.gold}) < 2:
        errors.append(f"{q.id}: a conflict question needs gold passages from two documents")
    if q.expected_reason in ("INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE") and q.gold:
        errors.append(f"{q.id}: {q.expected_reason} question with gold evidence")
    for ref in [*q.gold, *q.alt_pages]:
        if ref.doc_id not in manifest:
            errors.append(f"{q.id}: unknown document {ref.doc_id}")
    gold_tiers = {manifest.get(g.doc_id) for g in q.gold}
    want_tier = "committed" if gold_tiers <= {"committed"} else "full"
    if q.tier != want_tier:
        errors.append(f"{q.id}: tier {q.tier}, but its gold documents make it {want_tier}")
    if q.demo and q.tier != "committed":
        errors.append(f"{q.id}: demo questions must be answerable or refusable on committed data")
    for g in q.gold:
        text = page_text(g.doc_id, g.page)
        if text is None:
            if manifest.get(g.doc_id) == "committed":
                errors.append(f"{q.id}: page {g.doc_id} p{g.page} not in the pack")
            continue
        if normalize(g.evidence_quote) not in text:
            errors.append(f"{q.id}: evidence_quote is not verbatim on {g.doc_id} p{g.page}")
    for p in q.alt_pages:
        if manifest.get(p.doc_id) == "committed" and page_text(p.doc_id, p.page) is None:
            errors.append(f"{q.id}: alt page {p.doc_id} p{p.page} not in the pack")
    return errors


def write_splits(path: Path, splits: dict[str, str]) -> None:
    """Rewrite ``split`` in place, keeping every other byte of each line's JSON order."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj: dict[str, Any] = json.loads(line)
        obj["split"] = splits[obj["id"]]
        lines.append(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
