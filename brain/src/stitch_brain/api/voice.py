"""Voice proxies (contract 8c, design 14). Thin: validate, call the Voice organ, return its
``data`` plus ``served_by``. Voice is never part of a briefing graph. Audio, transcripts and
speak text are never logged. A disabled or unwell Voice organ gives a clean 503
``UPSTREAM_UNAVAILABLE`` with ``details.status`` so the UI can hide the controls."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from stitch_brain.api.errors import ApiException
from stitch_brain.api.runs import RunManager
from stitch_brain.runtime.organs import CallContext, OrganClient
from stitch_brain.runtime.registry import DisabledOrgan, OrganRegistry
from stitch_brain.settings import Settings
from stitch_common.brain_api import (
    SpeakRequest,
    VoiceSpeakResponse,
    VoiceTranscribeRequest,
    VoiceTranscribeResponse,
)

SPEAK_MAX_CHARS = 4000
TIMEOUT_S = 45.0


def _voice(registry: OrganRegistry) -> OrganClient:
    client = registry.get("voice")
    if client is None or isinstance(client, DisabledOrgan):
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "Voice is disabled",
            details={"organ": "voice", "status": "disabled"},
        )
    status = client.health().status
    if status in ("unwell", "disabled"):
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "Voice is unavailable",
            details={"organ": "voice", "status": status},
        )
    return client


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ApiException("INVALID_INPUT", "the body is not JSON", status=400) from None


def _invalid(exc: ValidationError) -> ApiException:
    errors = [
        {"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", ""))[:200]}
        for e in exc.errors()[:10]
    ]
    return ApiException(
        "INVALID_INPUT", "request validation failed", status=422, details={"errors": errors}
    )


async def _call(client: OrganClient, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    ctx = CallContext(f"voice-{uuid.uuid4()}", f"voice.{tool}", 1, "voice")
    out = await client.call_tool(tool, args, timeout_s=TIMEOUT_S, ctx=ctx)
    if out.result is None:
        raise ApiException(
            "UPSTREAM_UNAVAILABLE", "Voice did not answer", details={"organ": "voice"}
        )
    if not out.result.get("ok"):
        err = out.result.get("error") or {}
        code = str(err.get("code", "INTERNAL"))
        if code == "INVALID_INPUT":
            raise ApiException("INVALID_INPUT", str(err.get("message", "invalid input"))[:300])
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "Voice returned an error",
            details={"organ": "voice", "code": code},
        )
    data = out.result.get("data")
    return dict(data) if isinstance(data, dict) else {}


async def transcribe(request: Request, registry: OrganRegistry) -> JSONResponse:
    try:
        body = VoiceTranscribeRequest.model_validate(await _body(request))
    except ValidationError as exc:
        raise _invalid(exc) from None
    client = _voice(registry)
    data = await _call(client, "transcribe", body.model_dump(mode="json", exclude_none=True))
    try:
        resp = VoiceTranscribeResponse.model_validate({**data, "served_by": client.served_by})
    except ValidationError:
        raise ApiException(
            "UPSTREAM_UNAVAILABLE", "Voice returned an invalid result", details={"organ": "voice"}
        ) from None
    return JSONResponse(resp.model_dump(mode="json", exclude_none=True))


def briefing_script(briefing: dict[str, Any], limit: int = SPEAK_MAX_CHARS) -> str:
    """The spoken script: section titles and claim texts in briefing order, cut at a sentence
    boundary under ``limit``. Built only from the stored briefing (every claim has provenance)."""
    parts: list[str] = []
    for sec in briefing.get("sections") or []:
        texts = [str(c.get("text", "")).strip() for c in sec.get("claims") or []]
        texts = [t for t in texts if t]
        if not texts:
            continue
        parts.append(f"{sec.get('title', '')}.")
        parts += texts
    out = ""
    for p in parts:
        cand = f"{out} {p}".strip()
        if len(cand) > limit:
            break
        out = cand
    return out


async def speak(
    request: Request, registry: OrganRegistry, manager: RunManager, settings: Settings
) -> JSONResponse:
    try:
        body = SpeakRequest.model_validate(await _body(request))
    except ValidationError as exc:
        raise _invalid(exc) from None
    if body.text is not None:
        if not settings.allow_arbitrary_tts:
            raise ApiException(
                "INVALID_INPUT",
                "free text is disabled; send briefing_id",
                details={"setting": "STITCH_ALLOW_ARBITRARY_TTS"},
            )
        text = body.text
    else:
        assert body.briefing_id is not None
        state = manager.state(body.briefing_id)
        briefing = state.get("briefing")
        if not briefing:
            raise ApiException(
                "NOT_FOUND",
                "the briefing is not finished",
                details={"reason": "no briefing", "status": state.get("status")},
            )
        if briefing.get("lang") != body.lang:
            raise ApiException(
                "INVALID_INPUT",
                "lang must match the briefing language",
                details={"briefing_lang": briefing.get("lang")},
            )
        text = briefing_script(briefing)
        if not text:
            raise ApiException("NOT_FOUND", "the briefing has no claims to speak")
    client = _voice(registry)
    args: dict[str, Any] = {"text": text, "lang": body.lang}
    if body.voice:
        args["voice"] = body.voice
    if body.format:
        args["format"] = body.format
    data = await _call(client, "speak", args)
    try:
        resp = VoiceSpeakResponse.model_validate({**data, "served_by": client.served_by})
    except ValidationError:
        raise ApiException(
            "UPSTREAM_UNAVAILABLE", "Voice returned an invalid result", details={"organ": "voice"}
        ) from None
    return JSONResponse(resp.model_dump(mode="json", exclude_none=True))


__all__ = ["briefing_script", "speak", "transcribe"]
