"""Core logic of library.search_guidance. Pure: inputs in, output out, no I/O."""

from __future__ import annotations

from stitch_common.organs.library import SearchGuidanceIn, SearchGuidanceOut
from stitch_common.tooling import Outcome


def run(
    params: SearchGuidanceIn,
) -> SearchGuidanceOut | Outcome[SearchGuidanceOut]:
    """Implement search_guidance.

    Raise ``stitch_common.tooling.ToolFailure(code, message, retryable)`` for expected failures.
    Return ``Outcome(data, warnings=[...], data_sources=[...])`` to add provenance details.
    """
    raise NotImplementedError("library.search_guidance")
