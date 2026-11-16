"""Brain HTTP/SSE API models (mcp-contracts.md section 8c), added in contract v0.4.

These are browser-facing models, not MCP tools. The Brain implements them and the frontend
consumes them. Every model forbids unknown fields. SSE frames carry a ``TaskEvent`` in ``data``;
the ``payload`` shapes per event type are defined here as documentation-grade models, and the
Brain validates its own payloads against them in tests.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from stitch_common.base import Contract
from stitch_common.brain import Briefing, Claim, Conflict, OrganStatus, ServedBy, TaskEvent
from stitch_common.envelope import ErrorInfo, ToolResult
from stitch_common.organs.library import AnswerWithCitationsOut
from stitch_common.organs.voice import SpeakOut, TranscribeIn, TranscribeOut
from stitch_common.types import EvidenceRef, Lang, LangOrAuto, Mode, OrganName, Slug

# --- limits and protocol constants (section 8c) ------------------------------------------------
SSE_RETRY_MS = 2000
SSE_PING_INTERVAL_S = 15
SSE_PING_FRAME = ": ping\n\n"
VOICE_TRANSCRIBE_MAX_BODY_BYTES = 4 * 1024 * 1024  # 60 s of 16 kHz mono WAV is about 2.6 MB b64
EVIDENCE_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # larger responses return 413
ASK_QUESTION_MAX_CHARS = 500

# --- errors ------------------------------------------------------------------------------------
ApiErrorCode = Literal[
    "INVALID_INPUT",
    "NOT_FOUND",
    "RATE_LIMITED",
    "BUSY",
    "CANCELLED",
    "PAYLOAD_TOO_LARGE",
    "UPSTREAM_UNAVAILABLE",
    "INTERNAL",
]


class ApiErrorBody(Contract):
    code: ApiErrorCode
    message: str
    details: dict[str, Any] | None = None


class ApiError(Contract):
    """Body of every non-2xx Brain response, including 429 and 413."""

    error: ApiErrorBody


# --- briefings ---------------------------------------------------------------------------------
class BriefingRequest(Contract):
    """``POST /briefings`` body. ``region`` and ``scenario`` must exist in the Brain's config."""

    region: Slug = Field(max_length=64)
    scenario: str = Field(min_length=1, max_length=64)
    lang: Lang = "en"
    mode: Mode = "demo"


class BriefingAccepted(Contract):
    """``POST /briefings`` 202 body. ``task_id`` equals ``briefing_id`` (frontend alias)."""

    briefing_id: str = Field(min_length=1)
    status: Literal["running"] = "running"
    events_url: str
    result_url: str
    task_id: str | None = None


BriefingRunStatus = Literal["running", "done", "failed", "cancelled"]


class BriefingState(Contract):
    """``GET /briefings/{id}`` body. ``DELETE /briefings/{id}`` is an idempotent cancel (202)."""

    briefing_id: str = Field(min_length=1)
    status: BriefingRunStatus
    request: BriefingRequest
    created_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    briefing: Briefing | None = None
    error: ApiErrorBody | None = None


# --- organs and health -------------------------------------------------------------------------
class VoiceOrganMeta(Contract):
    """``OrganInfo.meta`` for Voice, copied from the Voice organ's ``/healthz``."""

    capabilities: list[Literal["speak", "transcribe"]]
    tts_provider: str
    hosted: bool
    whisper_model: str | None = None


class OrganInfo(Contract):
    """One organ in ``GET /organs``. ``status`` has five values: ``incompatible`` is also a
    ``compat`` flag, and the frontend accepts either spelling."""

    organ: OrganName
    status: OrganStatus
    compat: Literal["compatible", "incompatible", "unknown"] | None = None
    reason: str | None = None
    served_by: ServedBy | None = None
    stub: bool = False
    tools: list[str] = Field(default_factory=list)
    last_check: AwareDatetime | None = None
    last_error: str | None = None
    version: str | None = None
    meta: dict[str, Any] | None = None


class OrganList(Contract):
    organs: list[OrganInfo]
    live_available: bool
    default_mode: Mode
    brain_version: str
    contract_version: str
    llm_provider: str | None = None
    build_sha: str | None = None


class BrainHealth(Contract):
    """``GET /healthz`` on the Brain."""

    status: Literal["ok", "degraded"]
    organs_ready: int = Field(ge=0)
    db_ok: bool


# --- evidence ----------------------------------------------------------------------------------
class EvidenceValue(Contract):
    """``GET /evidence/{run_id}?pointer=<RFC 6901>``: one resolved value."""

    ref: EvidenceRef
    value: Any
    organ: str
    tool: str
    served_by: Literal["real", "recorded", "brain"]
    mode: Mode
    generated_at: AwareDatetime
    node_id: str | None = None


#: ``GET /evidence/{run_id}`` without ``pointer`` returns the full stored ``ToolResult``.
EvidenceResult = ToolResult[dict[str, Any]]


# --- ask ---------------------------------------------------------------------------------------
class AskRequest(Contract):
    question: str = Field(min_length=1, max_length=ASK_QUESTION_MAX_CHARS)
    lang: LangOrAuto = "auto"


class AskResponse(Contract):
    """``POST /ask``. ``claims`` carry provenance like briefing claims; ``result`` is the full
    Library ToolResult for the UI. Both come from the same single Library call."""

    ask_id: str = Field(min_length=1)
    status: Literal["answered", "refused"]
    claims: list[Claim]
    refusal_claim: Claim | None = None
    mode: Mode
    library_run_id: str = Field(min_length=1)
    result: ToolResult[AnswerWithCitationsOut] | None = None


