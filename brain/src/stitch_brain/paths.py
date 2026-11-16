"""Filesystem locations. Overridable by env so the container and tests can relocate them."""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent
BRAIN_DIR = _PKG.parents[1]  # brain/


def repo_root() -> Path:
    env = os.environ.get("STITCH_REPO_ROOT")
    if env:
        return Path(env)
    for parent in _PKG.parents:
        if (parent / "data" / "demo").is_dir():
            return parent
    return Path.cwd()


def config_dir() -> Path:
    env = os.environ.get("STITCH_BRAIN_CONFIG")
    return Path(env) if env else BRAIN_DIR / "config"


def demo_dir() -> Path:
    env = os.environ.get("STITCH_DEMO_DIR")
    return Path(env) if env else repo_root() / "data" / "demo"


def recorded_dir() -> Path:
    return demo_dir() / "recorded"


def evals_results_dir() -> Path:
    env = os.environ.get("STITCH_EVALS_RESULTS")
    return Path(env) if env else repo_root() / "evals" / "results"
