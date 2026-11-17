"""Library evals (LIB-R9, LIB-R10.4): ``python -m evals.run --organ library --seed 0 [--fast]``.

Runs the 50-question set (``questions.jsonl``) through the real Library service: local e5-small
and mMARCO models, the committed pack, ``FakeLLM`` replaying the demo recordings (other
questions take the extractive path), no network.

* ``--fast``: committed corpus, test split, reranker on.
* full run: adds the dev split (reported as "tuned on"), the reranker off, and the ``full``
  corpus (committed plus fetch-tier documents found under ``data/raw/library``).

Headline numbers are the committed corpus, test split. Before running, the harness refuses if
the calibration profile is missing, provisional or computed on another pack, if the split
differs from ``split.lock``, or if calibration used a test id (LIB-P12). Bootstrap 95 %
intervals (1000 resamples, ``seed``) are attached to the main rates; with 30 test questions
they are wide. Per-question rows and breakdowns go to ``evals/results/library_report.json``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.models import MetricResult

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
CI_METRICS = ("answer_rate", "refusal_rate", "false_answer_rate", "citation_accuracy")
TARGETS: dict[str, tuple[float, str]] = {
    "citation_validity": (1.0, "higher"),
    "invariant_p1": (1.0, "higher"),
}
LOWER_IS_BETTER = {"false_answer_rate"}


def _preflight(service: Any) -> None:
    from evals.library.dataset import QUESTIONS, SPLIT_LOCK, load, split_hash
    from evals.library.validate_questions import calibration_problems

    cal = service.calibration
    if cal.status != "ok":
        raise RuntimeError(
            f"calibration {cal.status} for {cal.key}; run python -m evals.library.calibrate"
        )
    pack_sha = str(service.store.get_meta("content_sha256") or "")
    if not pack_sha:
        from stitch_library.pack import load_pack

        pack_sha = str(load_pack().meta.get("content_sha256", ""))
    if cal.meta.get("pack_content_sha256") not in (None, pack_sha):
        raise RuntimeError("calibration was computed on another pack; recalibrate")
    questions = load(QUESTIONS)
    lock = SPLIT_LOCK.read_text(encoding="utf-8").strip()
    if split_hash((q.id, str(q.split)) for q in questions) != lock:
        raise RuntimeError("questions.jsonl split differs from split.lock (LIB-P12)")
    problems = calibration_problems()
    if problems:
        raise RuntimeError("; ".join(problems))


def _metric(
    mid: str,
    value: float,
    *,
    label: str,
    dataset: str,
    seed: int,
    sha: str,
    now: datetime,
    unit: str = "",
    notes: str = "",
) -> MetricResult:
    base = mid.rsplit(".", 1)[-1]
    target, direction = TARGETS.get(base, (None, "higher"))
    if base in LOWER_IS_BETTER or base.endswith("_s"):
        direction = "lower"
    # Latency has no pass/fail target here: laptop timings vary with load, and the eval status
    # must be a deterministic function of the seed. LIB-R8.3 (1.5 s p95 on 2 vCPU) is checked
    # by scripts/bench_library.py in the constrained container.
    return MetricResult(
        id=mid,
        label=label,
        value=float(value),
        target=target,
        unit=unit,
        direction=direction,  # type: ignore[arg-type]
        dataset=dataset,
        mode="demo",
        timestamp=now,
        git_sha=sha,
        seed=seed,
        notes=notes,
    )


def _block(
    results: Sequence[Any],
    prefix: str,
    dataset: str,
    *,
    seed: int,
    sha: str,
    now: datetime,
    note: str,
) -> tuple[list[MetricResult], dict[str, Any]]:
    from evals.library.harness import bootstrap_ci, metrics_for

    vals = metrics_for(results)
    out: list[MetricResult] = []
    report: dict[str, Any] = {"metrics": vals, "ci95": {}}
    for name, v in vals.items():
        if v is None or name == "n":
            continue
        notes = note
        if name in CI_METRICS:
            ci = bootstrap_ci(results, lambda rs, n=name: metrics_for(rs)[n], seed=seed)
            if ci is not None:
                report["ci95"][name] = ci
                notes = f"{note} 95% CI [{ci[0]:.2f}, {ci[1]:.2f}], n={len(results)}".strip()
        out.append(
            _metric(
                f"{prefix}.{name}",
                v,
                label=f"Library {name.replace('_', ' ')} ({dataset})",
                dataset=dataset,
                seed=seed,
                sha=sha,
                now=now,
                notes=notes,
            )
        )
    return out, report


def run(fast: bool, seed: int) -> list[MetricResult]:
    from evals.library.corpus import build_service, fetched
    from evals.library.dataset import QUESTIONS, load
    from evals.library.harness import latency, run_question
    from evals.run import git_sha

    sha = git_sha()
    now = datetime.now(UTC)
    questions = load(QUESTIONS)
    plans: list[tuple[str, bool, str]] = [("committed", True, "test")]
    if not fast:
        plans += [("committed", True, "dev"), ("committed", False, "test")]
        if fetched().docs:
            plans.append(("full", True, "test"))
    metrics: list[MetricResult] = []
    report: dict[str, Any] = {"generated_at": now.isoformat(), "seed": seed, "runs": {}}
    for corpus, rr_on, split in plans:
        built = build_service(corpus, reranker_on=rr_on)  # type: ignore[arg-type]
        _preflight(built.service)
        qs = [q for q in questions if q.split == split]
        results = [run_question(built.service, q, corpus) for q in qs]
        tag = f"{corpus}.{split}" + ("" if rr_on else ".no_rerank")
        dataset = f"library-50q:{corpus}:{split}" + ("" if rr_on else ":rerank-off")
        note = "tuned on (calibration split)" if split == "dev" else ""
        ms, rep = _block(results, f"library.{tag}", dataset, seed=seed, sha=sha, now=now, note=note)
        metrics += ms
        by: dict[str, Any] = {}
        for key, sel in (
            ("lang.en", lambda r: r.lang == "en"),
            ("lang.ur", lambda r: r.lang == "ur"),
            ("generation.llm", lambda r: r.generation == "llm"),
            ("generation.extractive", lambda r: r.generation == "extractive"),
        ):
            from evals.library.harness import metrics_for

            sub = [r for r in results if sel(r)]
            by[key] = metrics_for(sub) if sub else None
        rep["breakdown"] = by
        rep["latency"] = latency(results)
        rep["docs"] = built.docs
        rep["questions"] = [
            {
                "id": r.qid,
                "lang": r.lang,
                "expected": r.expected_status,
                "expected_reason": r.expected_reason,
                "status": r.status,
                "reason": r.reason,
                "generation": r.generation,
                "cited_pages": r.cited_pages,
                "first_gold_rank": next(
                    (i for i, p in enumerate(r.hit_pages, 1) if p in r.gold_pages), None
                ),
                "from_alt": r.from_alt,
                "answer": r.answer,
                "warnings": r.warnings,
            }
            for r in results
        ]
        report["runs"][tag] = rep
        if corpus == "committed" and rr_on and split == "test":
            for lang in ("en", "ur"):
                sub = [r for r in results if r.lang == lang]
                ms2, _ = _block(
                    sub,
                    f"library.{tag}.{lang}",
                    f"{dataset}:{lang}",
                    seed=seed,
                    sha=sha,
                    now=now,
                    note="",
                )
                metrics += [
                    m
                    for m in ms2
                    if m.id.rsplit(".", 1)[-1]
                    in ("answer_rate", "refusal_rate", "false_answer_rate", "recall_at_3")
                ]
            for k, v in latency(results).items():
                metrics.append(
                    _metric(
                        f"library.{tag}.{k}",
                        v,
                        label=f"Library {k} (laptop, in-process)",
                        dataset=dataset,
                        seed=seed,
                        sha=sha,
                        now=now,
                        unit="s",
                        notes="Measured on the dev laptop, not the 2 vCPU container.",
                    )
                )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "library_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=list) + "\n", encoding="utf-8"
    )
    return metrics
