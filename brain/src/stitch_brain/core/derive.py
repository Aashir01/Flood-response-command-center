"""Named pure derivations (design 5.2). A slot value is either a resolved evidence leaf or the
output of one of these functions over the slot's resolved refs, so the critic can recompute it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from stitch_brain.core.claims import Slot
from stitch_brain.core.evidence import EvidenceStore, ResolvedRef
from stitch_brain.core.numbers import to_decimal

Value = Decimal | str


class DerivationError(ValueError):
    pass


def _nums(values: Sequence[Any]) -> list[Decimal]:
    return [to_decimal(v) for v in values]


def d_sum(values: Sequence[Any], **_: Any) -> Value:
    return sum(_nums(values), Decimal(0))


def d_count(values: Sequence[Any], **_: Any) -> Value:
    return Decimal(len(values))


def d_max(values: Sequence[Any], **_: Any) -> Value:
    return max(_nums(values))


def d_min(values: Sequence[Any], **_: Any) -> Value:
    return min(_nums(values))


def d_ratio(values: Sequence[Any], **_: Any) -> Value:
    a, b = _nums(values)[:2]
    if b == 0:
        raise DerivationError("ratio with zero denominator")
    return a / b


def d_per_day(values: Sequence[Any], days: str = "1", **_: Any) -> Value:
    return _nums(values)[0] / Decimal(days)


def d_diff(values: Sequence[Any], **_: Any) -> Value:
    a, b = _nums(values)[:2]
    return a - b


def d_rel_diff(values: Sequence[Any], **_: Any) -> Value:
    a, b = _nums(values)[:2]
    m = max(abs(a), abs(b))
    return Decimal(0) if m == 0 else abs(a - b) / m


def d_date_part(values: Sequence[Any], **_: Any) -> Value:
    return str(values[0])[:10]


def d_lookup(values: Sequence[Any], table: str = "", lang: str = "en", **_: Any) -> Value:
    """Map an evidence string through a fixed i18n table; the tables are passed at call time by
    ``recompute`` (see ``LOOKUPS``)."""
    tbl = LOOKUPS.get(table, {}).get(lang, {})
    key = str(values[0])
    if key not in tbl:
        raise DerivationError(f"no {table} label for {key!r}")
    return tbl[key]


def d_join(values: Sequence[Any], sep: str = ", ", **_: Any) -> Value:
    return sep.join(str(v) for v in values)


DERIVATIONS: dict[str, Callable[..., Value]] = {
    "sum": d_sum,
    "count": d_count,
    "max": d_max,
    "min": d_min,
    "ratio": d_ratio,
    "per_day": d_per_day,
    "diff": d_diff,
    "rel_diff": d_rel_diff,
    "date_part": d_date_part,
    "lookup": d_lookup,
    "join": d_join,
}

#: i18n lookup tables (organ names, solver status words, unit labels, refusal reasons) by table
#: and language. Filled from ``config/i18n`` at startup by ``set_lookups``; pure afterwards.
LOOKUPS: dict[str, dict[str, dict[str, str]]] = {}


def set_lookups(tables: Mapping[str, Mapping[str, Mapping[str, str]]]) -> None:
    LOOKUPS.clear()
    for name, by_lang in tables.items():
        LOOKUPS[name] = {lang: dict(t) for lang, t in by_lang.items()}


def recompute(slot: Slot, store: EvidenceStore) -> Value | None:
    """Re-resolve the slot's refs and re-run its derivation. ``None`` if a ref fails."""
    values: list[Any] = []
    for ref in slot.refs:
        res = store.resolve(ref)
        if not isinstance(res, ResolvedRef):
            return None
        values.append(res.value)
    try:
        if slot.derivation is None:
            v = values[0]
            if slot.fmt in ("int", "dec", "pct"):
                return to_decimal(v)
            if slot.fmt == "date":
                return str(v)[:10]
            return str(v)
        fn = DERIVATIONS[slot.derivation.fn]
        return fn(values, **slot.derivation.params)
    except (DerivationError, KeyError, TypeError, ValueError, ArithmeticError):
        return None


def slot_matches(slot: Slot, store: EvidenceStore) -> bool:
    got = recompute(slot, store)
    if got is None:
        return False
    want: Any = slot.value
    if slot.fmt == "date":
        want = str(want)[:10]
    if isinstance(got, Decimal) and isinstance(want, Decimal):
        return got == want
    return str(got) == str(want)