# --- voice proxy -------------------------------------------------------------------------------
class SpeakRequest(Contract):
    """``POST /voice/speak``. Exactly one of ``briefing_id`` (the Brain builds the script from
    the stored briefing) or ``text`` (only when ``STITCH_ALLOW_ARBITRARY_TTS=1``)."""

    briefing_id: str | None = Field(default=None, min_length=1)
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    lang: Lang
    voice: str | None = None
    format: Literal["wav", "mp3"] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SpeakRequest:
        if (self.briefing_id is None) == (self.text is None):
            raise ValueError("exactly one of briefing_id and text is required")
        return self


class VoiceSpeakResponse(SpeakOut):
    served_by: ServedBy


class VoiceTranscribeRequest(TranscribeIn):
    """Same as the Voice tool input. The JSON body is capped at 4 MB on this route."""


class VoiceTranscribeResponse(TranscribeOut):
    served_by: ServedBy


# --- SSE event payloads (``TaskEvent.payload`` per event type) ----------------------------------
class PlanNode(Contract):
    id: str = Field(min_length=1)
    kind: str
    organ: str | None = None
    tool: str | None = None
    deps: list[str] = Field(default_factory=list)
    optional: bool = False


class PlanPayload(Contract):
    plan_id: str
    revision: int = Field(ge=0)
    planner: str
    scenario: str
    lang: Lang
    mode_requested: Mode
    nodes: list[PlanNode]
    stub_organs: list[str] = Field(default_factory=list)
    added: list[str] | None = None


class OrganCallPayload(Contract):
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    timeout_s: float = Field(gt=0.0)
    served_by: ServedBy
    started_at: AwareDatetime


class OrganResultPayload(Contract):
    ok: bool
    attempt: int = Field(ge=1)
    duration_ms: float = Field(ge=0.0)
    served_by: ServedBy
    run_id: str = Field(min_length=1)  # call-level; usable with GET /evidence/{run_id}
    mode: Mode
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    summary: dict[str, Any] = Field(default_factory=dict)  # at most 10 scalar fields of data

    @model_validator(mode="after")
    def _checks(self) -> OrganResultPayload:
        if len(self.summary) > 10:
            raise ValueError("summary holds at most 10 fields")
        if any(isinstance(v, dict | list) for v in self.summary.values()):
            raise ValueError("summary values must be scalars")
        if self.ok == (self.error is not None):
            raise ValueError("error is required iff ok is false")
        return self


#: ``conflict`` event payload is the contract ``Conflict`` (with its v0.4 fields).
ConflictPayload = Conflict


class CriticIssue(Contract):
    claim_id: str
    check: str
    detail: str


class CriticPayload(Contract):
    model_config = ConfigDict(populate_by_name=True)

    pass_no: int = Field(alias="pass", ge=1)
    passed: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    reverted: list[str] = Field(default_factory=list)


#: ``briefing`` event payload is the full ``Briefing``.
BriefingPayload = Briefing


class ErrorPayload(Contract):
    """``error`` event. ``fatal: true`` is the last event of a run (failure or cancellation)."""

    code: str
    message: str
    fatal: bool
    retryable: bool = False


class NoticePayload(Contract):
    """``notice`` event: a non-fatal fallback, for example ``MODE_FALLBACK`` (live to demo)."""

    code: str
    message: str
    details: dict[str, Any] | None = None


EVENT_PAYLOADS: dict[str, type[Contract]] = {
    "plan": PlanPayload,
    "organ_call": OrganCallPayload,
    "organ_result": OrganResultPayload,
    "conflict": Conflict,
    "critic": CriticPayload,
    "briefing": Briefing,
    "error": ErrorPayload,
    "notice": NoticePayload,
}


def validate_event_payload(event: TaskEvent) -> Contract:
    """Validate ``event.payload`` against the model for its type (raises ``ValidationError``)."""
    return EVENT_PAYLOADS[event.event].model_validate(event.payload)


def format_sse_frame(seq: int, event: TaskEvent) -> str:
    """One SSE frame: ``id`` (per-run integer from 1), ``event`` (type), ``data`` (TaskEvent)."""
    if seq < 1:
        raise ValueError("SSE id starts at 1")
    data = json.dumps(
        event.model_dump(mode="json", exclude_none=True), separators=(",", ":"), ensure_ascii=False
    )
    return f"id: {seq}\nevent: {event.event}\ndata: {data}\n\n"


#: Models exported as ``brain_api.<name>.json`` schemas (serialization mode).
API_MODELS: dict[str, type[Contract]] = {
    "api_error": ApiError,
    "briefing_request": BriefingRequest,
    "briefing_accepted": BriefingAccepted,
    "briefing_state": BriefingState,
    "organ_list": OrganList,
    "brain_health": BrainHealth,
    "evidence_value": EvidenceValue,
    "ask_request": AskRequest,
    "ask_response": AskResponse,
    "speak_request": SpeakRequest,
    "voice_speak_response": VoiceSpeakResponse,
    "voice_transcribe_response": VoiceTranscribeResponse,
    **{f"payload_{k}": v for k, v in EVENT_PAYLOADS.items() if k not in ("conflict", "briefing")},
}
