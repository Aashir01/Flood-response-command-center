"""Run the Library question set and compute the metrics of design 10.4 (LIB-R9.2, LIB-R10.4).

Every question is asked through ``LibraryService.answer`` (``lang = auto``, the ``/ask`` path)
and ``LibraryService.search`` (``top_k = 8``) on a fresh in-memory service. Expected outcomes
depend on the corpus: on the committed corpus a ``tier = full`` question has no supporting
document, so a refusal is correct and an answer is a false answer unless every citation points
at a gold or alt page (``answered_from_alt``).

Pure metric functions (``metrics_for``, ``bootstrap_ci``) take plain result records so they are
unit-tested on hand-built sets.
"""

from __future__ import annotations

import random
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from evals.library.dataset import Question

TOP_K = 8
KS = (1, 3, 5, 8)


@dataclass
class Result:
    qid: str
    lang: str
    split: str
    expected_status: str  # for this corpus
    expected_reason: str | None
    status: str
    reason: str | None
    answer: str | None
    cited_pages: list[tuple[str, int]]
    citations_valid: list[bool]  # answer citations and closest hits
    invariant_ok: bool  # LIB-P1
    gold_pages: set[tuple[str, int]]
    required_facts: list[str]
    hit_pages: list[tuple[str, int]]  # search_guidance order
    generation: str  # "llm" | "extractive" | "none"
    search_s: float
    answer_s: float
    warnings: list[str] = field(default_factory=list)

    @property
    def answered(self) -> bool:
        return self.status == "answered"

    @property
    def from_alt(self) -> bool:
        return (
            self.answered
            and self.expected_status == "refused"
            and bool(self.cited_pages)
            and all(p in self.gold_pages for p in self.cited_pages)
        )


def expected_for(q: Question, corpus: str) -> tuple[str, str | None]:
    if corpus == "committed" and q.tier == "full":
        return "refused", "INSUFFICIENT_EVIDENCE"
    return q.expected_status, q.expected_reason


def run_question(service: Any, q: Question, corpus: str) -> Result:
    from stitch_common.organs.library import AnswerWithCitationsIn, SearchGuidanceIn
    from stitch_library.core.citations import is_verbatim

    t0 = time.perf_counter()
    found = service.search(SearchGuidanceIn(query=q.question, top_k=TOP_K))
    t1 = time.perf_counter()
    out = service.answer(AnswerWithCitationsIn(query=q.question))
    t2 = time.perf_counter()
    data = out.data
    cites = list(data.citations)
    closest = list(data.refusal.closest_hits) if data.refusal else []
    valid = [is_verbatim(service.store.get_page(c.doc_id, c.page), c) for c in [*cites, *closest]]
    invariant = (
        data.status == "answered"
        and bool(cites)
        and bool(data.claims)
        and all(
            c.citation_idx and all(0 <= i < len(cites) for i in c.citation_idx) for c in data.claims
        )
    ) or (data.status == "refused" and data.refusal is not None and not cites)
    exp_status, exp_reason = expected_for(q, corpus)
    gen = data.generation.mode if data.generation else "none"
    return Result(
        qid=q.id,
        lang=q.lang,
        split=str(q.split),
        expected_status=exp_status,
        expected_reason=exp_reason,
        status=data.status,
        reason=data.refusal.reason if data.refusal else None,
        answer=data.answer,
        cited_pages=[(c.doc_id, c.page) for c in cites],
        citations_valid=valid,
        invariant_ok=invariant,
        gold_pages=q.pages(),
        required_facts=list(q.required_facts),
        hit_pages=[(h.doc_id, h.page) for h in found.data.hits],
        generation=gen,
        search_s=t1 - t0,
        answer_s=t2 - t1,
        warnings=list(out.warnings),
    )


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def _first_rank(r: Result) -> int | None:
    return next((i for i, p in enumerate(r.hit_pages, start=1) if p in r.gold_pages), None)


def _facts_found(r: Result) -> tuple[int, int]:
    from stitch_library.core.normalize import search_text

    if not r.required_facts:
        return 0, 0
    ans = search_text(r.answer or "")
    return sum(search_text(f) in ans for f in r.required_facts), len(r.required_facts)


def metrics_for(results: Sequence[Result]) -> dict[str, float | None]:
    """Metrics of one result set. ``None`` when a metric has no denominator."""
    pos = [r for r in results if r.expected_status == "answered"]
    neg = [r for r in results if r.expected_status == "refused"]
    answered_pos = [r for r in pos if r.answered]
    cited = [p for r in answered_pos for p in r.cited_pages]
    accurate = sum(1 for r in answered_pos for p in r.cited_pages if p in r.gold_pages)
    valid = [v for r in results for v in r.citations_valid]
    false_answers = [r for r in neg if r.answered and not r.from_alt]
    refused_neg = [r for r in neg if not r.answered]
    facts = [_facts_found(r) for r in answered_pos]
    out: dict[str, float | None] = {
        "n": float(len(results)),
        "citation_accuracy": _rate(accurate, len(cited)),
        "citation_validity": _rate(sum(valid), len(valid)),
        "answer_rate": _rate(len(answered_pos), len(pos)),
        "answer_correct_rate": _rate(
            sum(1 for r in answered_pos if any(p in r.gold_pages for p in r.cited_pages)), len(pos)
        ),
        "refusal_rate": _rate(len(refused_neg), len(neg)),
        "refusal_reason_accuracy": _rate(
            sum(1 for r in refused_neg if r.reason == r.expected_reason), len(refused_neg)
        ),
        "false_answer_rate": _rate(len(false_answers), len(neg)),
        "fact_recall": _rate(sum(a for a, _ in facts), sum(b for _, b in facts)),
        "invariant_p1": _rate(sum(r.invariant_ok for r in results), len(results)),
    }
    ranks = [_first_rank(r) for r in pos]
    for k in KS:
        out[f"recall_at_{k}"] = _rate(sum(1 for x in ranks if x and x <= k), len(ranks))
    out["mrr"] = (sum(1.0 / x for x in ranks if x) / len(ranks)) if ranks else None
    return out


def bootstrap_ci(
    results: Sequence[Result],
    metric: Callable[[Sequence[Result]], float | None],
    *,
    seed: int,
    n: int = 1000,
) -> tuple[float, float] | None:
    """95 % percentile bootstrap over questions. ``None`` when the metric is undefined."""
    if not results or metric(results) is None:
        return None
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(n):
        sample = [results[rng.randrange(len(results))] for _ in results]
        v = metric(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return lo, hi


def latency(results: Sequence[Result]) -> dict[str, float]:
    def pct(xs: list[float], p: float) -> float:
        xs = sorted(xs)
        return xs[min(len(xs) - 1, round(p * (len(xs) - 1)))]

    s = [r.search_s for r in results]
    a = [r.answer_s for r in results]
    return {
        "search_p50_s": statistics.median(s),
        "search_p95_s": pct(s, 0.95),
        "answer_p50_s": statistics.median(a),
        "answer_p95_s": pct(a, 0.95),
    }
