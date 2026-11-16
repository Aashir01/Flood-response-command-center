"""Briefing confidence (design section 11). A heuristic "strength of the evidence" score in
[0, 1], not a probability. Weights and penalties are judgement values (``confidence.yaml``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from stitch_brain.core.evidence import EvidenceStore

ORGANS = ("eyes", "oracle", "library", "ledger")


@dataclass(frozen=True)
class ConfidenceParams:
    weights: Mapping[str, float] = field(
        default_factory=lambda: {"eyes": 0.30, "oracle": 0.25, "library": 0.20, "ledger": 0.25}
    )
    unvalidated_factor: float = 0.7
    conflict_penalty: Mapping[str, float] = field(
        default_factory=lambda: {"flagged": 0.15, "escalated": 0.15, "reconciled": 0.05}
    )
    critic_failed_factor: float = 0.6
    removed_penalty: float = 0.05
    removed_cap: int = 4

    def __post_init__(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-9 or set(self.weights) != set(ORGANS):
            raise ValueError(f"confidence weights must cover {ORGANS} and sum to 1 (got {total})")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ConfidenceParams:
        return cls(
            weights=dict(raw["weights"]),
            unvalidated_factor=float(raw["unvalidated_factor"]),
            conflict_penalty=dict(raw["conflict_penalty"]),
            critic_failed_factor=float(raw["critic_failed_factor"]),
            removed_penalty=float(raw["removed_penalty"]),
            removed_cap=int(raw["removed_cap"]),
        )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def organ_confidences(
    store: EvidenceStore,
    library_nodes: Sequence[str],
    refused: int,
    params: ConfidenceParams,
    ledger_node: str = "ledger.final",
) -> dict[str, float]:
    c: dict[str, float] = dict.fromkeys(ORGANS, 0.0)
    seg = store.ok_node("eyes.segment")
    if seg is not None:
        conf = seg.data().get("confidence")
        v = float(conf) if conf is not None else 0.0
        if seg.data().get("validation", {}).get("validated_for_region") is False:
            v *= params.unvalidated_factor
        c["eyes"] = _clamp(v)
    fc = store.ok_node("oracle.forecast")
    if fc is not None:
        pts = fc.data().get("forecast") or []
        if pts:
            widths = [
                (float(p["discharge"]["p90"]) - float(p["discharge"]["p10"]))
                / max(float(p["discharge"]["p50"]), 1.0)
                for p in pts
            ]
            c["oracle"] = _clamp(1.0 - sum(widths) / len(widths))
    if library_nodes:
        answered = sum(
            1
            for n in library_nodes
            if (e := store.ok_node(n)) is not None and e.data().get("status") == "answered"
        )
        c["library"] = _clamp(answered / len(library_nodes))
    led = store.ok_node(ledger_node) or store.ok_node("ledger.optimize")
    if led is not None:
        status = led.data().get("status")
        gap = led.data().get("optimality_gap")
        if status == "optimal":
            c["ledger"] = 1.0
        elif status == "feasible":
            c["ledger"] = _clamp(1.0 - _clamp(float(gap or 0.0)))
    return c


def confidence(
    organ_conf: Mapping[str, float],
    resolutions: Sequence[str],
    critic_passed: bool,
    removed: int,
    params: ConfidenceParams | None = None,
) -> float:
    p = params or ConfidenceParams()
    c0 = sum(p.weights[o] * _clamp(organ_conf.get(o, 0.0)) for o in ORGANS)
    c1 = c0
    for r in resolutions:
        c1 *= 1.0 - p.conflict_penalty.get(r, 0.15)
    c2 = c1 * (p.critic_failed_factor if not critic_passed else 1.0)
    c3 = c2 * (1.0 - p.removed_penalty * min(removed, p.removed_cap))
    q = Decimal(repr(_clamp(c3))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return float(q)
