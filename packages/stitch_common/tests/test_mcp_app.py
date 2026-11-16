"""ContractServer and run_tool: envelope behaviour over MCP, /healthz, failure mapping."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from mcp import Client

from stitch_common.envelope import ToolResult
from stitch_common.mcp_app import ContractServer
from stitch_common.organs import ORGAN_TOOLS
from stitch_common.organs.voice import SpeakIn, SpeakOut, TranscribeIn
from stitch_common.testing.examples import TOOL_EXAMPLES
from stitch_common.tooling import Outcome, ToolFailure, run_tool


def speak_ok(params: SpeakIn) -> SpeakOut:
    out = dict(TOOL_EXAMPLES["voice.speak"][1])
    out["lang"] = params.lang
    return SpeakOut.model_validate(out)


def transcribe_stub(params: TranscribeIn) -> Any:
    raise NotImplementedError


def make_server(**overrides: Any) -> ContractServer:
    cores: dict[str, Any] = {"speak": speak_ok, "transcribe": transcribe_stub}
    cores.update(overrides)
    return ContractServer("voice", "0.0.1", cores)


async def test_list_tools_advertises_exact_contract_schemas() -> None:
    async with Client(make_server()) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"speak", "transcribe"}
    for name, tool in tools.items():
        assert tool.input_schema == ORGAN_TOOLS["voice"][name].input.model_json_schema(
            mode="validation"
        )
        assert tool.output_schema is not None


async def test_call_returns_valid_envelope_matching_output_schema() -> None:
    async with Client(make_server()) as client:
        res = await client.call_tool("speak", TOOL_EXAMPLES["voice.speak"][0])
    assert not res.is_error and res.structured_content is not None
    env = ToolResult[SpeakOut].model_validate(res.structured_content)
    assert env.ok and env.data is not None and env.data.provider == "fake"
    assert env.provenance.organ == "voice" and env.provenance.tool == "speak"
    schema = ToolResult[SpeakOut].model_json_schema(mode="serialization")
    Draft202012Validator(schema).validate(res.structured_content)
    assert json.loads(res.content[0].text) == res.structured_content  # type: ignore[union-attr]


async def test_not_implemented_core_is_internal_failure_envelope() -> None:
    async with Client(make_server()) as client:
        res = await client.call_tool("transcribe", TOOL_EXAMPLES["voice.transcribe"][0])
    assert not res.is_error  # domain failures are envelopes, not protocol errors
    env = ToolResult[Any].model_validate(res.structured_content)
    assert not env.ok and env.error is not None and env.error.code == "INTERNAL"
    assert "not implemented" in env.error.message


async def test_invalid_input_is_an_envelope_naming_fields_only() -> None:
    async with Client(make_server()) as client:
        res = await client.call_tool("speak", {"text": "x" * 5000, "lang": "fr"})
    env = ToolResult[Any].model_validate(res.structured_content)
    assert env.error is not None and env.error.code == "INVALID_INPUT"
    assert "text" in env.error.message and "lang" in env.error.message
    assert "xxxx" not in env.error.message  # rejected values are not echoed


async def test_unknown_tool_is_a_protocol_error_result() -> None:
    async with Client(make_server()) as client:
        res = await client.call_tool("nope", {})
    assert res.is_error


def test_cores_must_match_contract() -> None:
    with pytest.raises(ValueError, match="missing"):
        ContractServer("voice", "0", {"speak": speak_ok})
    with pytest.raises(ValueError, match="extra"):
        ContractServer("voice", "0", {"speak": speak_ok, "transcribe": speak_ok, "x": speak_ok})


async def test_run_tool_maps_failures_and_outcome() -> None:
    args = TOOL_EXAMPLES["voice.speak"][0]

    def failing(p: SpeakIn) -> Any:
        raise ToolFailure("UPSTREAM_UNAVAILABLE", "tts down", retryable=True)

    def boom(p: SpeakIn) -> Any:
        raise RuntimeError("secret detail")

    def wrong(p: SpeakIn) -> Any:
        return {"audio_b64": 1}

    def with_outcome(p: SpeakIn) -> Any:
        return Outcome(speak_ok(p), warnings=["cached"])

    async def async_core(p: SpeakIn) -> Any:
        return speak_ok(p)

    r = await run_tool("voice", "speak", "0", failing, args)
    assert r.error is not None and r.error.code == "UPSTREAM_UNAVAILABLE" and r.error.retryable
    r = await run_tool("voice", "speak", "0", boom, args)
    assert r.error is not None and r.error.code == "INTERNAL" and "secret" not in r.error.message
    r = await run_tool("voice", "speak", "0", wrong, args)
    assert r.error is not None and r.error.code == "INTERNAL"
    r = await run_tool("voice", "speak", "0", with_outcome, args)
    assert r.ok and r.warnings == ["cached"]
    r = await run_tool("voice", "speak", "0", async_core, args)
    assert r.ok


@given(st.dictionaries(st.text(max_size=8), st.integers(), max_size=4))
async def test_p1_run_tool_never_raises_and_envelope_is_consistent(args: dict[str, Any]) -> None:
    r = await run_tool("voice", "speak", "0", speak_ok, args)
    assert r.ok == (r.data is not None and r.error is None)


@pytest.mark.allow_loopback
def test_healthz_over_http() -> None:
    """Runs the real HTTP transport in a subprocess and GETs /healthz on loopback."""
    code = (
        "from stitch_common.mcp_app import ContractServer, serve\n"
        "from stitch_common.testing.examples import TOOL_EXAMPLES\n"
        "def core(p): raise NotImplementedError\n"
        "s = ContractServer('voice', '0.0.1', {'speak': core, 'transcribe': core})\n"
        "raise SystemExit(serve(s, ['--http', '--port', PORT]))\n"
    )
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-c", code.replace("PORT", repr(str(port)))],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        body = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                    body = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.2)
        assert body is not None, "server did not answer /healthz"
        assert body["status"] == "ok" and body["organ"] == "voice"
        assert body["tools"] == ["speak", "transcribe"] and body["contract_version"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        if proc.stderr:
            proc.stderr.close()
