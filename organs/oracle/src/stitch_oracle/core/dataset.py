"""Design matrix for training, calibration and evaluation (pure).

Rows are ``(as_of, station)`` pairs built with the same ``feature_table`` that serving uses, so a
row equals ``build_features(frames, station, as_of)`` exactly (tested). Targets are the log
ratios ``y_h`` for every lead; they read the future by definition and are never features.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from stitch_oracle.core.features import FEATURES, Wide, feature_table, targets
from stitch_oracle.core.splits import Split
from stitch_oracle.core.stations import Catalog


@dataclass(frozen=True)
class Design:
    dates: np.ndarray  # object array of date
    station_ids: np.ndarray  # object array of str
    q_t: np.ndarray  # (n,) modeled discharge at as_of, m3/s
    x: np.ndarray  # (n, F)
    y: np.ndarray  # (n, H) log-ratio targets (NaN past the data end)
    leads: tuple[int, ...]

    def __len__(self) -> int:
        return int(self.x.shape[0])

    def select(self, mask: np.ndarray) -> Design:
        return Design(
            self.dates[mask],
            self.station_ids[mask],
            self.q_t[mask],
            self.x[mask],
            self.y[mask],
            self.leads,
        )

    def split_mask(self, split: Split, lead: int) -> np.ndarray:
        """Rows whose origin and target (``as_of + lead``) fall inside ``split`` (purge), with a
        finite target."""
        j = self.leads.index(lead)
        return split.mask(self.dates, lead) & np.isfinite(self.y[:, j])

    def target_dates(self, lead: int) -> list[date]:
        from datetime import timedelta

        return [d + timedelta(days=lead) for d in self.dates]


def design_matrix(
    wide: Wide,
    catalog: Catalog,
    station_ids: Sequence[str],
    codes: Mapping[str, int],
    leads: Sequence[int],
    require: str | None = "dlnq_30",
) -> Design:
    parts_x, parts_y, parts_d, parts_s, parts_q = [], [], [], [], []
    for sid in sorted(station_ids):
        st = catalog.get(sid)
        if st is None:
            raise KeyError(sid)
        table = feature_table(wide, st, catalog, dict(codes))
        y = targets(wide, sid, range(1, max(leads) + 1))[list(leads)]
        keep = np.isfinite(wide.q[sid].to_numpy("float64"))
        if require is not None:
            keep &= np.isfinite(table[require].to_numpy("float64"))
        parts_x.append(table.to_numpy("float64")[keep])
        parts_y.append(y.to_numpy("float64")[keep])
        parts_d.append(np.asarray(table.index, dtype=object)[keep])
        parts_s.append(np.full(int(keep.sum()), sid, dtype=object))
        parts_q.append(wide.q[sid].to_numpy("float64")[keep])
    return Design(
        dates=np.concatenate(parts_d),
        station_ids=np.concatenate(parts_s),
        q_t=np.concatenate(parts_q),
        x=np.vstack(parts_x),
        y=np.vstack(parts_y),
        leads=tuple(int(h) for h in leads),
    )


def feature_ranges(x: np.ndarray, names: Sequence[str] = FEATURES) -> dict[str, list[float]]:
    """Per-feature finite min and max (for the out-of-range flag)."""
    out: dict[str, list[float]] = {}
    for i, n in enumerate(names):
        col = x[:, i]
        col = col[np.isfinite(col)]
        if col.size:
            out[n] = [float(col.min()), float(col.max())]
    return out


def to_frame(d: Design) -> pd.DataFrame:
    return pd.DataFrame(d.x, columns=list(FEATURES)).assign(date=d.dates, station_id=d.station_ids)
