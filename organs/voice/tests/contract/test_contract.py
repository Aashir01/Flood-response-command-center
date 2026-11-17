"""Contract tests: tool schemas equal the exported contract (v0.5) and the shared
example payloads validate against them; real outputs validate against the exported
output schemas."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import pytest
import voice_helpers as h
from jsonschema import Draft202012Validator

from stitch_common.organs import ORGAN_TOOLS
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_voice.core import audio
from stitch_voice.models import TOOL_NAMES, TOOL_SCHEMAS
from stitch_voice.providers.fake import FakeSTT, FakeTTS


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_tool_schema_equals_exported_input_schema(
    tool: str, load_schema: Callable[[str], dict[str, Any]]
) -> None:
    assert TOOL_SCHEMAS[tool] == load_schema(f"voice.{tool}.in.json")


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_input_validates_against_tool_schema(tool: str) -> None:
    Draft202012Validator(TOOL_SCHEMAS[tool]).validate(TOOL_EXAMPLES[f"voice.{tool}"][0])


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_example_output_validates_against_contract_model(tool: str) -> None:
    ORGAN_TOOLS["voice"][tool].output.model_validate(TOOL_EXAMPLES[f"voice.{tool}"][1])


def _real_outputs() -> dict[str, list[dict[str, Any]]]:

    import voice_helpers as h

    svc = h.service(tts=[FakeTTS()], stt=[FakeSTT()])
    clip = base64.b64encode(audio.tone_wav(1.0, 440.0)).decode("ascii")
    silent = base64.b64encode(audio.silence_wav(1.0)).decode("ascii")
    calls = {
        "speak": [{"text": "The river is rising.", "lang": "en"}, {"text": "پانی", "lang": "ur"}],
        "transcribe": [
            {"audio_b64": clip, "format": "wav", "lang_hint": "ur"},
            {"audio_b64": silent, "format": "wav"},
        ],
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for tool, args in calls.items():
        out[tool] = []
        for a in args:
            res = h.call(svc, tool, a)
            assert res.ok, res.error
            out[tool].append(res.model_dump(mode="json"))
    return out


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_real_outputs_validate_against_exported_output_schema(
    tool: str, load_schema: Callable[[str], dict[str, Any]]
) -> None:
    validator = Draft202012Validator(load_schema(f"voice.{tool}.out.json"))
    for envelope in _real_outputs()[tool]:
        validator.validate(envelope["data"])
        assert envelope["provenance"]["organ"] == "voice"
        assert envelope["provenance"]["tool"] == tool


def test_failure_envelope_has_no_data() -> None:
    res = h.call(h.service(tts=[], stt=[]), "speak", {"text": "x" * 4001, "lang": "en"})
    assert not res.ok and res.data is None and res.error is not None
    assert res.error.code == "INVALID_INPUT"
