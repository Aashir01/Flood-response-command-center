"""Refusal-threshold calibration on the dev split (design 8.4, LIB-R4.5).

    uv run python -m evals.library.calibrate --seed 0

Items: the ``dev`` split of ``questions.jsonl`` plus ``dev_extra.jsonl``, retrieved against the
committed corpus. Never the test split. For every item the retrieval signals are recorded
(``LibraryService.probe``):

* evidence: a positive is an answerable committed-tier item whose gold (or alt) page is in the
  top 3 hits; a negative is an ``INSUFFICIENT_EVIDENCE`` or ``OUT_OF_SCOPE`` item. Conflict
  items and fetch-tier items (unanswerable on the committed corpus for a different reason) are
  left out.
* scope: in-scope items (everything except ``OUT_OF_SCOPE``) against ``OUT_OF_SCOPE`` items.

``select_threshold`` minimizes ``3 * false answers + 1 * false refusals`` over the midpoints of
the sorted scores; ties go to the larger threshold. A language with fewer than 8 negatives uses
the pooled threshold and the profile records a warning. One profile is written per reranker
setting (on and off) for the loaded embedder, to ``stitch_library/calibration.json``.
"""

from __future__ import annotations

import argparse
import itertools
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from evals.library.dataset import DEV_EXTRA, QUESTIONS, Question, ids_hash, load

COST_FALSE_ANSWER = 3.0
COST_FALSE_REFUSAL = 1.0
MIN_NEGATIVES = 8
TOP_EVIDENCE = 3


@dataclass(frozen=True)
class Choice:
    threshold: float
    false_answers: int
    false_refusals: int
    n_pos: int
    n_neg: int

    @property
    def cost(self) -> float:
        return COST_FALSE_ANSWER * self.false_answers + COST_FALSE_REFUSAL * self.false_refusals


def candidates(scores: Sequence[float]) -> list[float]:
    """Midpoints between sorted distinct scores, plus one point below and one above all."""
    xs = sorted(set(scores))
    if not xs:
        return [0.0]
    mids = [(a + b) / 2.0 for a, b in itertools.pairwise(xs)]
    return [xs[0] - 1e-3, *mids, xs[-1] + 1e-3]


def select_threshold(
    pos: Sequence[float],
    neg: Sequence[float],
    *,
    cost_fa: float = COST_FALSE_ANSWER,
    cost_fr: float = COST_FALSE_REFUSAL,
) -> Choice:
    """Answer when ``score >= threshold``. Minimum weighted cost, ties to the larger threshold."""
    best: Choice | None = None
    best_cost = float("inf")
    for t in candidates([*pos, *neg]):
        fa = sum(s >= t for s in neg)
        fr = sum(s < t for s in pos)
        cost = cost_fa * fa + cost_fr * fr
        if cost < best_cost or (cost == best_cost and best is not None and t > best.threshold):
            best, best_cost = Choice(t, fa, fr, len(pos), len(neg)), cost
    assert best is not None
    return best


@dataclass(frozen=True)
class ItemSignals:
    id: str
    lang: str
    role_evidence: str  # "pos" | "neg" | "skip"
    role_scope: str  # "pos" | "neg"
    scope: float
    rerank: float | None
    dense: float | None
    gold_rank: int | None  # 1-based rank of the first gold/alt page among hits


def item_signals(service: Any, q: Question) -> ItemSignals:
    p = service.probe(q.question)
    pages = q.pages()
    rank = next(
        (i for i, h in enumerate(p.hits, start=1) if (h.chunk.doc_id, h.chunk.page) in pages),
        None,
    )
    if q.answerable and q.tier == "committed":
        ev = "pos" if rank is not None and rank <= TOP_EVIDENCE else "skip"
    elif q.expected_reason in ("INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE"):
        ev = "neg"
    else:
        ev = "skip"
    sc = "neg" if q.expected_reason == "OUT_OF_SCOPE" else "pos"
    return ItemSignals(q.id, q.lang, ev, sc, p.scope_score, p.rerank_score, p.dense_score, rank)


def _scores(items: Sequence[ItemSignals], role: str, attr: str, lang: str | None) -> list[float]:
    out: list[float] = []
    for it in items:
        if it.role_evidence != role or (lang is not None and it.lang != lang):
            continue
        v = getattr(it, attr)
        if v is not None:  # the scorer did not run for this item (reranker gated off)
            out.append(float(v))
    return out


