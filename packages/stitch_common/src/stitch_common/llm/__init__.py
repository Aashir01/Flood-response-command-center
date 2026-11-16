"""Provider-agnostic LLM client shared by the Library and the Brain.

API (everything below is importable from ``stitch_common.llm``):

* ``LLMRequest(purpose, system, messages, max_tokens=700, temperature=0.0,
  response_format=None, cache_key=None)``: frozen request. ``response_format`` is a JSON Schema
  for structured replies (callers still validate the reply). ``purpose`` names the step, e.g.
  ``"library.answer"`` or ``"brain.phrase"``.
* ``LLMResponse(text, provider, model, usage, latency_s, key)``.
* ``LLMClient`` protocol: ``generate(req, *, timeout_s=30) -> LLMResponse``,
  ``complete(messages, *, system, max_tokens=700, temperature=0, response_format=None,
  purpose="generic", cache_key=None, timeout_s=30) -> LLMResponse`` (``messages`` is a string,
  ``Message`` objects or role/content dicts) and ``async agenerate(req, *, timeout_s=30)``.
* Errors: every failure raises ``LLMUnavailable``. ``RecordingMissing`` (a subclass, carries
  ``.key``) is raised by ``FakeLLM`` on a replay miss. Catch ``LLMUnavailable`` to fall back.
* ``prompt_key(req)``: ``req.cache_key`` if set, else ``sha256(canonical_json({purpose,
  system, messages, schema, max_tokens, temperature}))``. Provider and model are not in the key.
* ``FakeLLM(recordings=None, *, mode="replay", responder=None, unavailable=False)``:
  ``recordings`` is a JSONL file, a directory of ``*.jsonl`` files or a list of either. Test
  modes: ``adversarial``, ``garbage``, ``echo_injection``.
* ``RecordingLLM(inner, path)``: records real exchanges for later replay
  (``python -m stitch_common.llm.recording check|keys FILE``).
* ``ClaudeClient``, ``OpenAIClient``: lazy SDK import (extras ``stitch-common[anthropic]``,
  ``stitch-common[openai]``), key from ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``, model from
  ``STITCH_LLM_MODEL`` or the default.
* ``get_llm_client(provider=None, *, recordings=None, model=None)``: provider from
  ``STITCH_LLM_PROVIDER`` (``fake`` default, ``anthropic``, ``openai``). For ``fake``,
  ``recordings`` defaults to ``STITCH_LLM_RECORDINGS`` (``os.pathsep``-separated paths).

Nothing in this package calls the network at import time. Tests never use the real adapters.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from stitch_common.llm.adapters import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    ClaudeClient,
    OpenAIClient,
)
from stitch_common.llm.base import (
    BaseLLMClient,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMUnavailable,
    Message,
    RecordingMissing,
    prompt_key,
    to_messages,
)
from stitch_common.llm.fake import FakeLLM, Recording, default_recording_paths, load_recordings
from stitch_common.llm.recording import RecordingLLM, stale_keys

PROVIDERS = ("fake", "anthropic", "openai")


def provider_name(provider: str | None = None) -> str:
    """Normalized provider name from the argument or ``STITCH_LLM_PROVIDER`` (default fake)."""
    name = (provider or os.environ.get("STITCH_LLM_PROVIDER") or "fake").strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"unknown STITCH_LLM_PROVIDER {name!r}; expected one of {PROVIDERS}")
    return name


def get_llm_client(
    provider: str | None = None,
    *,
    recordings: Path | str | Iterable[Path | str] | None = None,
    model: str | None = None,
) -> LLMClient:
    """Build the configured client. Construction never touches the network or needs a key."""
    name = provider_name(provider)
    if name == "anthropic":
        return ClaudeClient(model)
    if name == "openai":
        return OpenAIClient(model)
    return FakeLLM(recordings if recordings is not None else default_recording_paths())


__all__ = [
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "PROVIDERS",
    "BaseLLMClient",
    "ClaudeClient",
    "FakeLLM",
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "LLMUnavailable",
    "Message",
    "OpenAIClient",
    "Recording",
    "RecordingLLM",
    "RecordingMissing",
    "default_recording_paths",
    "get_llm_client",
    "load_recordings",
    "prompt_key",
    "provider_name",
    "stale_keys",
    "to_messages",
]
