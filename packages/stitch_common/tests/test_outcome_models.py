"""Outcome.models flows into Provenance.models (contract v0.4, additive)."""

from __future__ import annotations

import asyncio

from stitch_common.organs.library import SearchGuidanceIn, SearchGuidanceOut
from stitch_common.provenance import ModelInfo, build_provenance
from stitch_common.tooling import Outcome, run_tool

EMB = ModelInfo(name="emb", version="1", sha256="a" * 64)
RR = ModelInfo(name="rr", version="2", sha256="b" * 64)


def test_build_provenance_models_default_empty() -> None:
    prov = build_provenance(organ="library", tool="t", tool_version="0", inputs={}, mode="demo")
    assert prov.models == []


def test_outcome_models_reach_provenance() -> None:
    def core(params: SearchGuidanceIn) -> Outcome[SearchGuidanceOut]:
        return Outcome(SearchGuidanceOut(hits=[]), model=EMB, models=[EMB, RR])

    res = asyncio.run(run_tool("library", "search_guidance", "0", core, {"query": "water"}))
    assert res.ok
    assert res.provenance.model == EMB
    assert res.provenance.models == [EMB, RR]
