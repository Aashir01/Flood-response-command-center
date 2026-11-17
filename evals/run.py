"""Eval runner: ``python -m evals.run --organ <name|all> [--fast] [--seed N]``.

Each organ's evals live in ``evals/<organ>/`` (a package) and expose
``run(fast: bool, seed: int) -> list[MetricResult]``. Organs without that module are reported
as ``not_run``. Output: ``evals/results/<organ>.json`` and ``evals/results/latest.json`` (the
latter merges every per-organ file). ``--write-schema`` rewrites ``evals/results/schema.json``.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from evals.models import ORGANS, Latest, MetricResult, OrganResult, results_schema

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"
REPO_ROOT = EVALS_DIR.parent


def git_sha(root: Path = REPO_ROOT) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return res.stdout.strip() or "unknown"


def run_organ(organ: str, fast: bool, seed: int) -> OrganResult:
    """Run one organ's evals. Missing module is ``not_run``; a raised exception is ``error``."""
    module_name = f"evals.{organ}"
    if importlib.util.find_spec(module_name) is None:
        return OrganResult(status="not_run", message=f"no eval module {module_name}")
    try:
        module = importlib.import_module(module_name)
        out = module.run(fast=fast, seed=seed)
    except Exception as exc:
        return OrganResult(status="error", message=f"{type(exc).__name__}: {exc}")
    if isinstance(out, OrganResult):  # an organ may report not_run or a message itself
        return out
    metrics: list[MetricResult] = out
    failed = any(m.met_target is False for m in metrics)
    return OrganResult(status="fail" if failed else "pass", metrics=metrics)


def _write_json(path: Path, text: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")  # evals/results/*.tmp is git-ignored
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def merge_latest(results_dir: Path = RESULTS_DIR, sha: str | None = None) -> Latest:
    """Merge ``<organ>.json`` files; organs without a file are ``not_run``."""
    organs: dict[str, OrganResult] = {}
    for organ in ORGANS:
        f = results_dir / f"{organ}.json"
        if f.exists():
            organs[organ] = OrganResult.model_validate_json(f.read_text(encoding="utf-8"))
        else:
            organs[organ] = OrganResult(status="not_run", message="not run yet")
    return Latest(generated_at=datetime.now(UTC), git_sha=sha or git_sha(), organs=organs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organ", default="all", help=f"one of {', '.join(ORGANS)} or all")
    parser.add_argument("--fast", action="store_true", help="fast subset (used by the save hook)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--write-schema", action="store_true")
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="use a real LLM where an eval has a judge (sets STITCH_EVAL_LIVE_LLM=1; network)",
    )
    args = parser.parse_args(argv)

    if args.write_schema:
        _write_json(RESULTS_DIR / "schema.json", json.dumps(results_schema(), indent=2))
        return 0
    if args.organ != "all" and args.organ not in ORGANS:
        parser.error(f"unknown organ {args.organ!r}")

    sys.path.insert(0, str(REPO_ROOT))
    if args.live_llm:
        os.environ["STITCH_EVAL_LIVE_LLM"] = "1"
    statuses: list[str] = []
    for organ in ORGANS if args.organ == "all" else (args.organ,):
        result = run_organ(organ, args.fast, args.seed)
        statuses.append(result.status)
        _write_json(RESULTS_DIR / f"{organ}.json", result.model_dump_json(indent=2))
        print(f"{organ}: {result.status}" + (f" ({result.message})" if result.message else ""))
    latest = merge_latest()
    _write_json(RESULTS_DIR / "latest.json", latest.model_dump_json(indent=2))
    return 1 if any(s in ("fail", "error") for s in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
