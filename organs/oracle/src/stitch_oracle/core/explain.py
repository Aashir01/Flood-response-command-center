"""Explanations (design section 4.7, ORA-R4.5): TreeSHAP on the p50 model at the peak lead,
mapped to m3/s, with a template narrative. No LLM.

TreeSHAP contributions ``phi_f`` and bias ``phi_0`` add up exactly to the raw p50 prediction in
target space (log ratio). With anchor ``A = Q_t + 1``:

* ``baseline_m3s = A exp(phi_0) - 1``: the model's average prediction for this starting level;
* ``c_f = A exp(phi_0) * expm1(S) / S * phi_f`` with ``S = sum(phi_f)`` (log-share allocation).
  ``sum(c_f) = A exp(phi_0 + S) - A exp(phi_0)`` = raw median minus baseline, exactly, and the
  factor is finite as ``S -> 0`` (its limit is ``A exp(phi_0)``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from stitch_oracle.core.features import FEATURES, GROUPS, feature_group

TOP_K = 5

#: Plain-language labels. Every label that names a discharge says "modeled".
LABELS: dict[str, str] = {
    "lnq": "current modeled discharge level",
    "dlnq_1": "1-day change in modeled discharge",
    "dlnq_3": "3-day change in modeled discharge",
    "dlnq_7": "7-day change in modeled discharge",
    "dlnq_14": "14-day change in modeled discharge",
    "dlnq_30": "30-day change in modeled discharge",
    "max7_rel": "recent 7-day peak of modeled discharge relative to today",
    "min7_rel": "recent 7-day low of modeled discharge relative to today",
    "up1_rel": "modeled discharge upstream ({up1}) relative to this point",
    "up1_d1": "1-day change in modeled discharge upstream ({up1})",
    "up1_d3": "3-day change in modeled discharge upstream ({up1})",
    "up1_d7": "7-day change in modeled discharge upstream ({up1})",
    "up2_rel": "modeled discharge upstream ({up2}) relative to this point",
    "up2_d1": "1-day change in modeled discharge upstream ({up2})",
    "up2_d3": "3-day change in modeled discharge upstream ({up2})",
    "up2_d7": "7-day change in modeled discharge upstream ({up2})",
    "rain_1": "basin rainfall over the last day (ERA5)",
    "rain_3": "basin rainfall over the last 3 days (ERA5)",
    "rain_7": "basin rainfall over the last 7 days (ERA5)",
    "rain_14": "basin rainfall over the last 14 days (ERA5)",
    "rain_30": "basin rainfall over the last 30 days (ERA5)",
    "rain_max7": "wettest basin point, 7-day rainfall (ERA5)",
    "temp_7": "upper-basin temperature, 7-day mean (ERA5, snowmelt proxy)",
    "temp_d14": "14-day change in upper-basin temperature (ERA5)",
    "doy_sin": "time of year",
    "doy_cos": "time of year",
    "monsoon": "monsoon season (June to September)",
    "station": "station-specific behaviour",
}
assert set(LABELS) == set(FEATURES)


@dataclass(frozen=True)
class DriverOut:
    feature: str
    label: str
    group: str
    contribution_m3s: float
    direction: str  # up | down


@dataclass(frozen=True)
class Explanation:
    drivers: tuple[DriverOut, ...]
    baseline_m3s: float
    raw_p50_m3s: float
    all_contributions: tuple[float, ...]
    top_group: str | None


def allocate(phi: np.ndarray, q_t: float) -> tuple[np.ndarray, float, float]:
    """``phi`` has shape ``(F + 1,)`` with the bias last. Returns ``(c_f, baseline, raw_p50)`` in
    m3/s (``raw_p50`` before clipping at 0)."""
    phi = np.asarray(phi, dtype="float64")
    contrib, bias = phi[:-1], float(phi[-1])
    anchor = max(q_t, 0.0) + 1.0
    base1 = anchor * math.exp(bias)
    s = float(np.sum(contrib))
    factor = base1 * (math.expm1(s) / s if s != 0.0 else 1.0)
    c = factor * contrib
    return c, base1 - 1.0, base1 * math.exp(s) - 1.0


def explain(
    phi: np.ndarray,
    q_t: float,
    names: Sequence[str] = FEATURES,
    upstream_names: Sequence[str] = (),
    top_k: int = TOP_K,
) -> Explanation:
    c, baseline, raw = allocate(phi, q_t)
    order = sorted(range(len(names)), key=lambda i: (-abs(float(c[i])), i))
    subs = {f"up{i + 1}": n for i, n in enumerate(upstream_names)}
    drivers = []
    for i in order[:top_k]:
        val = float(c[i])
        label = LABELS[names[i]]
        for key, n in subs.items():
            label = label.replace("{" + key + "}", n)
        drivers.append(
            DriverOut(
                feature=names[i],
                label=label,
                group=feature_group(names[i]),
                contribution_m3s=round(val, 3),
                direction="up" if val >= 0 else "down",
            )
        )
    by_group: dict[str, float] = {}
    for i, n in enumerate(names):
        g = feature_group(n)
        by_group[g] = by_group.get(g, 0.0) + abs(float(c[i]))
    top = max(sorted(by_group), key=lambda g: by_group[g]) if any(by_group.values()) else None
    return Explanation(
        drivers=tuple(drivers),
        baseline_m3s=round(max(baseline, 0.0), 3),
        raw_p50_m3s=raw,
        all_contributions=tuple(float(v) for v in c),
        top_group=top,
    )


def _fmt(x: float) -> str:
    return f"{x:,.0f}"


def narrative(
    *,
    station_label: str,
    peak_date: date,
    peak_lead: int,
    p50: float,
    lo: float,
    hi: float,
    coverage: float,
    expl: Explanation,
) -> str:
    """Template narrative. Uses only the numbers passed in."""
    parts = [
        f"Modeled river discharge (GloFAS via Open-Meteo) at the {station_label} peaks at lead "
        f"day {peak_lead} ({peak_date.isoformat()}) with a median of {_fmt(p50)} m3/s "
        f"({coverage:.0%} interval {_fmt(lo)} to {_fmt(hi)} m3/s).",
        f"For this starting level the model's average forecast is {_fmt(expl.baseline_m3s)} m3/s.",
    ]
    if expl.drivers:
        items = [
            f"{d.label} ({'+' if d.contribution_m3s >= 0 else '-'}"
            f"{_fmt(abs(d.contribution_m3s))} m3/s)"
            for d in expl.drivers[:3]
        ]
        parts.append("The largest drivers of the modeled median: " + "; ".join(items) + ".")
    if expl.top_group is not None:
        parts.append(f"The largest share comes from {GROUPS[expl.top_group]}.")
    parts.append(
        "These are statistical associations in a post-model of GloFAS output, not causal effects."
    )
    return " ".join(parts)
