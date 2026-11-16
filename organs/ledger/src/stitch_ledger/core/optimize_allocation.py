"""Core logic of ledger.optimize_allocation. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.ledger import OptimizeAllocationIn, OptimizeAllocationOut
from stitch_common.tooling import Outcome


def run(
    params: OptimizeAllocationIn,
) -> OptimizeAllocationOut | Outcome[OptimizeAllocationOut]:
    """Implement optimize_allocation.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("ledger.optimize_allocation")
