"""Tool entry of library.search_guidance: delegates to the process-wide ``LibraryService``.

The retrieval logic itself is pure and lives in ``core/retrieve.py``; the service supplies the
store, models and calibration.
"""

from __future__ import annotations

from stitch_common.organs.library import SearchGuidanceIn, SearchGuidanceOut
from stitch_common.tooling import Outcome


def run(params: SearchGuidanceIn) -> Outcome[SearchGuidanceOut]:
    from stitch_library.service import get_service

    return get_service().search(params)
