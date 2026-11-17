"""Stack smoke test through the gateway (deploy design 11, DEP-R10, DEP-P1, DEP-P6). Stdlib only,
so it runs on a CI runner, the VPS, or a laptop without installs.

    python deploy/bin/smoke.py http://127.0.0.1:8080
    python deploy/bin/smoke.py https://stitch.aashirnoman.dev --allow-disabled eyes,voice
    python deploy/bin/smoke.py http://64.177.59.11 --placeholder       # gateway and page only

Steps (each with a timeout and one clear failure line):
1. ``GET /healthz`` is 200; the start page is 200 and names Stitch.
2. ``GET /api/organs``: every organ is ``ready``; organs named in ``--allow-disabled`` may be
   ``disabled`` (lite mode, or an organ not shipped yet).
3. ``POST /api/briefings`` (demo scenario) and read the SSE stream until ``briefing``: ``plan``
   first, every ``organ_call`` before its ``organ_result``, no fatal ``error``, contiguous ids,
   ``mode == demo``, the five sections, ``critic.passed``, every claim carries evidence (BRN-P1)
   and one evidence pointer resolves through ``GET /api/evidence/{run_id}?pointer=``. Also checks
   that events arrive progressively (the gateway does not buffer SSE).
4. ``POST /api/ask`` answers with citations or returns a labelled refusal.
5. Prints a JSON report with per-step timings; exits 1 on the first failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

ORGANS = ("eyes", "oracle", "library", "ledger", "voice")
SECTION_IDS = ("extent", "forecast", "guidance", "allocation", "caveats")
DEFAULT_QUESTION = "How much drinking water does each person need per day in a flood shelter?"


class SmokeFailure(Exception):
    """One failed check, with a message meant for a human reading CI logs."""


@dataclass
class SseEvent:
    id: str | None
    event: str
    data: Any
    received_at: float = 0.0


@dataclass
class Report:
    base_url: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    failure: str | None = None


# --- HTTP helpers --------------------------------------------------------------------------------


def http(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "stitch-smoke/1")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure(f"{method} {url}: {exc}") from None


def get_json(url: str, timeout: float = 15.0) -> Any:
    status, _, raw = http("GET", url, timeout=timeout)
    if status != 200:
        raise SmokeFailure(f"GET {url}: HTTP {status}: {raw[:200]!r}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise SmokeFailure(f"GET {url}: not JSON: {raw[:200]!r}") from None


# --- SSE -----------------------------------------------------------------------------------------


def parse_sse(lines: Iterable[str], clock: Any = time.monotonic) -> Iterator[SseEvent]:
    """Parse an SSE stream (WHATWG rules for the fields Stitch uses: id, event, data, comments,
    retry). Yields one event per blank-line-terminated block that has data."""
    ev_id: str | None = None
    ev_type = "message"
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                text = "\n".join(data)
                try:
                    payload: Any = json.loads(text)
                except json.JSONDecodeError:
                    payload = text
                yield SseEvent(ev_id, ev_type, payload, clock())
            ev_type, data = "message", []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            data.append(value)
        elif name == "event":
            ev_type = value
        elif name == "id":
            ev_id = value
        # `retry` and unknown fields are ignored


def _iter_lines(resp: Any) -> Iterator[str]:
    while True:
        line = resp.readline()
        if not line:
            return
        yield line.decode("utf-8", errors="replace")


def read_events(url: str, deadline_s: float) -> list[SseEvent]:
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    req.add_header("User-Agent", "stitch-smoke/1")
    events: list[SseEvent] = []
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=deadline_s) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "text/event-stream" not in ctype:
                raise SmokeFailure(f"GET {url}: Content-Type {ctype!r}, expected text/event-stream")
            for ev in parse_sse(_iter_lines(resp)):
                events.append(ev)
                if ev.event == "briefing":
                    break
                if ev.event == "error" and isinstance(ev.data, dict):
                    payload = ev.data.get("payload", {})
                    if isinstance(payload, dict) and payload.get("fatal"):
                        break
                if time.monotonic() - start > deadline_s:
                    raise SmokeFailure(f"SSE: no briefing within {deadline_s:.0f} s")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure(f"SSE {url}: {exc} after {len(events)} events") from None
    return events


# --- checks (pure, unit tested) ------------------------------------------------------------------


def check_organs(doc: Any, allow_disabled: set[str]) -> dict[str, str]:
    if not isinstance(doc, dict) or not isinstance(doc.get("organs"), list):
        raise SmokeFailure("/api/organs: no `organs` list")
    status = {str(o.get("organ")): str(o.get("status")) for o in doc["organs"]}
    for organ in ORGANS:
        st = status.get(organ)
        if st == "ready":
            continue
        if organ in allow_disabled and st in ("disabled", None):
            continue
        reason = next((o.get("reason") for o in doc["organs"] if o.get("organ") == organ), None)
        raise SmokeFailure(f"/api/organs: {organ} is {st!r} (reason: {reason})")
    return status


def check_events(events: list[SseEvent], *, mode: str = "demo") -> dict[str, Any]:
    """Validate the order and content of one briefing run's events. Returns the briefing."""
    if not events:
        raise SmokeFailure("SSE: no events")
    types = [e.event for e in events]
    if types[0] != "plan":
        raise SmokeFailure(f"SSE: first event is {types[0]!r}, expected plan")
    ids = [e.id for e in events]
    if all(i is not None and i.isdigit() for i in ids):
        nums = [int(i) for i in ids if i is not None]
        if nums != list(range(nums[0], nums[0] + len(nums))):
            raise SmokeFailure(f"SSE: ids are not contiguous: {ids[:20]}")
    called: set[str] = set()
    critic_seen = False
    for e in events:
        data = e.data if isinstance(e.data, dict) else {}
        task = str(data.get("task_id", ""))
        if e.event == "organ_call":
            called.add(task)
        elif e.event == "organ_result" and task not in called:
            raise SmokeFailure(f"SSE: organ_result for {task!r} before its organ_call")
        elif e.event == "critic":
            critic_seen = True
        elif e.event == "error":
            payload = data.get("payload", {})
            raise SmokeFailure(f"SSE: error event on {task!r}: {payload}")
        elif e.event == "briefing" and not critic_seen:
            raise SmokeFailure("SSE: briefing arrived before any critic event")
    if types[-1] != "briefing":
        raise SmokeFailure(f"SSE: last event is {types[-1]!r}, expected briefing")
    if "organ_call" not in types:
        raise SmokeFailure("SSE: no organ_call events")
    last = events[-1].data
    briefing = last.get("payload") if isinstance(last, dict) else None
    if not isinstance(briefing, dict):
        raise SmokeFailure("SSE: briefing event has no payload object")
    return check_briefing(briefing, mode=mode)


