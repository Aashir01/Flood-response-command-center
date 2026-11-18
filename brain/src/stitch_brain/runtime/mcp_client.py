"""``McpOrganClient``: a long-lived MCP session per organ over stdio or streamable HTTP, owned
by a supervisor task with backoff (design 3.1, 3.2).

The SDK ``Client`` is an async context manager whose cancel scopes must be entered and exited
in the same task, so the supervisor task owns it and other tasks only send requests through the
session. A connection failure never blocks startup: calls made while disconnected return a
``CONNECTION`` transport error and the supervisor keeps retrying (1, 2, 4, 8, 16, 30 s, with
seeded jitter).

SDK finding (task 8): ``mcp`` 2.x sends ``notifications/cancelled`` when a request times out or
the awaiting task is cancelled. The server may still finish the work; the Brain discards a
cancelled call's result.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from stitch_brain.config import OrganEndpoint
from stitch_brain.core.evidence import sha256_json
from stitch_brain.runtime.clock import Clock, RealClock, wait_for
from stitch_brain.runtime.organs import (
    CallContext,
    CallHistory,
    CallOutcome,
    Compat,
    OrganHealth,
    ServedBy,
    TransportError,
    health_status,
    resource_tool,
    wrap_resource,
)
from stitch_brain.runtime.validate import ContractViolation, validate_tool_result
from stitch_common.organs import ORGAN_TOOLS

BACKOFF_STEPS_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
BREAKER_WINDOW_S = 15.0
PING_INTERVAL_S = 10.0
PROBE_TIMEOUT_S = 5.0
# Largest single SSE event accepted from an organ over HTTP: a 4,000-character spoken briefing
# is about 12 MB of WAV, 16 MB in base64.
MAX_SSE_EVENT_BYTES = 32 * 1024 * 1024
PROBE_FAILURES = 3
_DROP_KEYS = frozenset({"description", "title", "default", "examples"})


def _normalize(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _normalize(v) for k, v in sorted(schema.items()) if k not in _DROP_KEYS}
    if isinstance(schema, list):
        return [_normalize(x) for x in schema]
    return schema


def _types(prop: Any) -> Any:
    if not isinstance(prop, dict):
        return None
    if "anyOf" in prop:
        return sorted(json.dumps(_types(p), sort_keys=True) for p in prop["anyOf"])
    return prop.get("type") or prop.get("$ref") or prop.get("const")


def compat_problems(organ: str, discovered: dict[str, dict[str, Any]]) -> list[str]:
    """Missing tool, missing or extra required property, or a property type mismatch marks the
    organ incompatible (design 3.2). Schemas are compared after normalization."""
    problems: list[str] = []
    for tool, spec in ORGAN_TOOLS.get(organ, {}).items():
        got = discovered.get(tool)
        if got is None:
            problems.append(f"missing tool {tool}")
            continue
        want = _normalize(spec.input.model_json_schema(mode="validation"))
        have = _normalize(got)
        if sorted(want.get("required", [])) != sorted(have.get("required", [])):
            problems.append(f"{tool}: required properties differ")
        wprops, hprops = want.get("properties", {}), have.get("properties", {})
        for name, wp in wprops.items():
            if name not in hprops:
                problems.append(f"{tool}: missing property {name}")
            elif _types(wp) != _types(hprops[name]):
                problems.append(f"{tool}: type of {name} differs")
    return problems


def _jitter(rng: random.Random, base: float) -> float:
    return base * (1.0 + rng.random() * 0.2)


class McpOrganClient:
    """One organ over MCP. ``connector`` builds the SDK client (injected in tests)."""

    served_by: ServedBy = "real"

    def __init__(
        self,
        organ: str,
        endpoint: OrganEndpoint,
        *,
        clock: Clock | None = None,
        seed: int = 0,
        connector: Callable[[], Any] | None = None,
    ) -> None:
        self.organ = organ
        self.endpoint = endpoint
        self.clock = clock or RealClock()
        self._rng = random.Random(seed)
        self._connector = connector or self._default_connector
        self._client: Any = None
        self._tools: dict[str, dict[str, Any]] = {}
        self._compat: Compat = "unknown"
        self._reason: str | None = "not connected yet"
        self._history = CallHistory()
        self._last_check: datetime | None = None
        self._last_error: str | None = None
        self._healthz_degraded = False
        self._stop = asyncio.Event()
        self._connected = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._in_flight = 0
        self.connect_attempts = 0
        self.backoffs: list[float] = []

    # --- connection --------------------------------------------------------------------------
    def _default_connector(self) -> Any:
        from mcp import Client, StdioServerParameters

        ep = self.endpoint
        if ep.transport == "http":
            if not ep.url:
                raise ValueError(f"{self.organ}: http transport needs a url")
            from mcp.client.streamable_http import streamable_http_client

            # One tool result is one SSE event. The SDK caps an event at 1 MiB, but a spoken
            # briefing (WAV, base64) is several MB, so the cap is raised for organ calls.
            transport = streamable_http_client(ep.url, max_sse_event_size=MAX_SSE_EVENT_BYTES)
            return Client(transport, read_timeout_seconds=60, cache=None)
        cmd = ep.command or [sys.executable, "-m", f"stitch_{self.organ}.server", "--stdio"]
        if cmd[0] == "python":
            cmd = [sys.executable, *cmd[1:]]
        params = StdioServerParameters(
            command=cmd[0], args=cmd[1:], env={**os.environ, "STITCH_MODE": "demo", **ep.env}
        )
        return Client(params, read_timeout_seconds=60, cache=None)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._supervise(), name=f"organ-{self.organ}")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def wait_connected(self, timeout_s: float) -> bool:
        with suppress(TimeoutError):
            await wait_for(self.clock, self._connected.wait(), timeout_s)
        return self._connected.is_set()

    async def _supervise(self) -> None:
        step = 0
        while not self._stop.is_set():
            self.connect_attempts += 1
            try:
                client = self._connector()
                async with client:
                    self._client = client
                    await self._discover()
                    self._connected.set()
                    step = 0
                    await self._keepalive()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"connect failed: {type(exc).__name__}"
                self._reason = "not connected"
            finally:
                self._client = None
                self._connected.clear()
            if self._stop.is_set():
                break
            delay = _jitter(self._rng, BACKOFF_STEPS_S[min(step, len(BACKOFF_STEPS_S) - 1)])
            self.backoffs.append(delay)
            step += 1
            await self.clock.sleep(delay)

    async def _discover(self) -> None:
        listed = await self._client.list_tools()
        self._tools = {t.name: dict(t.input_schema) for t in listed.tools}
        problems = compat_problems(self.organ, self._tools)
        self._compat = "incompatible" if problems else "compatible"
        self._reason = "incompatible: " + "; ".join(problems[:3]) if problems else None
        self._last_check = datetime.now(UTC)

    async def _probe(self) -> None:
        """Liveness probe. ``tools/list`` instead of ``ping`` (deprecated in SDK 2.3)."""
        await wait_for(self.clock, self._client.list_tools(), PROBE_TIMEOUT_S)

    async def _keepalive(self) -> None:
        """Probe every 10 s while idle. A probe is skipped while calls are in flight (a
        CPU-bound organ such as the Ledger solver may not answer until its call returns), and
        the session is dropped only after ``PROBE_FAILURES`` consecutive failed probes. Before
        this, one slow probe during a long solve tore down the session and failed the call."""
        misses = 0
        while not self._stop.is_set():
            await self.clock.sleep(PING_INTERVAL_S)
            if self._in_flight > 0:
                continue
            try:
                await self._probe()
                misses = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                misses += 1
                self._last_error = f"liveness probe failed ({misses}/{PROBE_FAILURES})"
                if misses >= PROBE_FAILURES:
                    raise
                continue
            self._last_check = datetime.now(UTC)
            if self.endpoint.healthz_url:
                self._healthz_degraded = not await asyncio.to_thread(
                    _healthz_ok, self.endpoint.healthz_url
                )

    # --- calls -------------------------------------------------------------------------------
    def _breaker_open(self) -> bool:
        h = self.health()
        last = self._history.last_failure_mono
        return (
            h.status == "unwell"
            and h.compat != "incompatible"
            and self._client is not None
            and last is not None
            and self.clock.monotonic() - last < BREAKER_WINDOW_S
        )

    def _fail(self, code: Any, message: str) -> CallOutcome:
        self._history.record(False, self.clock.monotonic())
        self._last_error = message
        return CallOutcome(transport_error=TransportError(code, message))

    async def call_tool(
        self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: CallContext
    ) -> CallOutcome:
        if self._client is None:
            return self._fail("CONNECTION", f"{self.organ} is not connected")
        if self._compat == "incompatible":
            return CallOutcome(transport_error=TransportError("UNAVAILABLE", "incompatible"))
        if self._breaker_open():
            return CallOutcome(transport_error=TransportError("UNAVAILABLE", "circuit open"))
        self._in_flight += 1
        try:
            raw = await self._client.call_tool(tool, args, read_timeout_seconds=timeout_s)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._fail("TIMEOUT", f"{self.organ}.{tool} timed out")
        except Exception as exc:
            return self._fail("PROTOCOL", f"{self.organ}.{tool}: {type(exc).__name__}")
        finally:
            self._in_flight -= 1
        payload = raw.structured_content
        if payload is None and raw.content:
            with suppress(Exception):
                payload = json.loads(raw.content[0].text)
        try:
            result = validate_tool_result(self.organ, tool, payload)
        except ContractViolation as exc:
            self._history.record(False, self.clock.monotonic())
            return CallOutcome(transport_error=TransportError("PROTOCOL", f"contract: {exc}"))
        self._history.record(True, self.clock.monotonic())
        return CallOutcome(result=result, original_sha256=sha256_json(result))

    async def read_resource(self, uri: str, *, timeout_s: float, ctx: CallContext) -> CallOutcome:
        if self._client is None:
            return self._fail("CONNECTION", f"{self.organ} is not connected")
        self._in_flight += 1
        try:
            res = await wait_for(self.clock, self._client.read_resource(uri), timeout_s)
            items = json.loads(res.contents[0].text)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._fail("TIMEOUT", f"{uri} timed out")
        except Exception as exc:
            return self._fail("PROTOCOL", f"{uri}: {type(exc).__name__}")
        finally:
            self._in_flight -= 1
        if isinstance(items, dict) and "items" in items:
            items = items["items"]
        doc = wrap_resource(self.organ, uri, list(items), ctx=ctx)
        try:
            result = validate_tool_result(self.organ, resource_tool(uri), doc)
        except ContractViolation as exc:
            return self._fail("PROTOCOL", f"contract: {exc}")
        self._history.record(True, self.clock.monotonic())
        return CallOutcome(result=result, original_sha256=sha256_json(result))

    async def list_tools(self) -> list[str]:
        return sorted(self._tools)

    def health(self) -> OrganHealth:
        status = health_status(
            disabled=False,
            connected=self._client is not None,
            compat=self._compat,
            failures=self._history.failures,
            healthz_degraded=self._healthz_degraded,
        )
        return OrganHealth(
            organ=self.organ,
            status=status,
            compat=self._compat,
            reason=self._reason if status != "ready" else None,
            served_by="real",
            tools=sorted(self._tools),
            last_check=self._last_check,
            last_error=self._last_error,
            connected=self._client is not None,
        )


def _healthz_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return bool(resp.status == 200)
    except Exception:
        return False
