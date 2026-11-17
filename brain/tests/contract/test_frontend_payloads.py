"""The Brain's SSE and REST payloads validate against the exported JSON Schemas in
``packages/stitch_common/schemas`` (the files the frontend's types are generated from and its
Ajv fixture test reads), across the runs the UI must handle: the headline demo, the seeded
conflicts in Urdu, an organ failure, and a live request that falls back to demo.

``STITCH_WRITE_FRONTEND_STREAM=1`` also writes the headline and conflict streams to
``frontend/fixtures/streams/brain-*.ndjson`` so the frontend reducer test replays real Brain
output."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from brain_testkit import faulty_registry, run_briefing
from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for

from stitch_brain.paths import repo_root

SCHEMAS = repo_root() / "packages" / "stitch_common" / "schemas"
PAYLOAD = {
    "plan": "brain_api.payload_plan",
    "organ_call": "brain_api.payload_organ_call",
    "organ_result": "brain_api.payload_organ_result",
    "critic": "brain_api.payload_critic",
    "error": "brain_api.payload_error",
    "notice": "brain_api.payload_notice",
    "briefing": "brain.briefing",
}
_V: dict[str, Any] = {}


def _validator(name: str) -> Any:
    if name not in _V:
        schema = json.loads((SCHEMAS / f"{name}.json").read_text(encoding="utf-8"))
        cls = validator_for(schema, default=Draft202012Validator)
        _V[name] = cls(schema, format_checker=cls.FORMAT_CHECKER)
    return _V[name]


def _check(name: str, doc: Any, where: str) -> None:
    errors = sorted(_validator(name).iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, f"{where} vs {name}: " + "; ".join(
        f"{'/'.join(map(str, e.path))}: {e.message[:200]}" for e in errors[:5]
    )


def _frames(result: Any) -> list[dict[str, Any]]:
    return [
        {"seq": i, "event": e.event, "data": e.model_dump(mode="json")}
        for i, e in enumerate(result.events, start=1)
    ]


def _runs() -> dict[str, Any]:
    from brain_testkit import recorded_registry

    async def go() -> dict[str, Any]:
        return {
            "default-demo.en": await run_briefing(),
            "conflict.ur": await run_briefing("demo-sindh-2022-conflicts", "ur"),
            "organ-error.en": await run_briefing(registry=faulty_registry(["ledger"], "error")),
            "live-fallback.en": await run_briefing(mode="live", registry=recorded_registry()),
        }

    return asyncio.run(go())


@pytest.fixture(scope="module")
def runs() -> dict[str, Any]:
    return _runs()


def test_every_event_and_payload_matches_the_exported_schemas(runs: dict[str, Any]) -> None:
    for name, res in runs.items():
        frames = _frames(res)
        assert frames[0]["event"] == "plan" and frames[-1]["event"] == "briefing", name
        for f in frames:
            _check("brain.task_event", f["data"], f"{name}#{f['seq']}")
            if f["event"] in PAYLOAD:
                _check(PAYLOAD[f["event"]], f["data"]["payload"], f"{name}#{f['seq']} payload")
        _check("brain.briefing", res.briefing.model_dump(mode="json"), name)


def test_ui_relevant_fields_are_present(runs: dict[str, Any]) -> None:
    """Fields the reducer and briefing view read (frontend/src/state, components/briefing)."""
    for name, res in runs.items():
        for e in res.events:
            p = e.payload
            if e.event in ("organ_call", "organ_result"):
                assert e.organ in ("eyes", "oracle", "library", "ledger"), (name, e.organ)
                assert e.tool, name
                assert p["served_by"] in ("real", "recorded")
            if e.event == "organ_call":
                assert p["started_at"]
            if e.event == "organ_result":
                assert isinstance(p["duration_ms"], int | float) and p["run_id"]
                if not p["ok"]:
                    assert p["error"]["code"] and p["error"]["message"]
        b = res.briefing
        assert [s.id for s in b.sections] == [
            "extent",
            "forecast",
            "guidance",
            "allocation",
            "caveats",
        ]
        assert b.disclaimer and b.organs
        for s in b.sections:
            if s.status != "ok" and s.id != "caveats":
                assert s.missing, (name, s.id)  # Panel shows what is missing by name
    conflicts = runs["conflict.ur"].briefing.conflicts
    assert conflicts and all(c.rule_id and c.status == "final" and c.subjects for c in conflicts)
    notices = [e for e in runs["live-fallback.en"].events if e.event == "notice"]
    assert [n.payload["code"] for n in notices] == ["MODE_FALLBACK"]
    assert runs["live-fallback.en"].briefing.mode == "demo"


def test_organ_list_and_ask_response_match_the_schemas() -> None:
    from brain_testkit import recorded_registry
    from fastapi.testclient import TestClient

    from stitch_brain.api.app import create_app
    from stitch_brain.settings import Settings

    app = create_app(Settings(recorded_organs=("all",)), registry=recorded_registry(), llm=None)
    with TestClient(app) as c:
        _check("brain_api.organ_list", c.get("/organs").json(), "/organs")
        _check("brain_api.brain_health", c.get("/healthz").json(), "/healthz")
        q = "How much drinking water does each person need per day in a flood emergency?"
        for question in (q, "What is the capital of France?"):
            _check(
                "brain_api.ask_response", c.post("/ask", json={"question": question}).json(), "/ask"
            )


def test_write_frontend_streams(runs: dict[str, Any]) -> None:
    if os.environ.get("STITCH_WRITE_FRONTEND_STREAM") != "1":
        pytest.skip(
            "set STITCH_WRITE_FRONTEND_STREAM=1 to refresh frontend/fixtures/streams/brain-*"
        )
    out = Path(repo_root()) / "frontend" / "fixtures" / "streams"
    for name in ("default-demo.en", "conflict.ur"):
        lines = [json.dumps(f, ensure_ascii=False) for f in _frames(runs[name])]
        (out / f"brain-{name}.ndjson").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
        )
