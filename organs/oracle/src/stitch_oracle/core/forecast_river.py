"""Core logic of oracle.forecast_river. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.oracle import ForecastRiverIn, ForecastRiverOut
from stitch_common.tooling import Outcome


def run(
    params: ForecastRiverIn,
) -> ForecastRiverOut | Outcome[ForecastRiverOut]:
    """Implement forecast_river.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("oracle.forecast_river")
