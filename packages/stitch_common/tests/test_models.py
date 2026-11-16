"""BOOT-R2.1 and BOOT-P4: models build from valid fixtures, reject bad ones, round-trip schemas."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from stitch_common.base import Contract
from stitch_common.brain import Briefing, TaskEvent
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.organs.ledger import ScenarioDistrict
from stitch_common.organs.library import AnswerWithCitationsOut
from stitch_common.organs.voice import SpeakOut, TranscribeIn
from stitch_common.schemas import all_schemas
from stitch_common.testing.examples import (
    BRIEFING,
    CITATION,
    PROVENANCE,
    RESOURCE_EXAMPLES,
    TASK_EVENT,
    TOOL_EXAMPLES,
)
from stitch_common.types import Citation, Interval

SCHEMAS = all_schemas()
CASES = [
    (f"{organ}.{tool}", spec.input, spec.output)
    for organ, tools in ORGAN_TOOLS.items()
    for tool, spec in tools.items()
]


def _validate(schema_name: str, payload: Any) -> None:
    Draft202012Validator(SCHEMAS[schema_name]).validate(payload)


def test_every_tool_has_an_example() -> None:
    assert {c[0] for c in CASES} == set(TOOL_EXAMPLES)
    assert len(CASES) == 10


@pytest.mark.parametrize(("key", "in_model", "out_model"), CASES, ids=[c[0] for c in CASES])
def test_examples_build_and_round_trip_through_schema(
    key: str, in_model: type[Contract], out_model: type[Contract]
) -> None:
    in_payload, out_payload = TOOL_EXAMPLES[key]
    inp = in_model.model_validate(in_payload)
    out = out_model.model_validate(out_payload)
    _validate(f"{key}.in.json", inp.model_dump(mode="json"))
    _validate(f"{key}.out.json", out.model_dump(mode="json"))
    # The raw fixtures must validate against the schemas too (schema and model agree).
    _validate(f"{key}.in.json", in_payload)
    _validate(f"{key}.out.json", out_payload)
    assert out_model.model_validate_json(out.model_dump_json()) == out


@pytest.mark.parametrize(("key", "in_model", "out_model"), CASES, ids=[c[0] for c in CASES])
def test_unknown_fields_rejected(
    key: str, in_model: type[Contract], out_model: type[Contract]
) -> None:
    in_payload, out_payload = TOOL_EXAMPLES[key]
    with pytest.raises(ValidationError):
        in_model.model_validate({**in_payload, "bogus": 1})
    with pytest.raises(ValidationError):
        out_model.model_validate({**out_payload, "bogus": 1})
    assert SCHEMAS[f"{key}.in.json"]["additionalProperties"] is False


def test_other_models_build() -> None:
    Briefing.model_validate(BRIEFING)
    TaskEvent.model_validate(TASK_EVENT)
    ScenarioDistrict.model_validate(RESOURCE_EXAMPLES["ledger.resource.districts.json"])
    _validate("brain.briefing.json", Briefing.model_validate(BRIEFING).model_dump(mode="json"))
    _validate("brain.task_event.json", TaskEvent.model_validate(TASK_EVENT).model_dump(mode="json"))
    _validate("common.provenance.json", PROVENANCE)
    _validate("common.citation.json", CITATION)


def _mut(key: str, side: int, path: list[Any], value: Any) -> dict[str, Any]:
    payload = copy.deepcopy(TOOL_EXAMPLES[key][side])
    node: Any = payload
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    return payload


BAD_INPUTS = [
    ("eyes.segment_flood", ["region_id"], "Not A Slug"),
    ("eyes.segment_flood", ["tile_size"], 0),
    ("eyes.segment_flood", ["bbox"], [70, 20, 60, 30]),
    ("oracle.forecast_river", ["horizon_days"], 15),
    ("oracle.forecast_river", ["horizon_days"], 0),
    ("oracle.forecast_river", ["coverage"], 1.0),
    ("library.search_guidance", ["top_k"], 21),
    ("library.search_guidance", ["lang"], "fr"),
    ("ledger.optimize_allocation", ["equity_floor"], 1.5),
    ("ledger.optimize_allocation", ["on_infeasible_floor"], "ignore"),
    ("ledger.optimize_allocation", ["min_road_access"], -0.1),
    ("ledger.optimize_allocation", ["districts", 0, "severity"], 1.1),
    ("ledger.optimize_allocation", ["districts", 0, "population_affected"], -1),
    ("ledger.optimize_allocation", ["districts", 0, "unit_cost_multiplier"], 0),
    ("ledger.optimize_allocation", ["commodities", 0, "per_person_need"], 0),
    ("ledger.optimize_allocation", ["supply"], {"water": 5.0}),
    ("ledger.optimize_allocation", ["supply"], {"food": -1.0}),
    ("ledger.optimize_allocation", ["commodities"], []),
    ("ledger.sensitivity_report", ["floor_steps"], 1),
    ("ledger.sensitivity_report", ["floor_steps"], 22),
    ("voice.transcribe", ["format"], "flac"),
    ("voice.transcribe", ["audio_b64"], "not base64 !!"),
    ("voice.speak", ["text"], "x" * 4001),
    ("voice.speak", ["lang"], "fr"),
]


@pytest.mark.parametrize(("key", "path", "value"), BAD_INPUTS)
def test_bad_inputs_rejected(key: str, path: list[Any], value: Any) -> None:
    spec = ORGAN_TOOLS[key.split(".")[0]][key.split(".")[1]]
    with pytest.raises(ValidationError):
        spec.input.model_validate(_mut(key, 0, path, value))


BAD_OUTPUTS = [
    ("eyes.segment_flood", ["confidence"], 1.2),
    ("eyes.segment_flood", ["reference_overlay_geojson"], {"type": "Feature"}),
    ("oracle.forecast_river", ["target_kind"], "gauge"),
    ("oracle.forecast_river", ["forecast", 0, "discharge"], {"p10": 3, "p50": 2, "p90": 1}),
    ("oracle.forecast_river", ["forecast"], []),
    ("oracle.forecast_river", ["unit"], "m3"),
    ("oracle.forecast_river", ["exceedance_prob", 0, "p_exceed"], 1.5),
    ("ledger.optimize_allocation", ["status"], "infeasible"),  # needs infeasibility_reason
    ("ledger.optimize_allocation", ["coverage", 0, "access_mode"], "helicopter"),
    ("ledger.optimize_allocation", ["allocation", 0, "quantity"], -1),
    ("ledger.optimize_allocation", ["equity", "floor_applied"], 0.9),
    ("ledger.sensitivity_report", ["basis"], "simplex"),
    ("ledger.sensitivity_report", ["shadow_prices", 0, "constraint"], "bogus"),
    ("ledger.sensitivity_report", ["equity_tradeoff", 0, "total_coverage"], None),
    ("ledger.sensitivity_report", ["equity_tradeoff", 1, "total_coverage"], 5.0),
    ("voice.speak", ["provider"], "polly"),
    ("voice.speak", ["synthesized"], "magic"),
    ("voice.transcribe", ["segments", 0, "end"], -1.0),
]


@pytest.mark.parametrize(("key", "path", "value"), BAD_OUTPUTS)
def test_bad_outputs_rejected(key: str, path: list[Any], value: Any) -> None:
    spec = ORGAN_TOOLS[key.split(".")[0]][key.split(".")[1]]
    with pytest.raises(ValidationError):
        spec.output.model_validate(_mut(key, 1, path, value))


def test_voice_provider_enum_is_exact() -> None:
    for provider in ["azure", "google", "prerendered", "local-mms", "fake"]:
        SpeakOut.model_validate({**TOOL_EXAMPLES["voice.speak"][1], "provider": provider})


def test_voice_audio_size_limit() -> None:
    import base64

    big = base64.b64encode(b"\0" * 10_000_001).decode()
    with pytest.raises(ValidationError):
        TranscribeIn(audio_b64=big, format="wav")


def _answer(**over: Any) -> dict[str, Any]:
    return {**TOOL_EXAMPLES["library.answer_with_citations"][1], **over}


refusal = {"reason": "INSUFFICIENT_EVIDENCE", "closest_hits": [CITATION]}


@pytest.mark.parametrize(
    "payload",
    [
        _answer(citations=[]),
        _answer(answer=None),
        _answer(claims=[]),
        _answer(claims=[{"text": "x", "citation_idx": []}]),
        _answer(claims=[{"text": "x", "citation_idx": [1]}]),
        _answer(refusal=refusal),
        _answer(status="refused"),
        _answer(status="refused", refusal=refusal),
        _answer(status="refused", answer=None, citations=[], claims=[], refusal=None),
    ],
)
def test_library_invariant_violations(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AnswerWithCitationsOut.model_validate(payload)


def test_library_refusal_ok() -> None:
    out = AnswerWithCitationsOut.model_validate(
        _answer(status="refused", answer=None, citations=[], claims=[], refusal=refusal)
    )
    assert out.refusal is not None


def test_brain_invariants() -> None:
    bad_claim = copy.deepcopy(BRIEFING)
    bad_claim["sections"][0]["claims"][0]["evidence"] = []
    with pytest.raises(ValidationError):
        Briefing.model_validate(bad_claim)
    dup = copy.deepcopy(BRIEFING)
    dup["sections"].append(copy.deepcopy(dup["sections"][0]))
    with pytest.raises(ValidationError):
        Briefing.model_validate(dup)
    ptr = copy.deepcopy(BRIEFING)
    ptr["sections"][0]["claims"][0]["evidence"][0]["json_pointer"] = "data/x"
    with pytest.raises(ValidationError):
        Briefing.model_validate(ptr)
    with pytest.raises(ValidationError):
        TaskEvent.model_validate({**TASK_EVENT, "event": "nope"})
    with pytest.raises(ValidationError):
        Briefing.model_validate({**BRIEFING, "confidence": 2})


# --- BOOT-P4 with Hypothesis -----------------------------------------------
finite = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6)
text = st.text(max_size=20)


def _round_trip(model: BaseModel, schema_name: str) -> None:
    dumped = model.model_dump(mode="json")
    _validate(schema_name, dumped)
    assert type(model).model_validate(dumped) == model


@given(st.lists(finite, min_size=3, max_size=3).map(sorted))
def test_p4_interval_round_trip(xs: list[float]) -> None:
    _round_trip(Interval(p10=xs[0], p50=xs[1], p90=xs[2]), "common.interval.json")


@given(
    page=st.integers(min_value=1, max_value=10_000),
    start=st.integers(min_value=0, max_value=1000),
    length=st.integers(min_value=0, max_value=1000),
    quote=st.text(max_size=400),
    lang=st.sampled_from(["en", "ur"]),
    url=st.none() | st.just("https://example.org/doc.pdf"),
)
def test_p4_citation_round_trip(
    page: int, start: int, length: int, quote: str, lang: str, url: str | None
) -> None:
    c = Citation.model_validate(
        {
            **CITATION,
            "page": page,
            "span": [start, start + length],
            "quote": quote,
            "lang": lang,
            "url": url,
        }
    )
    _round_trip(c, "common.citation.json")


@given(
    st.dictionaries(
        st.sampled_from(["food", "water", "shelter"]), st.floats(min_value=0, max_value=1e6)
    ),
    st.floats(min_value=0.0, max_value=1.0),
    st.booleans(),
)
def test_p4_ledger_input_round_trip(supply: dict[str, float], floor: float, integer: bool) -> None:
    key = "ledger.optimize_allocation"
    base = copy.deepcopy(TOOL_EXAMPLES[key][0])
    base["commodities"] = [
        {"id": i, "name": i, "unit": "u", "unit_cost": 1.0, "per_person_need": 1.0}
        for i in ["food", "water", "shelter"]
    ]
    base.update(supply=supply, equity_floor=floor, integer=integer)
    spec = ORGAN_TOOLS["ledger"]["optimize_allocation"]
    _round_trip(spec.input.model_validate(base), f"{key}.in.json")
