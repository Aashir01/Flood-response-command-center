"""Contract v0.4: every new field has a valid fixture and at least one invalid fixture.

All v0.4 changes are additive, so the v0.3-shaped ``TOOL_EXAMPLES`` must keep validating (that is
asserted in ``test_models.py``) and the overlays below must validate on top of them.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from stitch_common import CONTRACT_VERSION
from stitch_common.brain import Briefing, TaskEvent
from stitch_common.brain_api import (
    API_MODELS,
    EVENT_PAYLOADS,
    ApiError,
    AskResponse,
    BriefingAccepted,
    BriefingRequest,
    BriefingState,
    CriticPayload,
    OrganList,
    SpeakRequest,
    VoiceOrganMeta,
    format_sse_frame,
    validate_event_payload,
)
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.organs.eyes import SceneInfo
from stitch_common.organs.library import AnswerWithCitationsOut
from stitch_common.organs.oracle import StationInfo
from stitch_common.provenance import Provenance
from stitch_common.schemas import all_schemas
from stitch_common.testing.examples import (
    BRIEFING,
    CITATION,
    EVIDENCE,
    PROVENANCE,
    TASK_EVENT,
    TOOL_EXAMPLES,
    V04_IN,
    V04_OUT,
    V04_RESOURCES,
)

SCHEMAS = all_schemas()


def _spec(key: str) -> Any:
    organ, tool = key.split(".")
    return ORGAN_TOOLS[organ][tool]


def test_version_is_04() -> None:
    assert CONTRACT_VERSION == "0.4"
    assert PROVENANCE["contract_version"] == "0.4"


@pytest.mark.parametrize("key", sorted(V04_IN))
def test_v04_inputs_valid(key: str) -> None:
    payload = {**TOOL_EXAMPLES[key][0], **V04_IN[key]}
    model = _spec(key).input.model_validate(payload)
    Draft202012Validator(SCHEMAS[f"{key}.in.json"]).validate(payload)
    assert model.model_dump(mode="json", exclude_none=True)  # round trips below
    assert type(model).model_validate(model.model_dump(mode="json")) == model


@pytest.mark.parametrize("key", sorted(V04_OUT))
def test_v04_outputs_valid(key: str) -> None:
    payload = {**TOOL_EXAMPLES[key][1], **V04_OUT[key]}
    model = _spec(key).output.model_validate(payload)
    Draft202012Validator(SCHEMAS[f"{key}.out.json"]).validate(model.model_dump(mode="json"))
    assert type(model).model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize(
    "key",
    [
        "eyes.segment_flood",
        "eyes.compare_with_permanent_water",
        "oracle.forecast_river",
        "ledger.optimize_allocation",
    ],
)
def test_mode_input_values(key: str) -> None:
    base = TOOL_EXAMPLES[key][0]
    for good in ("demo", "live"):
        _spec(key).input.model_validate({**base, "mode": good})
    with pytest.raises(ValidationError):
        _spec(key).input.model_validate({**base, "mode": "recorded"})
    # omitted mode stays valid and the field is not required in the schema
    assert "mode" not in SCHEMAS[f"{key}.in.json"].get("required", [])


@pytest.mark.parametrize("tool", ["explain_forecast"])
def test_run_id_tools_take_no_mode(tool: str) -> None:
    with pytest.raises(ValidationError):
        ORGAN_TOOLS["oracle"][tool].input.model_validate({"run_id": "r1", "mode": "demo"})
    with pytest.raises(ValidationError):
        ORGAN_TOOLS["ledger"]["sensitivity_report"].input.model_validate(
            {"run_id": "r1", "mode": "demo"}
        )


def _mut(key: str, field_path: list[Any], value: Any, side: int = 1, v04: bool = True) -> Any:
    base = {**TOOL_EXAMPLES[key][side], **(V04_OUT if side else V04_IN).get(key, {})}
    payload = copy.deepcopy(base) if v04 else copy.deepcopy(TOOL_EXAMPLES[key][side])
    node: Any = payload
    for p in field_path[:-1]:
        node = node[p]
    node[field_path[-1]] = value
    return payload


BAD_V04_IN = [
    ("library.answer_with_citations", ["answer_lang"], "auto"),
    ("library.answer_with_citations", ["answer_lang"], "fr"),
    ("library.search_guidance", ["filters", "lang"], ["fr"]),
    ("library.search_guidance", ["filters", "doc_id"], "ndma"),
]


@pytest.mark.parametrize(("key", "path", "value"), BAD_V04_IN)
def test_v04_bad_inputs_rejected(key: str, path: list[Any], value: Any) -> None:
    payload = {**TOOL_EXAMPLES[key][0], **V04_IN[key]}
    node: Any = payload
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    with pytest.raises(ValidationError):
        _spec(key).input.model_validate(payload)


BAD_V04_OUT = [
    ("eyes.segment_flood", ["confidence"], 1.5),
    ("eyes.segment_flood", ["valid_fraction"], 1.1),
    ("eyes.segment_flood", ["valid_fraction"], -0.1),
    ("eyes.segment_flood", ["model_variant"], "unet-resnet50"),
    ("eyes.segment_flood", ["reference_overlay_note"], 5),
    ("eyes.compare_with_permanent_water", ["by_district", 0, "district_area_km2"], -1.0),
    ("eyes.compare_with_permanent_water", ["by_district", 0, "flooded_roads_km"], -0.5),
    ("oracle.forecast_river", ["calibration", "interval_lower_q"], 1.2),
    ("oracle.forecast_river", ["calibration", "interval_upper_q"], -0.1),
    ("oracle.forecast_river", ["station", "cell_lat"], 91.0),
    ("oracle.forecast_river", ["station", "cell_lon"], 181.0),
    ("oracle.forecast_river", ["station"], {"name": "x"}),
    ("oracle.forecast_river", ["quantile_correction_applied"], "maybe"),
    ("oracle.explain_forecast", ["lead_days_explained"], -1),
    ("oracle.explain_forecast", ["drivers", 0, "feature_group"], 3),
    ("library.search_guidance", ["hits", 0, "span"], [10, 2]),
    ("library.search_guidance", ["hits", 0, "span"], [-1, 2]),
    ("library.search_guidance", ["hits", 0, "chunk_id"], 7),
    ("library.answer_with_citations", ["generation", "mode"], "template"),
    ("library.answer_with_citations", ["generation"], {"mode": "llm"}),
    ("library.answer_with_citations", ["quantities", 0, "claim_idx"], 1),  # one claim only
    ("library.answer_with_citations", ["quantities", 0, "claim_idx"], -1),
    ("library.answer_with_citations", ["quantities", 0, "unit"], ""),
    ("voice.speak", ["voice"], 5),
]


@pytest.mark.parametrize(("key", "path", "value"), BAD_V04_OUT)
def test_v04_bad_outputs_rejected(key: str, path: list[Any], value: Any) -> None:
    with pytest.raises(ValidationError):
        _spec(key).output.model_validate(_mut(key, path, value))


def test_eyes_confidence_may_be_null() -> None:
    out = _spec("eyes.segment_flood").output.model_validate(
        {**TOOL_EXAMPLES["eyes.segment_flood"][1], "confidence": None, "flood_extent_km2": 0.0}
    )
    assert out.confidence is None
    Draft202012Validator(SCHEMAS["eyes.segment_flood.out.json"]).validate(
        out.model_dump(mode="json")
    )


def test_confidence_is_still_required_key() -> None:
    payload = copy.deepcopy(TOOL_EXAMPLES["eyes.segment_flood"][1])
    del payload["confidence"]
    with pytest.raises(ValidationError):
        _spec("eyes.segment_flood").output.model_validate(payload)


def test_refused_answer_has_no_quantities() -> None:
    refusal = {"reason": "INSUFFICIENT_EVIDENCE", "closest_hits": [CITATION]}
    refused = {
        "status": "refused",
        "answer": None,
        "citations": [],
        "claims": [],
        "refusal": refusal,
    }
    AnswerWithCitationsOut.model_validate(refused)
    AnswerWithCitationsOut.model_validate({**refused, "generation": None})
    with pytest.raises(ValidationError):
        AnswerWithCitationsOut.model_validate(
            {**refused, "quantities": [{"value": 1, "unit": "l", "per": None, "claim_idx": 0}]}
        )


def test_provenance_models_list() -> None:
    assert Provenance.model_validate(PROVENANCE).models == []
    model = {"name": "bge-small", "version": "1", "sha256": "ab"}
    p = Provenance.model_validate({**PROVENANCE, "models": [model, {**model, "name": "rerank"}]})
    assert [m.name for m in p.models] == ["bge-small", "rerank"]
    Draft202012Validator(SCHEMAS["common.provenance.json"]).validate(p.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        Provenance.model_validate({**PROVENANCE, "models": [{"name": "x"}]})
    with pytest.raises(ValidationError):
        Provenance.model_validate({**PROVENANCE, "models": "bge"})


@pytest.mark.parametrize("name", sorted(V04_RESOURCES))
def test_v04_resources(name: str) -> None:
    model = {"oracle.resource.stations.json": StationInfo, "eyes.resource.scenes.json": SceneInfo}[
        name
    ]
    built = model.model_validate(V04_RESOURCES[name])
    Draft202012Validator(SCHEMAS[name]).validate(built.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        model.model_validate({**V04_RESOURCES[name], "bogus": 1})


def test_station_resource_invalid() -> None:
    with pytest.raises(ValidationError):
        StationInfo.model_validate(
            {**V04_RESOURCES["oracle.resource.stations.json"], "cell_lat": 100}
        )
    bad = {**V04_RESOURCES["oracle.resource.stations.json"]}
    del bad["as_of_max"]
    with pytest.raises(ValidationError):
        StationInfo.model_validate(bad)
    with pytest.raises(ValidationError):
        SceneInfo.model_validate(
            {**V04_RESOURCES["eyes.resource.scenes.json"], "region_id": "Not A Slug"}
        )


# --- brain models ------------------------------------------------------------------------------
def _briefing_v04() -> dict[str, Any]:
    b = copy.deepcopy(BRIEFING)
    b["sections"][0]["claims"][0]["labels"] = ["modeled", "demo"]
    b["sections"][0]["missing"] = ["eyes"]
    b["conflicts"][0].update(rule_id="R1", status="final", subjects=["d1"])
    b["organs"] = [
        {"organ": "eyes", "status": "ready", "served_by": "recorded"},
        {"organ": "voice", "status": "disabled"},
    ]
    b["disclaimer"] = "Decision support demo, not an operational warning system."
    return b


def test_briefing_v03_still_valid_and_defaults() -> None:
    b = Briefing.model_validate(BRIEFING)
    assert b.organs == []
    assert b.disclaimer is None
    assert b.sections[0].missing == []
    assert b.sections[0].claims[0].labels == []
    assert b.conflicts[0].rule_id is None
    assert b.conflicts[0].subjects == []


def test_briefing_v04_fields() -> None:
    b = Briefing.model_validate(_briefing_v04())
    Draft202012Validator(SCHEMAS["brain.briefing.json"]).validate(b.model_dump(mode="json"))
    assert Briefing.model_validate_json(b.model_dump_json()) == b


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["sections"][0]["claims"][0].update(labels=["live"]),
        lambda b: b["sections"][0]["claims"][0].update(labels="modeled"),
        lambda b: b["sections"][0].update(missing="eyes"),
        lambda b: b["conflicts"][0].update(status="open"),
        lambda b: b["conflicts"][0].update(subjects="d1"),
        lambda b: b["organs"][0].update(status="broken"),
        lambda b: b["organs"][0].update(served_by="llm"),
        lambda b: b["organs"][0].update(organ="brain"),
        lambda b: b.update(disclaimer=3),
    ],
)
def test_briefing_v04_invalid(mutate: Any) -> None:
    b = _briefing_v04()
    mutate(b)
    with pytest.raises(ValidationError):
        Briefing.model_validate(b)


def test_notice_event() -> None:
    ev = TaskEvent.model_validate(
        {
            **TASK_EVENT,
            "event": "notice",
            "organ": None,
            "tool": None,
            "payload": {"code": "MODE_FALLBACK", "message": "live unavailable, using demo"},
        }
    )
    assert isinstance(validate_event_payload(ev), EVENT_PAYLOADS["notice"])
    with pytest.raises(ValidationError):
        TaskEvent.model_validate({**TASK_EVENT, "event": "warning"})


# --- brain_api ---------------------------------------------------------------------------------
NOW = "2026-01-01T00:00:00Z"
RESULT_OK = {
    "ok": True,
    "attempt": 1,
    "duration_ms": 12.5,
    "served_by": "real",
    "run_id": "r1",
    "mode": "demo",
    "warnings": [],
    "summary": {"status": "optimal"},
}


def _ev(event: str, payload: dict[str, Any], **kw: Any) -> TaskEvent:
    return TaskEvent.model_validate(
        {"event": event, "ts": NOW, "task_id": kw.get("task_id", "n1"), "payload": payload}
    )


def test_event_payload_models() -> None:
    plan = {
        "plan_id": "p1",
        "revision": 0,
        "planner": "static",
        "scenario": "demo-sindh-2022",
        "lang": "en",
        "mode_requested": "demo",
        "stub_organs": ["eyes"],
        "nodes": [
            {
                "id": "ledger.opt",
                "kind": "organ",
                "organ": "ledger",
                "tool": "optimize_allocation",
                "deps": [],
                "optional": False,
            }
        ],
    }
    call = {
        "attempt": 1,
        "max_attempts": 2,
        "timeout_s": 20,
        "served_by": "recorded",
        "started_at": NOW,
    }
    critic = {"pass": 1, "passed": True, "issues": [], "removed": [], "reverted": []}
    cases = {
        "plan": plan,
        "organ_call": call,
        "organ_result": RESULT_OK,
        "conflict": _briefing_v04()["conflicts"][0],
        "critic": critic,
        "briefing": _briefing_v04(),
        "error": {"code": "TIMEOUT", "message": "x", "fatal": False, "retryable": True},
        "notice": {"code": "MODE_FALLBACK", "message": "x"},
    }
    assert set(cases) == set(EVENT_PAYLOADS)
    for name, payload in cases.items():
        validate_event_payload(_ev(name, payload))


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("organ_result", {**RESULT_OK, "ok": False}),  # failed call needs an error
        (
            "organ_result",
            {**RESULT_OK, "error": {"code": "TIMEOUT", "message": "x", "retryable": True}},
        ),  # ok with error
        ("organ_result", {**RESULT_OK, "summary": {f"k{i}": i for i in range(11)}}),
        ("organ_result", {**RESULT_OK, "summary": {"nested": {"a": 1}}}),
        ("organ_result", {**RESULT_OK, "served_by": "brain"}),
        ("organ_result", {**RESULT_OK, "duration_ms": -1}),
        (
            "organ_call",
            {
                "attempt": 0,
                "max_attempts": 1,
                "timeout_s": 5,
                "served_by": "real",
                "started_at": NOW,
            },
        ),
        ("critic", {"pass": 0, "passed": True}),
        ("error", {"code": "X", "message": "m"}),  # fatal is required
        ("notice", {"code": "X"}),
    ],
)
def test_event_payload_invalid(event: str, payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_event_payload(_ev(event, payload))


def test_critic_payload_alias() -> None:
    p = CriticPayload.model_validate({"pass": 2, "passed": False})
    assert p.pass_no == 2
    assert p.model_dump(by_alias=True)["pass"] == 2
    assert "pass" in SCHEMAS["brain_api.payload_critic.json"]["properties"]


def test_sse_frame_format() -> None:
    frame = format_sse_frame(3, _ev("notice", {"code": "A", "message": "b"}))
    lines = frame.split("\n")
    assert lines[0] == "id: 3"
    assert lines[1] == "event: notice"
    assert lines[2].startswith('data: {"event":"notice"')
    assert frame.endswith("\n\n")
    with pytest.raises(ValueError):
        format_sse_frame(0, _ev("notice", {"code": "A", "message": "b"}))


def test_briefing_request_and_accepted() -> None:
    req = BriefingRequest.model_validate({"region": "pk-sindh", "scenario": "demo-sindh-2022"})
    assert (req.lang, req.mode) == ("en", "demo")
    for bad in (
        {"region": "Not A Slug"},
        {"region": "x" * 65},
        {"lang": "fr"},
        {"mode": "x"},
        {"bogus": 1},
    ):
        with pytest.raises(ValidationError):
            BriefingRequest.model_validate({"region": "pk-sindh", "scenario": "s", **bad})
    acc = BriefingAccepted.model_validate(
        {"briefing_id": "b1", "events_url": "/briefings/b1/events", "result_url": "/briefings/b1"}
    )
    assert acc.status == "running"
    with pytest.raises(ValidationError):
        BriefingAccepted.model_validate({**acc.model_dump(), "status": "done"})


def test_briefing_state() -> None:
    state = {
        "briefing_id": "b1",
        "status": "done",
        "request": {"region": "pk-sindh", "scenario": "s"},
        "created_at": NOW,
        "finished_at": NOW,
        "briefing": BRIEFING,
    }
    BriefingState.model_validate(state)
    with pytest.raises(ValidationError):
        BriefingState.model_validate({**state, "status": "queued"})
    with pytest.raises(ValidationError):
        BriefingState.model_validate({**state, "created_at": "2026-01-01T00:00:00"})  # naive


def test_organ_list() -> None:
    doc = {
        "organs": [
            {
                "organ": "voice",
                "status": "ready",
                "served_by": "real",
                "tools": ["speak"],
                "meta": VoiceOrganMeta(
                    capabilities=["speak"], tts_provider="azure", hosted=True
                ).model_dump(),
            },
            {
                "organ": "eyes",
                "status": "incompatible",
                "compat": "incompatible",
                "reason": "schema",
            },
        ],
        "live_available": False,
        "default_mode": "demo",
        "brain_version": "0.1.0",
        "contract_version": CONTRACT_VERSION,
    }
    OrganList.model_validate(doc)
    for bad in ({"live_available": "maybe"}, {"default_mode": "x"}, {"mode_default": "demo"}):
        with pytest.raises(ValidationError):
            OrganList.model_validate({**doc, **bad})
    with pytest.raises(ValidationError):
        VoiceOrganMeta.model_validate(
            {"capabilities": ["sing"], "tts_provider": "x", "hosted": False}
        )


def test_speak_request_exactly_one_source() -> None:
    SpeakRequest.model_validate({"briefing_id": "b1", "lang": "ur"})
    SpeakRequest.model_validate({"text": "hello", "lang": "en", "voice": "v", "format": "mp3"})
    for bad in (
        {"lang": "en"},
        {"briefing_id": "b1", "text": "hi", "lang": "en"},
        {"text": "x" * 4001, "lang": "en"},
        {"text": "", "lang": "en"},
        {"briefing_id": "b1", "lang": "fr"},
    ):
        with pytest.raises(ValidationError):
            SpeakRequest.model_validate(bad)


def test_ask_response() -> None:
    claim = BRIEFING["sections"][0]["claims"][0]
    base = {
        "ask_id": "a1",
        "status": "refused",
        "claims": [],
        "refusal_claim": claim,
        "mode": "demo",
        "library_run_id": PROVENANCE["run_id"],
    }
    AskResponse.model_validate(base)
    with pytest.raises(ValidationError):
        AskResponse.model_validate({**base, "status": "maybe"})
    with pytest.raises(ValidationError):
        AskResponse.model_validate({**base, "claims": [{**claim, "evidence": []}]})
    assert EVIDENCE["run_id"]


def test_api_error_codes() -> None:
    ApiError.model_validate({"error": {"code": "RATE_LIMITED", "message": "slow down"}})
    with pytest.raises(ValidationError):
        ApiError.model_validate({"error": {"code": "TEAPOT", "message": "x"}})
    with pytest.raises(ValidationError):
        ApiError.model_validate({"code": "INTERNAL", "message": "x"})


def test_every_api_model_has_a_schema() -> None:
    for name in API_MODELS:
        assert f"brain_api.{name}.json" in SCHEMAS
