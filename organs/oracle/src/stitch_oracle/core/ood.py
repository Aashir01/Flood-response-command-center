"""Out-of-distribution flag (design section 4.6, ORA-R5.2).

A feature is out of range when it lies outside ``[min - 5% range, max + 5% range]`` of the refit
training rows. NaN features (no upstream slot, for example) are not checked. The flag adds a
warning and never changes the numbers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

MARGIN = 0.05


def out_of_range(
    names: Sequence[str],
    values: Sequence[float],
    ranges: Mapping[str, tuple[float, float]],
    margin: float = MARGIN,
) -> list[str]:
    out: list[str] = []
    for name, v in zip(names, values, strict=True):
        if v is None or (isinstance(v, float) and math.isnan(v)) or name not in ranges:
            continue
        lo, hi = ranges[name]
        pad = margin * (hi - lo)
        if v < lo - pad or v > hi + pad:
            out.append(name)
    return out


def warning(names: Sequence[str]) -> str | None:
    if not names:
        return None
    shown = ", ".join(names[:3])
    more = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
    return f"input features outside training range: {shown}{more}; the forecast extrapolates"
