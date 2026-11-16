"""Helpers for offline fixture capture: the exact Ledger arguments the Brain sends per variant."""

from __future__ import annotations

from typing import Any

from stitch_brain.config import ScenarioCfg
from stitch_brain.core.plans import ledger_fallback_args


def ledger_variant_args(scenario: ScenarioCfg, variant: str) -> dict[str, Any] | None:
    """``defaults``: no district override. ``full`` and ``eyes_only``: the severity mapping
    (design 8) over the recorded Eyes, Oracle and district fixtures of the scenario."""
    if variant == "defaults":
        return ledger_fallback_args(scenario, "demo")
    return None