def check_briefing(b: dict[str, Any], *, mode: str = "demo") -> dict[str, Any]:
    if b.get("mode") != mode:
        raise SmokeFailure(f"briefing: mode {b.get('mode')!r}, expected {mode!r}")
    ids = [s.get("id") for s in b.get("sections", [])]
    if sorted(ids) != sorted(SECTION_IDS):
        raise SmokeFailure(f"briefing: sections {ids}, expected {list(SECTION_IDS)}")
    critic = b.get("critic") or {}
    if not critic.get("passed"):
        raise SmokeFailure(f"briefing: critic did not pass: {critic.get('notes')}")
    n = 0
    for s in b["sections"]:
        for c in s.get("claims", []):
            n += 1
            if not c.get("evidence"):
                raise SmokeFailure(f"briefing: claim {c.get('id')!r} has no evidence (BRN-P1)")
    if n == 0:
        raise SmokeFailure("briefing: no claims")
    return b


def first_evidence(b: dict[str, Any]) -> dict[str, Any]:
    for s in b["sections"]:
        for c in s.get("claims", []):
            for ref in c.get("evidence", []):
                if ref.get("run_id") and ref.get("json_pointer") is not None:
                    return dict(ref)
    raise SmokeFailure("briefing: no resolvable EvidenceRef")


def check_progressive(events: list[SseEvent], min_spread_s: float = 0.05) -> float:
    """SSE must not be buffered by the gateway: the first organ_call has to arrive measurably
    before the briefing. Returns the spread in seconds."""
    first_call = next((e.received_at for e in events if e.event == "organ_call"), None)
    if first_call is None:
        raise SmokeFailure("SSE: no organ_call to time")
    spread = events[-1].received_at - first_call
    if spread < min_spread_s:
        raise SmokeFailure(
            f"SSE: all events arrived within {spread:.3f} s; the gateway buffers the stream"
        )
    return spread


def check_ask(doc: Any) -> str:
    if not isinstance(doc, dict):
        raise SmokeFailure("/api/ask: not an object")
    status = doc.get("status")
    if status == "answered":
        claims = doc.get("claims") or []
        if not claims or not all(c.get("evidence") for c in claims):
            raise SmokeFailure("/api/ask: answered without evidence on every claim")
    elif status == "refused":
        if not doc.get("refusal_claim"):
            raise SmokeFailure("/api/ask: refused without a refusal_claim")
    else:
        raise SmokeFailure(f"/api/ask: status {status!r}")
    return str(status)


# --- runner --------------------------------------------------------------------------------------


