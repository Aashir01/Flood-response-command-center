"""Request and response models, the ``LLMClient`` protocol, errors and the replay key."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from stitch_common.provenance import canonical_json

Role = Literal["user", "assistant"]


class LLMUnavailable(Exception):
    """The provider cannot answer: no key, SDK missing, timeout, HTTP error, no recording.

    Callers catch this one type and take their deterministic fallback.
    """


class RecordingMissing(LLMUnavailable):
    """``FakeLLM`` has no recording for the request key (``.key`` holds it)."""

    def __init__(self, key: str, purpose: str) -> None:
        super().__init__(f"no recording for key {key[:12]}... (purpose={purpose})")
        self.key = key
        self.purpose = purpose


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    content: str


class LLMRequest(BaseModel):
    """One completion request. Deterministic content only (no timestamps or run ids)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: str = Field(min_length=1)  # e.g. "library.answer", "brain.phrase"; part of the key
    system: str
    messages: tuple[Message, ...] = Field(min_length=1)
    max_tokens: int = Field(default=700, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # JSON Schema of the expected JSON reply. Adapters request structured output where the
    # provider supports it. Callers must still validate the reply themselves.
    response_format: dict[str, Any] | None = None
    # Explicit replay key. When unset, ``prompt_key`` hashes the request.
    cache_key: str | None = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    provider: str  # "anthropic" | "openai" | "nebius" | "fake"
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    latency_s: float = 0.0
    key: str  # prompt_key of the request


MessagesArg = str | Sequence[Message | Mapping[str, str]]


def to_messages(messages: MessagesArg) -> tuple[Message, ...]:
    """Accept a plain user string, ``Message`` objects or ``{"role", "content"}`` dicts."""
    if isinstance(messages, str):
        return (Message(role="user", content=messages),)
    out: list[Message] = []
    for m in messages:
        out.append(m if isinstance(m, Message) else Message.model_validate(dict(m)))
    return tuple(out)


def prompt_key(req: LLMRequest) -> str:
    """Stable replay key.

    ``req.cache_key`` when set; otherwise ``sha256(canonical_json({purpose, system, messages,
    schema, max_tokens, temperature}))``. Provider and model are not part of the key, so a
    recording made with one provider replays under ``fake``.
    """
    if req.cache_key:
        return req.cache_key
    payload = {
        "purpose": req.purpose,
        "system": req.system,
        "messages": [m.model_dump() for m in req.messages],
        "schema": req.response_format,
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic client. Every method raises ``LLMUnavailable`` on any failure."""

    provider: str
    model: str

    def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse: ...

    def complete(
        self,
        messages: MessagesArg,
        *,
        system: str,
        max_tokens: int = 700,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
        purpose: str = "generic",
        cache_key: str | None = None,
        timeout_s: float = 30.0,
    ) -> LLMResponse: ...

    async def agenerate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse: ...


class BaseLLMClient:
    """Implements ``complete`` and ``agenerate`` on top of a subclass's ``generate``."""

    provider: str = "base"
    model: str = "none"

    def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
        raise NotImplementedError

    def complete(
        self,
        messages: MessagesArg,
        *,
        system: str,
        max_tokens: int = 700,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
        purpose: str = "generic",
        cache_key: str | None = None,
        timeout_s: float = 30.0,
    ) -> LLMResponse:
        req = LLMRequest(
            purpose=purpose,
            system=system,
            messages=to_messages(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            cache_key=cache_key,
        )
        return self.generate(req, timeout_s=timeout_s)

    async def agenerate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
        return await asyncio.to_thread(self.generate, req, timeout_s=timeout_s)
