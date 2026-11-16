"""Tool entry of library.answer_with_citations: delegates to the process-wide ``LibraryService``.

The decision, generation and verification logic is pure and lives in ``core/decide.py``,
``core/context.py``, ``core/extractive.py`` and ``core/answer.py``.
"""

from __future__ import annotations

from stitch_common.organs.library import AnswerWithCitationsIn, AnswerWithCitationsOut
from stitch_common.tooling import Outcome


def run(params: AnswerWithCitationsIn) -> Outcome[AnswerWithCitationsOut]:
    from stitch_library.service import get_service

    return get_service().answer(params)
