"""Core logic of library.answer_with_citations. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.library import AnswerWithCitationsIn, AnswerWithCitationsOut
from stitch_common.tooling import Outcome


def run(
    params: AnswerWithCitationsIn,
) -> AnswerWithCitationsOut | Outcome[AnswerWithCitationsOut]:
    """Implement answer_with_citations.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("library.answer_with_citations")
