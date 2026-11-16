"""Core logic of ledger.sensitivity_report. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.ledger import SensitivityReportIn, SensitivityReportOut
from stitch_common.tooling import Outcome


def run(
    params: SensitivityReportIn,
) -> SensitivityReportOut | Outcome[SensitivityReportOut]:
    """Implement sensitivity_report.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("ledger.sensitivity_report")
