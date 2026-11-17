"""Reranker on versus off per query language, on calibration items only (design 6.5, task 19).

    uv run python -m evals.library.compare_rerank

For the answerable committed-tier items of the dev split plus ``dev_extra.jsonl`` it reports, per
language, MRR and recall@1/3 of the first gold-or-alt page with the cross-encoder ordering and
with the RRF ordering (reranker off), and the dev refusal cost of each setting's calibrated
threshold. The test split is never read. Output: ``evals/library/rerank_comparison.json``
(committed, deterministic).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evals.library.calibrate import calibration_items, item_signals, profile_from
from evals.library.dataset import Question

OUT = Path(__file__).resolve().parent / "rerank_comparison.json"


def rank_metrics(ranks: Sequence[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    return {
        "mrr": round(sum(1.0 / r for r in ranks if r) / n, 4),
        "recall@1": round(sum(1 for r in ranks if r and r <= 1) / n, 4),
        "recall@3": round(sum(1 for r in ranks if r and r <= 3) / n, 4),
        "n": len(ranks),
    }


def compare(items: Sequence[Question]) -> dict[str, Any]:
    from evals.library.corpus import build_service

    out: dict[str, Any] = {}
    for reranker_on in (True, False):
        svc = build_service("committed", reranker_on=reranker_on, rerank_langs=("en", "ur")).service
        sig = [item_signals(svc, q) for q in items]
        scorers = ("rerank",) if reranker_on else ("dense",)
        prof = profile_from(sig, scorers)
        name = "rerank" if reranker_on else "rrf"
        for lang in ("en", "ur"):
            ranks = [
                s.gold_rank
                for s, q in zip(sig, items, strict=True)
                if q.lang == lang and q.answerable and q.tier == "committed"
            ]
            rep = prof["report"][f"{lang}.{scorers[0]}"]
            # An answerable item whose gold page is not in the top 3 cannot be answered well
            # by either setting; it counts as a false refusal so both settings are scored on
            # the same items.
            misses = sum(1 for r in ranks if not r or r > 3)
            out.setdefault(lang, {})[name] = rank_metrics(ranks) | {
                "threshold": round(rep["threshold"], 4),
                "dev_false_answers": rep["false_answers"],
                "dev_false_refusals": rep["false_refusals"],
                "dev_retrieval_misses": misses,
                "dev_cost": 3 * rep["false_answers"] + rep["false_refusals"] + misses,
            }
    for d in out.values():
        r, f = d["rerank"], d["rrf"]
        # Rule (decided before running): the reranker stays on for a language only if it lowers
        # the dev refusal cost, or keeps it equal and raises MRR.
        d["reranker_helps"] = r["dev_cost"] < f["dev_cost"] or (
            r["dev_cost"] == f["dev_cost"] and r["mrr"] > f["mrr"]
        )
    return out


def main() -> int:
    result = compare(calibration_items())
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for lang, d in result.items():
        print(lang, json.dumps(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
