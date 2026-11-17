"""Claude (Anthropic) and OpenAI adapters.

SDKs are optional extras (``stitch-common[anthropic]``, ``stitch-common[openai]``) and are
imported lazily on the first call, so the base install and the tests need neither. Keys come
only from the provider's own environment variable (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``)
and are never logged. Every failure (no key, SDK missing, timeout, HTTP or API error) becomes
``LLMUnavailable``. Tests inject a fake SDK client through ``sdk_client``; nothing here is
exercised against a real provider outside ``@pytest.mark.live`` tests.
"""

from __future__ import annotations

import importlib
import json
import os
import time
from typing import Any

from stitch_common.llm.base import (
    BaseLLMClient,
    LLMRequest,
    LLMResponse,
    LLMUnavailable,
    prompt_key,
)

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _json_instruction(schema: dict[str, Any]) -> str:
    return (
        "\n\nReply with one JSON object only, no prose and no code fences. "
        "It must validate against this JSON Schema:\n" + json.dumps(schema, sort_keys=True)
    )


def _import_sdk(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise LLMUnavailable(
            f"the {name!r} SDK is not installed (install stitch-common[{name}])"
        ) from exc


class ClaudeClient(BaseLLMClient):
    provider = "anthropic"

    def __init__(
        self, model: str | None = None, *, api_key: str | None = None, sdk_client: Any = None
    ) -> None:
        self.model = model or os.environ.get("STITCH_LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL
        self._api_key = api_key
        self._sdk_client = sdk_client

    def _client(self, timeout_s: float) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        key = self._api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        sdk = _import_sdk("anthropic")
        return sdk.Anthropic(api_key=key, timeout=timeout_s, max_retries=1)

    def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
        client = self._client(timeout_s)
        system = req.system + (
            _json_instruction(req.response_format) if req.response_format else ""
        )
        t0 = time.perf_counter()
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                system=system,
                messages=[m.model_dump() for m in req.messages],
                timeout=timeout_s,
            )
            text = "".join(
                str(getattr(b, "text", ""))
                for b in resp.content
                if getattr(b, "type", "") == "text"
            )
            usage = getattr(resp, "usage", None)
            counts = {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            }
        except LLMUnavailable:
            raise
        except Exception as exc:  # SDK error types are not importable without the SDK
            raise LLMUnavailable(f"anthropic call failed: {type(exc).__name__}") from exc
        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            usage=counts,
            latency_s=time.perf_counter() - t0,
            key=prompt_key(req),
        )


class OpenAIClient(BaseLLMClient):
    provider = "openai"
    key_env = "OPENAI_API_KEY"
    default_model = DEFAULT_OPENAI_MODEL
    base_url: str | None = None  # None means the SDK default (api.openai.com)

    def __init__(
        self, model: str | None = None, *, api_key: str | None = None, sdk_client: Any = None
    ) -> None:
        self.model = model or os.environ.get("STITCH_LLM_MODEL") or self.default_model
        self._api_key = api_key
        self._sdk_client = sdk_client

    def _base_url(self) -> str | None:
        return self.base_url

    def _client(self, timeout_s: float) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        key = self._api_key or os.environ.get(self.key_env)
        if not key:
            raise LLMUnavailable(f"{self.key_env} is not set")
        sdk = _import_sdk("openai")
        kwargs: dict[str, Any] = {"api_key": key, "timeout": timeout_s, "max_retries": 1}
        base_url = self._base_url()
        if base_url:
            kwargs["base_url"] = base_url
        return sdk.OpenAI(**kwargs)

    def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
        client = self._client(timeout_s)
        kwargs: dict[str, Any] = {}
        if req.response_format:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": req.response_format, "strict": False},
            }
        kwargs = self._request_kwargs(req, kwargs)
        system = req.system
        if req.response_format is not None and self._schema_in_prompt(req):
            system += _json_instruction(req.response_format)
        messages = [{"role": "system", "content": system}] + [m.model_dump() for m in req.messages]
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=req.temperature,
                timeout=timeout_s,
                **kwargs,
            )
            text = str(resp.choices[0].message.content or "")
            usage = getattr(resp, "usage", None)
            counts = {
                "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            }
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(f"{self.provider} call failed: {type(exc).__name__}") from exc
        return LLMResponse(
            text=_strip_think(text),
            provider=self.provider,
            model=self.model,
            usage=counts,
            latency_s=time.perf_counter() - t0,
            key=prompt_key(req),
        )

    def _request_kwargs(self, req: LLMRequest, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {**kwargs, "max_completion_tokens": req.max_tokens}

    def _schema_in_prompt(self, req: LLMRequest) -> bool:
        return False


DEFAULT_NEBIUS_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


class NebiusClient(OpenAIClient):
    """Nebius Token Factory through its OpenAI-compatible API.

    Differences from OpenAI handled here: the base URL (``NEBIUS_BASE_URL`` env overrides it),
    the key variable ``NEBIUS_API_KEY``, ``max_tokens`` instead of ``max_completion_tokens``,
    and ``response_format.json_schema`` as ``{name, schema}`` (a bare schema is a 422). Nebius
    recommends also stating the schema in the prompt, so it is appended to the system message.
    Model ids are Hugging Face style (``STITCH_LLM_MODEL``, default ``DEFAULT_NEBIUS_MODEL``).
    """

    provider = "nebius"
    key_env = "NEBIUS_API_KEY"
    default_model = DEFAULT_NEBIUS_MODEL

    def _base_url(self) -> str | None:
        return os.environ.get("NEBIUS_BASE_URL") or NEBIUS_BASE_URL

    def _request_kwargs(self, req: LLMRequest, kwargs: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"max_tokens": req.max_tokens}
        if req.response_format:
            out["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": req.response_format},
            }
        return out

    def _schema_in_prompt(self, req: LLMRequest) -> bool:
        return req.response_format is not None


def _strip_think(text: str) -> str:
    """Drop a leading ``<think>...</think>`` block that reasoning models may emit."""
    stripped = text.lstrip()
    if stripped.startswith("<think>") and "</think>" in stripped:
        return stripped.split("</think>", 1)[1].lstrip()
    return text