def _step(report: Report, name: str, fn: Any) -> Any:
    t0 = time.monotonic()
    try:
        out = fn()
    except SmokeFailure as exc:
        report.steps.append({"step": name, "ok": False, "seconds": round(time.monotonic() - t0, 3)})
        report.ok, report.failure = False, f"{name}: {exc}"
        raise
    entry: dict[str, Any] = {"step": name, "ok": True, "seconds": round(time.monotonic() - t0, 3)}
    if isinstance(out, dict) and "detail" in out:
        entry["detail"] = out["detail"]
    report.steps.append(entry)
    return out


def run(args: argparse.Namespace, report: Report) -> Report:
    base = args.base_url.rstrip("/")
    allow = {x.strip() for x in args.allow_disabled.split(",") if x.strip()}

    def healthz() -> dict[str, Any]:
        status, _, body = http("GET", f"{base}/healthz", timeout=args.timeout)
        if status != 200:
            raise SmokeFailure(f"GET /healthz: HTTP {status}")
        page = "/" if args.placeholder else "/en/"
        status, headers, body = http("GET", f"{base}{page}", timeout=args.timeout)
        if status != 200 or b"Stitch" not in body:
            raise SmokeFailure(f"GET {page}: HTTP {status}, Stitch not in page")
        missing = [
            h
            for h in ("content-security-policy", "x-content-type-options", "referrer-policy")
            if h not in headers
        ]
        if missing:
            raise SmokeFailure(f"GET {page}: missing security headers {missing}")
        return {"detail": {"page": page, "bytes": len(body)}}

    _step(report, "gateway", healthz)
    if args.placeholder:
        return report

    def organs() -> dict[str, Any]:
        return {"detail": check_organs(get_json(f"{base}/api/organs", args.timeout), allow)}

    _step(report, "organs", organs)

    def briefing() -> dict[str, Any]:
        body = {"region": args.region, "scenario": args.scenario, "lang": args.lang, "mode": "demo"}
        status, _, raw = http("POST", f"{base}/api/briefings", body, timeout=args.timeout)
        if status != 202:
            raise SmokeFailure(f"POST /api/briefings: HTTP {status}: {raw[:300]!r}")
        bid = json.loads(raw)["briefing_id"]
        events = read_events(f"{base}/api/briefings/{bid}/events", args.briefing_timeout)
        b = check_events(events)
        spread = check_progressive(events)
        ref = first_evidence(b)
        q = urllib.parse.urlencode({"pointer": ref["json_pointer"]})
        ev = get_json(f"{base}/api/evidence/{ref['run_id']}?{q}", args.timeout)
        if "value" not in ev:
            raise SmokeFailure(f"evidence {ref['run_id']}: no value in response")
        claims = sum(len(s.get("claims", [])) for s in b["sections"])
        return {
            "detail": {
                "briefing_id": bid,
                "events": len(events),
                "claims": claims,
                "sse_spread_s": round(spread, 3),
                "confidence": b.get("confidence"),
                "section_status": {s["id"]: s.get("status") for s in b["sections"]},
            }
        }

    _step(report, "briefing", briefing)

    def ask() -> dict[str, Any]:
        status, _, raw = http(
            "POST", f"{base}/api/ask", {"question": args.question, "lang": "en"}, args.timeout * 4
        )
        if status != 200:
            raise SmokeFailure(f"POST /api/ask: HTTP {status}: {raw[:300]!r}")
        return {"detail": {"status": check_ask(json.loads(raw))}}

    _step(report, "ask", ask)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stitch stack smoke test (stdlib only)")
    p.add_argument("base_url", nargs="?", default="http://127.0.0.1:8080")
    p.add_argument("--allow-disabled", default="", help="comma list of organs that may be disabled")
    p.add_argument("--placeholder", action="store_true", help="dry-run image: gateway and page")
    p.add_argument("--region", default="pk-sindh")
    p.add_argument("--scenario", default="demo-sindh-2022")
    p.add_argument("--lang", default="en", choices=["en", "ur"])
    p.add_argument("--question", default=DEFAULT_QUESTION)
    p.add_argument("--timeout", type=float, default=15.0, help="per request, seconds")
    p.add_argument("--briefing-timeout", type=float, default=120.0)
    p.add_argument("--retries", type=int, default=0, help="retry the gateway step (post-deploy)")
    args = p.parse_args(argv)
    t0 = time.monotonic()
    report = Report(base_url=args.base_url.rstrip("/"))
    for attempt in range(args.retries + 1):
        report = Report(base_url=args.base_url.rstrip("/"))
        try:
            run(args, report)
            break
        except SmokeFailure:
            # Only an unreachable gateway is retried (containers still starting after a deploy).
            if attempt < args.retries and len(report.steps) == 1:
                time.sleep(5)
                continue
            break
    out = {
        "ok": report.ok,
        "base_url": report.base_url,
        "failure": report.failure,
        "steps": report.steps,
        "seconds": round(time.monotonic() - t0, 3),
    }
    print(json.dumps(out, indent=2))
    if not report.ok:
        print(f"SMOKE FAIL: {report.failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
