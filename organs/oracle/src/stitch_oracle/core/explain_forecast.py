"""Core logic of oracle.explain_forecast. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.oracle import ExplainForecastIn, ExplainForecastOut
from stitch_common.tooling import Outcome


def run(
    params: ExplainForecastIn,
) -> ExplainForecastOut | Outcome[ExplainForecastOut]:
    """Implement explain_forecast.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("oracle.explain_forecast")
