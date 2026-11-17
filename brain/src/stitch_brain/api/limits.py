"""Token-bucket rate limits and request body caps (design 14), as pure ASGI middleware.

Buckets are keyed by (client address, route group). The client address is the socket peer, or
the first ``X-Forwarded-For`` hop when ``STITCH_TRUSTED_PROXY=1`` (behind Caddy). The clock is
injected so tests do not sleep."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stitch_brain.api.errors import error_body
from stitch_common.brain_api import VOICE_TRANSCRIBE_MAX_BODY_BYTES

DEFAULT_MAX_BODY = 64 * 1024
EXEMPT = frozenset({"/healthz"})


@dataclass
class _Bucket:
    tokens: float
    at: float


class TokenBuckets:
    """``limits``: group -> (requests per minute, burst)."""

    def __init__(
        self,
        limits: Mapping[str, tuple[float, int]],
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.limits = dict(limits)
        self.clock = clock
        self.max_keys = max_keys
        self._b: dict[tuple[str, str], _Bucket] = {}

    def take(self, client: str, group: str) -> float | None:
        """Take one token. Returns None when allowed, else the seconds until a token exists."""
        per_min, burst = self.limits.get(group) or self.limits["default"]
        rate = per_min / 60.0
        now = self.clock()
        key = (client, group)
        b = self._b.get(key)
        if b is None:
            if len(self._b) >= self.max_keys:
                self._b.clear()  # bounded memory; a reset only ever makes limits looser
            b = self._b[key] = _Bucket(float(burst), now)
        b.tokens = min(float(burst), b.tokens + (now - b.at) * rate)
        b.at = now
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return None
        return (1.0 - b.tokens) / rate if rate > 0 else 60.0


def route_group(method: str, path: str) -> str:
    if method == "POST" and path.rstrip("/") == "/briefings":
        return "briefings"
    if path.startswith("/ask"):
        return "ask"
    if path.startswith("/voice/"):
        return "voice"
    return "default"


def body_cap(path: str) -> int:
    if path == "/voice/transcribe":
        return VOICE_TRANSCRIBE_MAX_BODY_BYTES
    return DEFAULT_MAX_BODY


def client_key(scope: Scope, trusted_proxy: bool) -> str:
    if trusted_proxy:
        for k, v in scope.get("headers") or []:
            if k == b"x-forwarded-for":
                first = v.decode("latin-1").split(",")[0].strip()
                if first:
                    return str(first)
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


async def _send_json(send: Send, status: int, body: Any, headers: dict[str, str]) -> None:
    raw = json.dumps(body).encode()
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    hdrs += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": raw})


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, buckets: TokenBuckets, trusted_proxy: bool = False) -> None:
        self.app = app
        self.buckets = buckets
        self.trusted_proxy = trusted_proxy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or scope["path"] in EXEMPT:
            await self.app(scope, receive, send)
            return
        group = route_group(scope["method"], scope["path"])
        wait = self.buckets.take(client_key(scope, self.trusted_proxy), group)
        if wait is None:
            await self.app(scope, receive, send)
            return
        retry = str(max(1, math.ceil(wait)))
        body = error_body("RATE_LIMITED", f"too many requests ({group})", {"group": group})
        await _send_json(send, 429, body, {"Retry-After": retry})


class BodyLimitMiddleware:
    """413 for bodies over the route cap, by ``Content-Length`` or while reading a chunked
    body (which is buffered up to the cap and then replayed to the app)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        cap = body_cap(scope["path"])
        too_large = error_body(
            "PAYLOAD_TOO_LARGE", f"request body over {cap} bytes", {"max_bytes": cap}
        )
        for k, v in scope.get("headers") or []:
            if k == b"content-length":
                try:
                    n = int(v)
                except ValueError:
                    n = cap + 1
                if n > cap:
                    await _send_json(send, 413, too_large, {})
                    return
                await self.app(scope, receive, send)
                return
        chunks: list[bytes] = []
        size = 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            chunk = msg.get("body", b"")
            size += len(chunk)
            if size > cap:
                await _send_json(send, 413, too_large, {})
                return
            chunks.append(chunk)
            if not msg.get("more_body", False):
                break
        body = b"".join(chunks)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


__all__ = [
    "BodyLimitMiddleware",
    "RateLimitMiddleware",
    "TokenBuckets",
    "body_cap",
    "client_key",
    "route_group",
]