def profile_from(items: Sequence[ItemSignals], scorers: Sequence[str]) -> dict[str, Any]:
    """Thresholds and diagnostics for one model profile."""
    warnings: list[str] = []
    tau_evid: dict[str, dict[str, float]] = {}
    report: dict[str, Any] = {}
    for scorer in scorers:
        attr = "rerank" if scorer == "rerank" else "dense"
        pooled = select_threshold(
            _scores(items, "pos", attr, None), _scores(items, "neg", attr, None)
        )
        tau_evid.setdefault("pooled", {})[scorer] = round(pooled.threshold, 6)
        report[f"pooled.{scorer}"] = pooled.__dict__ | {"cost": pooled.cost}
        for lang in ("en", "ur"):
            neg = _scores(items, "neg", attr, lang)
            pos = _scores(items, "pos", attr, lang)
            if not pos and not neg:
                # The scorer never ran for this language (reranker gated off): no threshold;
                # at runtime ``Calibration.thresholds`` falls back to the pooled value.
                warnings.append(f"{lang}/{scorer}: scorer did not run for this language")
                continue
            if len(neg) < MIN_NEGATIVES:
                warnings.append(f"{lang}/{scorer}: {len(neg)} negatives < {MIN_NEGATIVES}, pooled")
                choice = pooled
            else:
                choice = select_threshold(pos, neg)
            tau_evid.setdefault(lang, {})[scorer] = round(choice.threshold, 6)
            fa = sum(s >= choice.threshold for s in neg)
            fr = sum(s < choice.threshold for s in pos)
            report[f"{lang}.{scorer}"] = {
                "threshold": choice.threshold,
                "n_pos": len(pos),
                "n_neg": len(neg),
                "false_answers": fa,
                "false_refusals": fr,
                "false_answer_rate": fa / len(neg) if neg else None,
                "false_refusal_rate": fr / len(pos) if pos else None,
            }
    scope_pos = [it.scope for it in items if it.role_scope == "pos"]
    scope_neg = [it.scope for it in items if it.role_scope == "neg"]
    scope = select_threshold(scope_pos, scope_neg)
    report["scope"] = scope.__dict__ | {"cost": scope.cost}
    return {
        "tau_scope": round(scope.threshold, 6),
        "tau_evid": tau_evid,
        "report": report,
        "warnings": warnings,
        "skipped_ids": sorted(it.id for it in items if it.role_evidence == "skip"),
    }


def calibration_items() -> list[Question]:
    dev = [q for q in load(QUESTIONS) if q.split == "dev"]
    return [*dev, *load(DEV_EXTRA)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args(argv)
    random.seed(args.seed)  # the procedure is deterministic; the seed is recorded

    from evals.library.corpus import build_service
    from stitch_library.calibration import CALIBRATION_PATH, profile_key, write_profile

    items = calibration_items()
    dev_ids = sorted(q.id for q in items)
    for reranker_on in (True, False):
        built = build_service("committed", reranker_on=reranker_on)
        svc = built.service
        signals = [item_signals(svc, q) for q in items]
        scorers = ("rerank", "dense") if reranker_on else ("dense",)
        prof = profile_from(signals, scorers)
        key = profile_key(svc.embedder.model_id, svc.reranker.model_id)
        prof.update(
            {
                "provisional": False,
                "seed": args.seed,
                "calibrated_at": datetime.now(UTC).date().isoformat(),
                "corpus": "committed",
                "pack_content_sha256": svc.store.get_meta("content_sha256") or _pack_sha(),
                "embedder": {"id": svc.embedder.model_id, "revision": svc.embedder.revision},
                "reranker": {"id": svc.reranker.model_id, "revision": svc.reranker.revision},
                "dev_ids": dev_ids,
                "dev_ids_sha256": ids_hash(dev_ids),
                "counts": {
                    "items": len(items),
                    "evidence_pos": sum(s.role_evidence == "pos" for s in signals),
                    "evidence_neg": sum(s.role_evidence == "neg" for s in signals),
                    "scope_neg": sum(s.role_scope == "neg" for s in signals),
                },
                "cost_weights": {
                    "false_answer": COST_FALSE_ANSWER,
                    "false_refusal": COST_FALSE_REFUSAL,
                },
            }
        )
        print(f"{key}: tau_scope={prof['tau_scope']} tau_evid={prof['tau_evid']}")
        for w in prof["warnings"]:
            print(f"  warning: {w}")
        if not args.dry_run:
            write_profile(key, prof)
    if not args.dry_run:
        print(f"wrote {CALIBRATION_PATH}")
    return 0


def _pack_sha() -> str:
    from stitch_library.pack import load_pack

    return str(load_pack().meta.get("content_sha256", ""))


if __name__ == "__main__":
    sys.exit(main())
