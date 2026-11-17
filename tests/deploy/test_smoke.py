"""DEP-R10.1, DEP-P6: the stack smoke script (deploy/bin/smoke.py). Pure checks with seeded
defects, plus one run of the whole script against an in-process fake Brain on 127.0.0.1."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "smoke.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stitch_smoke", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stitch_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


smoke = _load()

REF = {
    "run_id": "r-ledger-1",
    "organ": "ledger",
    "tool": "optimize_allocation",
    "json_pointer": "/data/total_coverage",
}


def _briefing() -> dict[str, Any]:
    return {
        "briefing_id": "b1",
        "scenario": "demo-sindh-2022",
        "lang": "en",
        "mode": "demo",
        "sections": [
            {
                "id": sid,
                "title": sid,
                "status": "ok",
                "claims": [{"id": f"{sid}-1", "text": "x", "evidence": [REF], "kind": "statement"}],
            }
            for sid in smoke.SECTION_IDS
        ],
        "conflicts": [],
        "critic": {"passed": True, "removed_claims": [], "notes": []},
        "confidence": 0.7,
        "generated_at": "2022-08-30T00:00:00Z",
    }


def _events(briefing: dict[str, Any] | None = None) -> list[str]:
    seq = [
        ("plan", "plan", {"nodes": []}),
        ("organ_call", "ledger.optimize", {"attempt": 1}),
        ("organ_result", "ledger.optimize", {"ok": True}),
        ("critic", "critic", {"pass": 1, "passed": True}),
        ("briefing", "briefing", briefing or _briefing()),
    ]
    lines: list[str] = ["retry: 2000\n", "\n", ": ping\n", "\n"]
    for i, (ev, task, payload) in enumerate(seq, 1):
        msg = {"event": ev, "ts": "2022-08-30T00:00:00Z", "task_id": task, "payload": payload}
        lines += [f"id: {i}\n", f"event: {ev}\n", f"data: {json.dumps(msg)}\n", "\n"]
    return lines


def _parsed(lines: list[str]) -> list[Any]:
    clock = iter(range(1000))
    return list(smoke.parse_sse(lines, clock=lambda: next(clock) * 0.1))


# --- parser ------


def test_parse_sse_skips_comments_and_retry() -> None:
    evs = _parsed(_events())
    assert [e.event for e in evs] == ["plan", "organ_call", "organ_result", "critic", "briefing"]
    assert [e.id for e in evs] == ["1", "2", "3", "4", "5"]
    assert evs[0].data["task_id"] == "plan"


def test_parse_sse_multiline_data_and_crlf() -> None:
    evs = list(smoke.parse_sse(["event: notice\r\n", "data: a\r\n", "data: b\r\n", "\r\n"]))
    assert evs[0].event == "notice" and evs[0].data == "a\nb"


def test_valid_stream_passes() -> None:
    b = smoke.check_events(_parsed(_events()))
    assert smoke.first_evidence(b) == REF
    assert smoke.check_progressive(_parsed(_events())) > 0


# --- seeded defects ------


def test_missing_evidence_fails() -> None:
    b = _briefing()
    b["sections"][2]["claims"][0]["evidence"] = []
    with pytest.raises(smoke.SmokeFailure, match="no evidence"):
        smoke.check_events(_parsed(_events(b)))


def test_error_event_fails() -> None:
    lines = _events()
    err = {
        "event": "error",
        "ts": "t",
        "task_id": "run",
        "payload": {"code": "INTERNAL", "message": "x", "fatal": True, "retryable": False},
    }
    lines[-4:] = ["id: 5\n", "event: error\n", f"data: {json.dumps(err)}\n", "\n"]
    with pytest.raises(smoke.SmokeFailure, match="error event"):
        smoke.check_events(_parsed(lines))


def test_result_before_call_fails() -> None:
    lines = _events()
    # swap the organ_call block (lines 8-11) with the organ_result block (12-15), ids kept in order
    call, result = lines[8:12], lines[12:16]
    call[0], result[0] = result[0], call[0]
    lines[8:16] = result + call
    with pytest.raises(smoke.SmokeFailure, match="before its organ_call"):
        smoke.check_events(_parsed(lines))


def test_plan_not_first_fails() -> None:
    lines = _events()[4:]
    lines = lines[4:] + lines[:4]
    with pytest.raises(smoke.SmokeFailure, match="first event"):
        smoke.check_events(_parsed(lines))


def test_live_mode_briefing_fails() -> None:
    b = _briefing()
    b["mode"] = "live"
    with pytest.raises(smoke.SmokeFailure, match="mode"):
        smoke.check_events(_parsed(_events(b)))


def test_missing_section_and_failed_critic() -> None:
    b = _briefing()
    b["sections"].pop()
    with pytest.raises(smoke.SmokeFailure, match="sections"):
        smoke.check_briefing(b)
    b = _briefing()
    b["critic"]["passed"] = False
    with pytest.raises(smoke.SmokeFailure, match="critic"):
        smoke.check_briefing(b)


def test_buffered_stream_fails() -> None:
    evs = list(smoke.parse_sse(_events(), clock=lambda: 1.0))
    with pytest.raises(smoke.SmokeFailure, match="buffer"):
        smoke.check_progressive(evs)


def test_organs_check() -> None:
    doc = {"organs": [{"organ": o, "status": "ready"} for o in smoke.ORGANS]}
    smoke.check_organs(doc, set())
    doc["organs"][0]["status"] = "disabled"
    with pytest.raises(smoke.SmokeFailure, match="eyes"):
        smoke.check_organs(doc, set())
    smoke.check_organs(doc, {"eyes"})
    doc["organs"][1]["status"] = "unwell"
    with pytest.raises(smoke.SmokeFailure, match="oracle"):
        smoke.check_organs(doc, {"eyes"})


def test_ask_check() -> None:
    assert smoke.check_ask({"status": "answered", "claims": [{"evidence": [REF]}]}) == "answered"
    assert smoke.check_ask({"status": "refused", "claims": [], "refusal_claim": {"id": "r"}})
    with pytest.raises(smoke.SmokeFailure):
        smoke.check_ask({"status": "answered", "claims": [{"evidence": []}]})
    with pytest.raises(smoke.SmokeFailure):
        smoke.check_ask({"status": "refused", "claims": []})


# --- whole script against a fake Brain behind a fake gateway ------


class _FakeGateway(BaseHTTPRequestHandler):
    briefing: dict[str, Any] = _briefing()

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path
        if path == "/healthz":
            self._send(200, b"ok", "text/plain")
        elif path == "/en/":
            self._send(200, b"<html><title>Stitch</title></html>", "text/html")
        elif path == "/api/organs":
            organs = [{"organ": o, "status": "ready"} for o in ("oracle", "library", "ledger")]
            organs += [{"organ": o, "status": "disabled"} for o in ("eyes", "voice")]
            self._send(200, json.dumps({"organs": organs}).encode())
        elif path.startswith("/api/briefings/b1/events"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for line in _events(self.briefing):
                self.wfile.write(line.encode())
                if line == "\n":
                    self.wfile.flush()
                    time.sleep(0.03)
        elif path.startswith("/api/evidence/r-ledger-1?pointer="):
            self._send(200, json.dumps({"ref": REF, "value": 1.0}).encode())
        else:
            self._send(404, b"{}")

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(n)
        if self.path == "/api/briefings":
            self._send(202, json.dumps({"briefing_id": "b1", "status": "running"}).encode())
        elif self.path == "/api/ask":
            doc = {
                "status": "refused",
                "claims": [],
                "refusal_claim": {"id": "r", "evidence": [REF]},
            }
            self._send(200, json.dumps(doc).encode())
        else:
            self._send(404, b"{}")


@pytest.fixture
def gateway() -> Iterator[str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeGateway)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.allow_loopback
def test_script_passes_against_fake_gateway(
    gateway: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _FakeGateway.briefing = _briefing()
    assert smoke.main([gateway, "--allow-disabled", "eyes,voice"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [s["step"] for s in report["steps"]] == ["gateway", "organs", "briefing", "ask"]


@pytest.mark.allow_loopback
def test_script_fails_on_disabled_organ_without_allowance(gateway: str) -> None:
    assert smoke.main([gateway]) == 1


@pytest.mark.allow_loopback
def test_script_fails_on_bad_briefing(gateway: str) -> None:
    bad = copy.deepcopy(_briefing())
    bad["critic"]["passed"] = False
    _FakeGateway.briefing = bad
    try:
        assert smoke.main([gateway, "--allow-disabled", "eyes,voice"]) == 1
    finally:
        _FakeGateway.briefing = _briefing()
