"""Brain HTTP/SSE API (tasks 23 to 26; BRN-R8, R14; BRN-P11, P21, P22). All organs are recorded
fixtures and the app runs in-process (``TestClient``), so no socket is opened."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from brain_testkit import faulty_registry, recorded_registry
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_brain.api.app import create_app
from stitch_brain.api.limits import TokenBuckets
from stitch_brain.runtime.clock import RealClock
from stitch_brain.settings import Settings
from stitch_common.brain import Briefing, TaskEvent
from stitch_common.brain_api import AskResponse, BriefingState, EvidenceValue, OrganList

ORIGIN = "http://localhost:3000"
BRIEF = {"region": "pk-sindh", "scenario": "demo-sindh-2022", "lang": "en", "mode": "demo"}


LOOSE = {g: (6000.0, 1000) for g in ("briefings", "ask", "voice", "default")}


def _settings(**kw: Any) -> Settings:
    kw.setdefault("rate_limits", LOOSE)
    return Settings(recorded_organs=("all",), db_path=None, **kw)


@pytest.fixture
def client() -> Iterator[TestClient]:
    s = _settings()
    app = create_app(s, registry=recorded_registry(), llm=None)
    with TestClient(app) as c:
        yield c


def _wait_done(c: TestClient, bid: str, timeout_s: float = 30.0) -> dict[str, Any]:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        r = c.get(f"/briefings/{bid}")
        assert r.status_code == 200
        body: dict[str, Any] = r.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def _frames(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        f: dict[str, Any] = {}
        for line in block.split("\n"):
            if line.startswith("id: "):
                f["id"] = int(line[4:])
            elif line.startswith("event: "):
                f["event"] = line[7:]
            elif line.startswith("data: "):
                f["data"] = json.loads(line[6:])
        if "id" in f:
            out.append(f)
    return out


def _start(c: TestClient, body: dict[str, Any] | None = None) -> str:
    r = c.post("/briefings", json=body or BRIEF)
    assert r.status_code == 202, r.text
    acc = r.json()
    assert acc["status"] == "running"
    assert acc["events_url"] == f"/briefings/{acc['briefing_id']}/events"
    assert acc["task_id"] == acc["briefing_id"]
    return str(acc["briefing_id"])


# --- task 23: briefings, SSE, resume, cancel ---------------------------------------------------
def test_run_stream_order_and_contract(client: TestClient) -> None:
    bid = _start(client)
    state = _wait_done(client, bid)
    assert state["status"] == "done"
    BriefingState.model_validate(state)
    briefing = Briefing.model_validate(state["briefing"])
    r = client.get(f"/briefings/{bid}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.startswith("retry: 2000")
    frames = _frames(r.text)
    ids = [f["id"] for f in frames]
    assert ids == list(range(1, len(ids) + 1))
    events = [TaskEvent.model_validate(f["data"]) for f in frames]
    assert all(f["event"] == e.event for f, e in zip(frames, events, strict=True))
    assert events[0].event == "plan"
    assert events[-1].event == "briefing"
    assert Briefing.model_validate(events[-1].payload) == briefing
    seen_call: set[str] = set()
    results: dict[str, int] = {}
    for e in events:
        if e.event == "organ_call":
            assert e.task_id not in results, "organ_call after its organ_result"
            seen_call.add(e.task_id)
        if e.event == "organ_result":
            assert e.task_id in seen_call
            results[e.task_id] = results.get(e.task_id, 0) + 1
            assert e.payload["run_id"]
    assert set(results.values()) == {1}
    kinds = [e.event for e in events]
    last_critic = max(i for i, k in enumerate(kinds) if k == "critic")
    assert last_critic < kinds.index("briefing")


def test_resume_with_last_event_id_has_no_gaps_or_duplicates(client: TestClient) -> None:
    bid = _start(client)
    _wait_done(client, bid)
    full = _frames(client.get(f"/briefings/{bid}/events").text)
    n = len(full)
    for k in (0, 1, n // 2, n - 1, n):
        hdr = client.get(f"/briefings/{bid}/events", headers={"Last-Event-ID": str(k)})
        qry = client.get(f"/briefings/{bid}/events?last_event_id={k}")
        for r in (hdr, qry):
            ids = [f["id"] for f in _frames(r.text)]
            assert ids == list(range(k + 1, n + 1))


def test_non_integer_last_event_id_is_400(client: TestClient) -> None:
    bid = _start(client)
    _wait_done(client, bid)
    r = client.get(f"/briefings/{bid}/events", headers={"Last-Event-ID": "abc"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_INPUT"
    r = client.get(f"/briefings/{bid}/events?last_event_id=1.5")
    assert r.status_code == 400


def test_unknown_ids_are_404(client: TestClient) -> None:
    for path in ("/briefings/nope", "/briefings/nope/events", "/evidence/nope"):
        r = client.get(path)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


def test_invalid_requests_are_rejected(client: TestClient) -> None:
    bad = [
        {**BRIEF, "scenario": "nope"},
        {**BRIEF, "region": "pk-punjab"},
        {**BRIEF, "lang": "fr"},
        {**BRIEF, "extra": 1},
        {**BRIEF, "region": "x" * 65},
    ]
    for body in bad:
        r = client.post("/briefings", json=body)
        assert r.status_code in (400, 422), body
        assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_cancel_ends_the_stream_with_a_fatal_cancelled_error() -> None:
    reg = faulty_registry(["ledger"], "hang", RealClock())
    app = create_app(_settings(), registry=reg, llm=None)
    with TestClient(app) as c:
        bid = _start(c)
        time.sleep(0.3)
        r = c.delete(f"/briefings/{bid}")
        assert r.status_code == 202
        state = _wait_done(c, bid)
        assert state["status"] == "cancelled"
        assert "briefing" not in state or state["briefing"] is None
        frames = _frames(c.get(f"/briefings/{bid}/events").text)
        last = frames[-1]["data"]
        assert last["event"] == "error"
        assert last["payload"]["code"] == "CANCELLED"
        assert last["payload"]["fatal"] is True
        assert c.delete(f"/briefings/{bid}").status_code == 202  # idempotent


def test_busy_when_the_run_limit_is_reached() -> None:
    reg = faulty_registry(["ledger"], "hang", RealClock())
    app = create_app(_settings(max_runs=1), registry=reg, llm=None)
    with TestClient(app) as c:
        bid = _start(c)
        r = c.post("/briefings", json=BRIEF)
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "BUSY"
        assert r.headers["Retry-After"]
        c.delete(f"/briefings/{bid}")


def test_urdu_briefing_over_http(client: TestClient) -> None:
    bid = _start(client, {**BRIEF, "lang": "ur"})
    b = Briefing.model_validate(_wait_done(client, bid)["briefing"])
    assert b.lang == "ur"
    assert b.critic.passed


# --- task 24: evidence, organs, evals, healthz, CORS, limits --------------------------------------
def test_every_claim_ref_resolves_over_http(client: TestClient) -> None:
    for scenario in ("demo-sindh-2022", "demo-sindh-2022-conflicts"):
        bid = _start(client, {**BRIEF, "scenario": scenario})
        b = Briefing.model_validate(_wait_done(client, bid)["briefing"])
        refs = [r for s in b.sections for c in s.claims for r in c.evidence]
        refs += [r for c in b.conflicts for r in c.evidence]
        assert refs
        for ref in refs:
            r = client.get(f"/evidence/{ref.run_id}", params={"pointer": ref.json_pointer})
            assert r.status_code == 200, (ref, r.text)
            v = EvidenceValue.model_validate(r.json())
            assert v.ref.run_id == ref.run_id
            assert v.organ == ref.organ
            assert v.tool == ref.tool
            assert v.served_by in ("recorded", "brain")


def test_evidence_full_result_and_404_reasons(client: TestClient) -> None:
    bid = _start(client)
    b = Briefing.model_validate(_wait_done(client, bid)["briefing"])
    ref = b.sections[0].claims[0].evidence[0]
    full = client.get(f"/evidence/{ref.run_id}").json()
    assert set(full) >= {"ok", "data", "provenance", "warnings"}
    r = client.get(f"/evidence/{ref.run_id}", params={"pointer": "/data/no_such_field"})
    assert r.status_code == 404
    assert r.json()["error"]["details"]["reason"]
    r = client.get(f"/evidence/{ref.run_id}", params={"pointer": "no-slash"})
    assert r.status_code == 404


def test_organs_healthz_and_evals(client: TestClient) -> None:
    body = OrganList.model_validate(client.get("/organs").json())
    assert [o.organ for o in body.organs] == ["eyes", "oracle", "library", "ledger", "voice"]
    assert all(o.served_by == "recorded" and o.stub for o in body.organs)
    assert body.live_available is False
    assert body.default_mode == "demo"
    h = client.get("/healthz").json()
    assert set(h) == {"status", "organs_ready", "db_ok"}
    ev = client.get("/evals/latest")
    assert ev.status_code == 200
    assert "organs" in ev.json()


def test_cors_allows_listed_origins_only(client: TestClient) -> None:
    pre = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    ok = client.options("/briefings", headers={"Origin": ORIGIN, **pre})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in ok.headers
    bad = client.options("/briefings", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in bad.headers
    get = client.get("/organs", headers={"Origin": "https://stitch.aashirnoman.dev"})
    assert get.headers["access-control-allow-origin"] == "https://stitch.aashirnoman.dev"
    get = client.get("/organs", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in get.headers


def test_rate_limit_on_post_briefings_with_retry_after() -> None:
    now = [1000.0]
    s = _settings(rate_limits=Settings().rate_limits)
    app = create_app(s, registry=recorded_registry(), llm=None, monotonic=lambda: now[0])
    bad = {**BRIEF, "scenario": "nope"}  # rejected (400) after the limiter, so no run starts
    with TestClient(app) as c:
        codes = [c.post("/briefings", json=bad).status_code for _ in range(4)]
        assert codes == [400, 400, 400, 429]
        r = c.post("/briefings", json=bad)
        assert r.json()["error"]["code"] == "RATE_LIMITED"
        assert int(r.headers["Retry-After"]) >= 1
        assert c.get("/organs").status_code == 200  # other routes have their own bucket
        now[0] += 10.0  # 6 per minute: one token per 10 s
        assert c.post("/briefings", json=bad).status_code == 400


def test_body_cap_is_413(client: TestClient) -> None:
    r = client.post(
        "/briefings",
        content=b'{"region": "' + b"x" * 70_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@settings(max_examples=60, deadline=None)
@given(
    per_min=st.integers(1, 120),
    burst=st.integers(1, 10),
    gaps=st.lists(st.floats(0, 5, allow_nan=False), min_size=1, max_size=80),
    window=st.floats(1, 60, allow_nan=False),
)
def test_brn_p22_rate_limiter_never_admits_more_than_its_budget(
    per_min: int, burst: int, gaps: list[float], window: float
) -> None:
    now = [0.0]
    tb = TokenBuckets({"default": (float(per_min), burst)}, clock=lambda: now[0])
    admitted: list[float] = []
    for g in gaps:
        now[0] += g
        if tb.take("c", "default") is None:
            admitted.append(now[0])
    rate = per_min / 60.0
    for i, start in enumerate(admitted):
        inside = [t for t in admitted[i:] if t <= start + window]
        assert len(inside) <= rate * window + burst + 1e-9


def test_no_secrets_or_prompts_in_responses(client: TestClient, monkeypatch: Any) -> None:
    from stitch_brain.runtime import llm_steps

    monkeypatch.setenv("NEBIUS_API_KEY", "sk-test-secret-value")
    bid = _start(client)
    _wait_done(client, bid)
    texts = [
        client.get(f"/briefings/{bid}").text,
        client.get(f"/briefings/{bid}/events").text,
        client.get("/organs").text,
        client.get("/healthz").text,
    ]
    blob = "\n".join(texts)
    for secret in ("sk-test-secret-value", "NEBIUS_API_KEY", llm_steps.PHRASE_SYSTEM[:60]):
        assert secret not in blob
    assert "Traceback" not in blob


# --- task 25: /ask -----------------------------------------------------------------------------
class _Spy:
    def __init__(self, inner: Any, calls: list[str]) -> None:
        self.inner, self.calls = inner, calls
        self.organ, self.served_by = inner.organ, inner.served_by

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def call_tool(self, tool: str, args: dict[str, Any], **kw: Any) -> Any:
        self.calls.append(f"{self.organ}.{tool}")
        return await self.inner.call_tool(tool, args, **kw)

    async def read_resource(self, uri: str, **kw: Any) -> Any:
        self.calls.append(f"{self.organ}.resource")
        return await self.inner.read_resource(uri, **kw)


def _spy_client() -> tuple[TestClient, list[str]]:
    reg = recorded_registry()
    calls: list[str] = []
    for o in list(reg.clients):
        reg.clients[o] = _Spy(reg.clients[o], calls)
    return TestClient(create_app(_settings(), registry=reg, llm=None)), calls


def test_brn_p21_ask_answered_calls_only_the_library_and_adds_no_text() -> None:
    tc, calls = _spy_client()
    q = "How much drinking water does each person need per day in a flood emergency?"
    with tc as c:
        r = c.post("/ask", json={"question": f"  {q}\u0007 ", "lang": "auto"})
        assert r.status_code == 200, r.text
        body = AskResponse.model_validate(r.json())
        assert calls == ["library.answer_with_citations"]
        assert body.status == "answered"
        assert body.result is not None
        assert body.result.data is not None
        lib_texts = [cl.text for cl in body.result.data.claims]
        assert [c.text for c in body.claims] == lib_texts
        for claim in body.claims:
            assert any(e.json_pointer.startswith("/data/citations/") for e in claim.evidence)
            for ref in claim.evidence:
                rr = c.get(f"/evidence/{ref.run_id}", params={"pointer": ref.json_pointer})
                assert rr.status_code == 200


def test_ask_refusal_renders_as_a_refusal() -> None:
    tc, calls = _spy_client()
    with tc as c:
        r = c.post("/ask", json={"question": "What is the capital of France?"})
        body = AskResponse.model_validate(r.json())
        assert calls == ["library.answer_with_citations"]
        assert body.status == "refused"
        assert body.claims == []
        assert body.refusal_claim is not None
        assert "memory" in body.refusal_claim.text


def test_ask_rejects_long_and_empty_questions(client: TestClient) -> None:
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422
    assert client.post("/ask", json={"question": ""}).status_code == 422
    r = client.post("/ask", json={"question": "\u0000\u0007"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_ask_with_the_library_disabled_is_503() -> None:
    s = replace(_settings(), disabled_organs=("library",))
    from stitch_brain.runtime.registry import OrganRegistry

    with TestClient(create_app(s, registry=OrganRegistry.build(s, None), llm=None)) as c:
        r = c.post("/ask", json={"question": "water?"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


# --- task 26: voice proxies ----------------------------------------------------------------------
def test_voice_disabled_gives_503_and_nothing_else_changes() -> None:
    s = replace(_settings(), disabled_organs=("voice",))
    from stitch_brain.runtime.registry import OrganRegistry

    with TestClient(create_app(s, registry=OrganRegistry.build(s, None), llm=None)) as c:
        voice = next(o for o in c.get("/organs").json()["organs"] if o["organ"] == "voice")
        assert voice["status"] == "disabled"
        r = c.post("/voice/transcribe", json={"audio_b64": "AAAA", "format": "wav"})
        assert r.status_code == 503
        assert r.json()["error"]["details"]["status"] == "disabled"
        bid = _start(c)
        state = _wait_done(c, bid)
        assert state["status"] == "done"
        r = c.post("/voice/speak", json={"briefing_id": bid, "lang": "en"})
        assert r.status_code == 503


def test_voice_speak_rejects_free_text_by_default(client: TestClient) -> None:
    r = client.post("/voice/speak", json={"text": "hello", "lang": "en"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_INPUT"


def test_voice_transcribe_body_cap(client: TestClient) -> None:
    from stitch_common.brain_api import VOICE_TRANSCRIBE_MAX_BODY_BYTES

    big = b'{"audio_b64": "' + b"A" * (VOICE_TRANSCRIBE_MAX_BODY_BYTES + 10) + b'"}'
    r = client.post("/voice/transcribe", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
