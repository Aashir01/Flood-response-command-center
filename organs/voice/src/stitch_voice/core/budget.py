"""Monthly budget arithmetic for paid APIs (design 3.3 and 14). Pure; the store is in
``stitch_voice.store``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

WARN_FRACTION = 0.8


def month_key(now: datetime) -> str:
    """UTC calendar month, e.g. ``2026-11``. ``now`` must be timezone-aware UTC."""
    return f"{now.year:04d}-{now.month:02d}"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    used_after: float
    warn: bool


def decide(used: float, amount: float, cap: float) -> Decision:
    """Whether ``amount`` fits under ``cap`` given ``used``. A cap of 0 or less disables the
    provider. ``warn`` is set when the new total reaches 80 % of the cap."""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    if cap <= 0 or used + amount > cap:
        return Decision(False, used, cap > 0 and used >= WARN_FRACTION * cap)
    total = used + amount
    return Decision(True, total, total >= WARN_FRACTION * cap)
