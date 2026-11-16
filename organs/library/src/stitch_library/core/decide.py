"""Pure refusal decision (design section 8.1). Numbers in, verdict out.

Order: scope gate, evidence gate, quantity rule, conflict gate. Raising ``tau_evid`` or
``tau_scope`` can only turn an answer into a refusal, never the reverse (LIB-P10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RefusalReason = Literal["INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "CONFLICTING_EVIDENCE"]


@dataclass(frozen=True)
class Signals:
    scope_score: float
    evidence_score: float | None  # None when retrieval returned nothing
    quantity_query: bool = False
    quantity_supported: bool = True
    conflict: bool = False


@dataclass(frozen=True)
class Thresholds:
    tau_scope: float
    tau_evid: float


@dataclass(frozen=True)
class Verdict:
    proceed: bool
    reason: RefusalReason | None = None
    gate: str = "none"


def decide(sig: Signals, th: Thresholds) -> Verdict:
    if sig.scope_score < th.tau_scope:
        return Verdict(False, "OUT_OF_SCOPE", "scope")
    if sig.evidence_score is None or sig.evidence_score < th.tau_evid:
        return Verdict(False, "INSUFFICIENT_EVIDENCE", "evidence")
    if sig.quantity_query and not sig.quantity_supported:
        return Verdict(False, "INSUFFICIENT_EVIDENCE", "quantity")
    if sig.conflict:
        return Verdict(False, "CONFLICTING_EVIDENCE", "conflict")
    return Verdict(True)
