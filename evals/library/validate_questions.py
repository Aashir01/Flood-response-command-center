"""Validate the Library question set (design 10.2 step 4, LIB-P12).

    uv run python -m evals.library.validate_questions            # check, exit 1 on problems
    uv run python -m evals.library.validate_questions --assign-split   # once, before calibration

Checks: counts and quotas, at least 10 unanswerable, the committed share of answerable questions,
cross-lingual Urdu questions, gold documents exist in the manifest, each ``evidence_quote`` is a
verbatim substring of the stored page text after normalization (fetch-tier pages only when the
document was fetched locally), tiers, the split rule and the committed ``split.lock``, and the
calibration file's dev ids (dev and test never intersect).
"""

from __future__ import annotations

import argparse
import json
import sys

from evals.library.dataset import (
    DEV_EXTRA,
    QUESTIONS,
    SPLIT_LOCK,
    assign_splits,
    ids_hash,
    load,
    split_hash,
    validate,
    write_splits,
)


def calibration_problems() -> list[str]:
    """The committed calibration used only dev ids (LIB-P12)."""
    from stitch_library.calibration import CALIBRATION_PATH

    if not CALIBRATION_PATH.exists():
        return []
    data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    questions = load(QUESTIONS)
    test_ids = {q.id for q in questions if q.split == "test"}
    out: list[str] = []
    for key, prof in (data.get("profiles") or {}).items():
        used = set(prof.get("dev_ids") or [])
        if used & test_ids:
            out.append(f"calibration profile {key} used test ids {sorted(used & test_ids)}")
        if prof.get("dev_ids_sha256") and prof["dev_ids_sha256"] != ids_hash(used):
            out.append(f"calibration profile {key}: dev_ids_sha256 does not match dev_ids")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--assign-split", action="store_true")
    parser.add_argument("--force", action="store_true", help="reassign even if split.lock exists")
    args = parser.parse_args(argv)

    from evals.library.corpus import manifest_tiers, normalize_quote, page_lookup

    questions = load(QUESTIONS)
    if args.assign_split:
        if SPLIT_LOCK.exists() and not args.force:
            print("split.lock exists; the split is frozen (use --force only before calibration)")
            return 1
        splits = assign_splits(questions)
        write_splits(QUESTIONS, splits)
        SPLIT_LOCK.write_text(split_hash(splits.items()) + "\n", encoding="utf-8")
        questions = load(QUESTIONS)
        print(f"assigned splits: {sum(s == 'dev' for s in splits.values())} dev")
    extra = load(DEV_EXTRA)
    lock = SPLIT_LOCK.read_text(encoding="utf-8").strip() if SPLIT_LOCK.exists() else None
    errors = validate(
        questions,
        extra,
        manifest=manifest_tiers(),
        page_text=page_lookup(include_fetched=True),
        lock=lock,
        normalize=normalize_quote,
    )
    errors += calibration_problems()
    for e in errors:
        print(f"error: {e}")
    if errors:
        return 1
    dev = [q for q in questions if q.split == "dev"]
    committed = sum(q.answerable and q.tier == "committed" for q in questions)
    answerable = sum(q.answerable for q in questions)
    print(
        f"ok: {len(questions)} questions ({len(dev)} dev, {len(questions) - len(dev)} test), "
        f"{len(extra)} dev_extra, {committed}/{answerable} answerable on the committed corpus"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
