"""Registry of every organ tool and its input and output model."""

from __future__ import annotations

from typing import NamedTuple

from stitch_common.base import Contract
from stitch_common.organs import eyes, ledger, library, oracle, voice


class ToolSpec(NamedTuple):
    input: type[Contract]
    output: type[Contract]


ORGAN_TOOLS: dict[str, dict[str, ToolSpec]] = {
    "eyes": {
        "segment_flood": ToolSpec(eyes.SegmentFloodIn, eyes.SegmentFloodOut),
        "compare_with_permanent_water": ToolSpec(
            eyes.CompareWithPermanentWaterIn, eyes.CompareWithPermanentWaterOut
        ),
    },
    "oracle": {
        "forecast_river": ToolSpec(oracle.ForecastRiverIn, oracle.ForecastRiverOut),
        "explain_forecast": ToolSpec(oracle.ExplainForecastIn, oracle.ExplainForecastOut),
    },
    "library": {
        "search_guidance": ToolSpec(library.SearchGuidanceIn, library.SearchGuidanceOut),
        "answer_with_citations": ToolSpec(
            library.AnswerWithCitationsIn, library.AnswerWithCitationsOut
        ),
    },
    "ledger": {
        "optimize_allocation": ToolSpec(ledger.OptimizeAllocationIn, ledger.OptimizeAllocationOut),
        "sensitivity_report": ToolSpec(ledger.SensitivityReportIn, ledger.SensitivityReportOut),
    },
    "voice": {
        "transcribe": ToolSpec(voice.TranscribeIn, voice.TranscribeOut),
        "speak": ToolSpec(voice.SpeakIn, voice.SpeakOut),
    },
}

__all__ = ["ORGAN_TOOLS", "ToolSpec"]
