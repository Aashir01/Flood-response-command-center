"""Shared Hypothesis strategies and test doubles for the Brain tests (``brain_testkit``)."""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

json_scalars = st.none() | st.booleans() | st.integers(-(10**9), 10**9) | st.text(max_size=8)
json_keys = st.text(
    alphabet=st.sampled_from(list("ab/~0 1é漢")) | st.characters(codec="utf-8"),
    max_size=6,
)


def recorded_registry(**settings_kw: Any) -> Any:
    from stitch_brain.runtime.registry import OrganRegistry
    from stitch_brain.settings import Settings

    settings = Settings(recorded_organs=("all",), **settings_kw)
    return OrganRegistry.build(settings, None)


async def run_briefing(
    scenario: str = "demo-sindh-2022",
    lang: str = "en",
    *,
    registry: Any = None,
    clock: Any = None,
    briefing_id: str = "00000000-0000-4000-8000-000000000001",
    mode: str = "demo",
    **runner_kw: Any,
) -> Any:
    from stitch_brain.config import load_scenarios
    from stitch_brain.runtime.runner import BriefingRunner
    from stitch_common.brain_api import BriefingRequest

    reg = registry or recorded_registry()
    sc = load_scenarios()[scenario]
    req = BriefingRequest(region=sc.region, scenario=scenario, lang=lang, mode=mode)  # type: ignore[arg-type]
    events: list[Any] = []
    runner = BriefingRunner(reg, clock=clock, **runner_kw)
    result = await runner.run(req, briefing_id, events.append)
    result.events = events
    return result


def all_claims(briefing: Any) -> list[Any]:
    return [c for s in briefing.sections for c in s.claims]


def json_docs(max_leaves: int = 20) -> st.SearchStrategy[Any]:
    return st.recursive(
        json_scalars | st.floats(allow_nan=False, allow_infinity=False),
        lambda children: (
            st.lists(children, max_size=4) | st.dictionaries(json_keys, children, max_size=4)
        ),
        max_leaves=max_leaves,
    )
