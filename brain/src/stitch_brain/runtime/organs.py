"""Organ clients: protocol, call outcomes, health (design 3.1, 3.2).

``CallOutcome`` is either a ToolResult document (validated against ``stitch_common``) or a
transport error. A recorded organ and a real MCP organ implement the same protocol; which one
serves an organ is decided by configuration (``STITCH_RECORDED_ORGANS``), never by failover.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from stitch_brain.core.evidence import det_uuid
from stitch_common import CONTRACT_VERSION
from stitch_common.provenance import inputs_hash

ServedBy = Literal["real", "recorded"]
HealthStatus = Literal["ready", "degraded", "unwell", "disabled"]
Compat = Literal["compatible", "incompatible", "unknown"]


@dataclass(frozen=True)
class CallContext:
    """What a call needs besides its arguments. Recorded organs use it to match fixtures and to
    derive deterministic run ids; real organs ignore it."""

    briefing_id: str
    node_id: str
    attempt: int
    scenario: str  # fixture set key


@dataclass(frozen=True)
class TransportError:
    code: Literal["TIMEOUT", "CONNECTION", "PROTOCOL", "UNAVAILABLE"]
    message: str


@dataclass(frozen=True)
class CallOutcome:
    result: dict[str, Any] | None = None  # ToolResult JSON
    transport_error: TransportError | None = None
    original_sha256: str | None = None
    source: str | None = None  # fixture path for recorded results


@dataclass
class OrganHealth:
    organ: str
    status: HealthStatus = "unwell"
    compat: Compat = "unknown"
    reason: str | None = None
    served_by: ServedBy = "real"
    tools: list[str] = field(default_factory=list)
    last_check: datetime | None = None
    last_error: str | None = None
    version: str | None = None
    connected: bool = False
    meta: dict[str, Any] | None = None


class OrganClient(Protocol):
    organ: str
    served_by: ServedBy

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def list_tools(self) -> list[str]: ...
    async def call_tool(
        self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: CallContext
    ) -> CallOutcome: ...
    async def read_resource(
        self, uri: str, *, timeout_s: float, ctx: CallContext
    ) -> CallOutcome: ...
    def health(self) -> OrganHealth: ...


class CallHistory:
    """Last five call outcomes, for the health state table (design 3.2)."""

    def __init__(self) -> None:
        self._last: deque[bool] = deque(maxlen=5)
        self.last_failure_mono: float | None = None

    def record(self, ok: bool, mono: float) -> None:
        self._last.append(ok)
        if not ok:
            self.last_failure_mono = mono

    @property
    def failures(self) -> int:
        return sum(1 for x in self._last if not x)


def health_status(
    *, disabled: bool, connected: bool, compat: Compat, failures: int, healthz_degraded: bool
) -> HealthStatus:
    """The state table of design 3.2."""
    if disabled:
        return "disabled"
    if not connected or compat == "incompatible" or failures >= 3:
        return "unwell"
    if failures >= 1 or healthz_degraded:
        return "degraded"
    return "ready"


def resource_tool(uri: str) -> str:
    """``ledger://scenario/x/districts`` -> ``resource:districts``."""
    tail = uri.rstrip("/").rsplit("/", 1)[-1]
    return f"resource:{tail}"


def wrap_resource(
    organ: str, uri: str, items: list[Any], *, mode: str = "demo", ctx: CallContext | None = None
) -> dict[str, Any]:
    """Wrap resource contents as a ToolResult-shaped document so pointers work uniformly."""
    rid = det_uuid(ctx.briefing_id, ctx.node_id, str(ctx.attempt), uri) if ctx else det_uuid(uri)
    return {
        "ok": True,
        "data": {"uri": uri, "items": items},
        "error": None,
        "provenance": {
            "organ": organ,
            "tool": resource_tool(uri),
            "tool_version": "resource",
            "contract_version": CONTRACT_VERSION,
            "run_id": rid,
            "inputs_hash": inputs_hash({"uri": uri}),
            "mode": mode,
            "data_sources": [],
            "model": None,
            "models": [],
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "warnings": [],
    }
