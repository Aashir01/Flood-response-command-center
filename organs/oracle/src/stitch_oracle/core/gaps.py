"""Gap rules for the feature window (design section 6, ORA-R1.4).

Inside the trailing feature window, a run of at most ``MAX_FILL`` missing days in a needed
column is forward-filled and reported; a longer run (or a gap with no earlier value) raises
``GapError``, which the tool returns as ``UPSTREAM_UNAVAILABLE``. Nothing is imputed silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from stitch_oracle.core.features import MAX_WINDOW, Wide

MAX_FILL = 2


class GapError(Exception):
    def __init__(self, message: str, columns: Sequence[str]) -> None:
        super().__init__(message)
        self.columns = tuple(columns)


@dataclass(frozen=True)
class GapReport:
    filled: tuple[tuple[str, date], ...]  # (column, date) pairs that were forward-filled

    def warning(self) -> str | None:
        if not self.filled:
            return None
        days = sorted({d for _, d in self.filled})
        cols = sorted({c for c, _ in self.filled})
        shown = ", ".join(d.isoformat() for d in days[:5])
        more = f" (+{len(days) - 5} more)" if len(days) > 5 else ""
        return (
            f"missing input days forward-filled (at most {MAX_FILL} in a row): {shown}{more} "
            f"in {', '.join(cols)}"
        )


def _fill(series: pd.Series, window_start: date, name: str) -> tuple[pd.Series, list[date]]:
    filled = series.ffill(limit=MAX_FILL)
    in_window = [d >= window_start for d in series.index]
    mask = pd.Series(in_window, index=series.index)
    still = filled[mask].isna()
    if bool(still.any()):
        first = still[still].index[0]
        raise GapError(
            f"input {name} has a gap longer than {MAX_FILL} days near {first.isoformat()}",
            [name],
        )
    changed = series[mask].isna()
    days = [d for d, c in changed.items() if c]
    out = series.copy()
    out[mask] = filled[mask]
    return out, days


def fill_window(
    wide: Wide, as_of: date, stations: Sequence[str], window: int = MAX_WINDOW
) -> tuple[Wide, GapReport]:
    """Extend the index to ``as_of``, then apply the gap rules to the needed columns over the
    last ``window`` days."""
    start = wide.q.index[0]
    idx = pd.date_range(start, as_of, freq="D").date
    q = wide.q.reindex(idx)
    precip = wide.precip.reindex(idx)
    temp = wide.temp.reindex(idx)
    window_start = as_of - timedelta(days=window)
    filled: list[tuple[str, date]] = []
    for sid in stations:
        if sid not in q.columns:
            raise GapError(f"no modeled discharge for {sid}", [sid])
        q[sid], days = _fill(q[sid], window_start, sid)
        filled += [(sid, d) for d in days]
    for pt in precip.columns:
        precip[pt], days = _fill(precip[pt], window_start, str(pt))
        filled += [(str(pt), d) for d in days]
    temp, days = _fill(temp, window_start, "temperature")
    filled += [("temperature", d) for d in days]
    return Wide(q, precip, temp), GapReport(tuple(filled))
