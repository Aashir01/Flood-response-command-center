"""The Brain HTTP/SSE API (contract section 8c, design 14). Thin: validation, routing, framing.

``create_app()`` builds everything from the environment. Tests pass their own ``Settings``,
registry and clock instead."""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware

from stitch_brain import BRAIN_VERSION
from stitch_brain.api import voice
from stitch_brain.api.ask import ask as run_ask
from stitch_brain.api.errors import ApiException, install
from stitch_brain.api.limits import BodyLimitMiddleware, RateLimitMiddleware, TokenBuckets
from stitch_brain.api.runs import RunManager
from stitch_brain.config import load_organs, load_scenarios
from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore, ResolvedRef
from stitch_brain.paths import evals_results_dir
from stitch_brain.runtime.llm_steps import default_llm
from stitch_brain.runtime.registry import DisabledOrgan, OrganRegistry
from stitch_brain.runtime.runner import BriefingRunner
from stitch_brain.runtime.store import EventLog, RunStore
from stitch_brain.settings import Settings
from stitch_common import CONTRACT_VERSION
from stitch_common.brain_api import (
    EVIDENCE_MAX_RESPONSE_BYTES,
    SSE_PING_FRAME,
    SSE_PING_INTERVAL_S,
    SSE_RETRY_MS,
    AskRequest,
    AskResponse,
    BrainHealth,
    BriefingAccepted,
    BriefingRequest,
    BriefingState,
    EvidenceValue,
    OrganInfo,
    OrganList,
    format_sse_frame,
)
from stitch_common.logging import get_logger
from stitch_common.types import EvidenceRef

LOG = get_logger("stitch_brain.api")
ORGAN_ORDER = ("eyes", "oracle", "library", "ledger", "voice")


def _llm(settings: Settings) -> Any:
    try:
        return default_llm(settings.llm_provider)
    except Exception as exc:  # a missing key must not stop the demo: templates still work
        LOG.warning(
            "llm_unavailable",
            extra={"provider": settings.llm_provider, "error": type(exc).__name__},
        )
        return None


def build_registry(settings: Settings) -> OrganRegistry:
    cfg = None
    if not settings.recorded_all:
        path = os.environ.get("STITCH_BRAIN_ORGANS_FILE") or None
        try:
            cfg = load_organs(path)
        except Exception as exc:
            LOG.warning("organs_config_unreadable", extra={"error": type(exc).__name__})
    return OrganRegistry.build(settings, cfg)


def organ_infos(registry: OrganRegistry) -> list[OrganInfo]:
    out: list[OrganInfo] = []
    health = registry.health()
    for organ in sorted(health, key=lambda o: ORGAN_ORDER.index(o) if o in ORGAN_ORDER else 99):
        h = health[organ]
        out.append(
            OrganInfo(
                organ=organ,
                status=h.status,
                compat=h.compat,
                reason=h.reason,
                served_by=h.served_by,
                stub=h.served_by == "recorded",
                tools=list(h.tools),
                last_check=h.last_check,
                last_error=h.last_error,
                version=h.version,
                meta=h.meta,
            )
        )
    return out


def live_available(registry: OrganRegistry) -> bool:
    """Live needs the real Eyes and Oracle organs (they fetch upstream data themselves)."""
    for organ in ("eyes", "oracle"):
        c = registry.get(organ)
        if c is None or isinstance(c, DisabledOrgan) or c.served_by != "real":
            return False
        if c.health().status in ("unwell", "disabled"):
            return False
    return True


def _generated_at(entry: EvidenceEntry) -> datetime:
    raw = (entry.result.get("provenance") or {}).get("generated_at")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return entry.ended_at


def _json(obj: Any, status: int = 200) -> Response:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    if len(raw) > EVIDENCE_MAX_RESPONSE_BYTES:
        raise ApiException(
            "PAYLOAD_TOO_LARGE",
            "the evidence value is over 10 MB; request a narrower pointer",
            details={"bytes": len(raw)},
        )
    return Response(raw, status_code=status, media_type="application/json")


def create_app(
    settings: Settings | None = None,
    *,
    registry: OrganRegistry | None = None,
    llm: Any = "default",
    monotonic: Callable[[], float] | None = None,
    ping_interval_s: float = SSE_PING_INTERVAL_S,
) -> FastAPI:
    settings = settings or Settings.from_env()
    reg = registry or build_registry(settings)
    runner = BriefingRunner(reg, settings=settings, llm=_llm(settings) if llm == "default" else llm)
    db = RunStore.open(settings.db_path)
    manager = RunManager(
        runner, db, max_runs=settings.max_runs, run_deadline_s=settings.run_deadline_s
    )
    scenarios = load_scenarios()
    ask_scenario = scenarios.get("demo-sindh-2022") or next(iter(scenarios.values()))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        interrupted = manager._db(db.mark_interrupted, datetime.now(UTC)) or []
        if interrupted:
            LOG.warning("runs_interrupted", extra={"count": len(interrupted)})
        await reg.start()
        try:
            yield
        finally:
            await manager.close()
            await reg.close()
            manager._db(db.close)

    app = FastAPI(
        title="Stitch Brain",
        version=BRAIN_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.registry = reg
    app.state.manager = manager
    app.state.db = db
    install(app)

    # --- briefings ---------------------------------------------------------------------------
    @app.post("/briefings", status_code=202, response_model=BriefingAccepted)
    async def post_briefing(body: BriefingRequest) -> BriefingAccepted:
        run = manager.start(body)
        bid = run.briefing_id
        return BriefingAccepted(
            briefing_id=bid,
            events_url=f"/briefings/{bid}/events",
            result_url=f"/briefings/{bid}",
            task_id=bid,
        )

    @app.get(
        "/briefings/{briefing_id}", response_model=BriefingState, response_model_exclude_none=True
    )
    async def get_briefing(briefing_id: str) -> BriefingState:
        return BriefingState.model_validate(manager.state(briefing_id))

    @app.delete("/briefings/{briefing_id}", status_code=202)
    async def delete_briefing(briefing_id: str) -> dict[str, str]:
        status = manager.cancel(briefing_id)
        return {"briefing_id": briefing_id, "status": status}

    @app.get("/briefings/{briefing_id}/events")
    async def events(
        briefing_id: str,
        last_event_id_q: str | None = Query(default=None, alias="last_event_id"),
        last_event_id_h: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        raw = last_event_id_h if last_event_id_h is not None else last_event_id_q
        after = 0
        if raw is not None and raw.strip() != "":
            try:
                after = max(0, int(raw.strip()))
            except ValueError:
                raise ApiException(
                    "INVALID_INPUT", "Last-Event-ID must be an integer", status=400
                ) from None
        log = manager.event_log(briefing_id)
        return StreamingResponse(
            _sse(log, after, ping_interval_s),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- organs, health, evals -----------------------------------------------------------------
    @app.get("/organs", response_model=OrganList, response_model_exclude_none=True)
    async def organs() -> OrganList:
        return OrganList(
            organs=organ_infos(reg),
            live_available=live_available(reg),
            default_mode="live" if settings.mode == "live" else "demo",
            brain_version=BRAIN_VERSION,
            contract_version=CONTRACT_VERSION,
            llm_provider=settings.llm_provider,
            build_sha=os.environ.get("STITCH_BUILD_SHA") or None,
        )

    @app.get("/healthz", response_model=BrainHealth)
    async def healthz() -> BrainHealth:
        infos = organ_infos(reg)
        ready = sum(1 for o in infos if o.status == "ready")
        enabled = [o for o in infos if o.status != "disabled"]
        db_ok = bool(manager._db(db.ok))
        all_ready = all(o.status == "ready" for o in enabled)
        status = "ok" if db_ok and all_ready and not db.fallback else "degraded"
        return BrainHealth(status=status, organs_ready=ready, db_ok=db_ok)

    @app.get("/evals/latest")
    async def evals_latest() -> Response:
        path = evals_results_dir() / "latest.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"generated_at": None, "organs": {}}
        return _json(data)

    # --- evidence ----------------------------------------------------------------------------
    @app.get("/evidence/{run_id}")
    async def evidence(run_id: str, pointer: str | None = None) -> Response:
        entry = manager.evidence(run_id)
        if entry is None:
            raise ApiException("NOT_FOUND", "unknown run id", details={"reason": "unknown run_id"})
        if pointer is None:
            return _json(entry.result)
        ref = EvidenceRef(run_id=run_id, organ=entry.organ, tool=entry.tool, json_pointer=pointer)
        store = EvidenceStore(entry.briefing_id)
        store.put(entry)
        res = store.resolve(ref)
        if not isinstance(res, ResolvedRef):
            raise ApiException(
                "NOT_FOUND", "the pointer does not resolve", details={"reason": res.reason}
            )
        body = EvidenceValue(
            ref=ref,
            value=res.value,
            organ=entry.organ,
            tool=entry.tool,
            served_by=entry.served_by,
            mode="live" if entry.mode == "live" else "demo",
            generated_at=_generated_at(entry),
            node_id=entry.node_id,
        )
        return _json(body.model_dump(mode="json", exclude_none=True))

    # --- ask ---------------------------------------------------------------------------------
    @app.post("/ask", response_model=AskResponse, response_model_exclude_none=True)
    async def post_ask(body: AskRequest) -> AskResponse:
        resp, store = await run_ask(body, reg, runner.i18n, ask_scenario)
        manager.remember_ask(resp.ask_id, store)
        return resp

    # --- voice -------------------------------------------------------------------------------
    @app.post("/voice/transcribe")
    async def voice_transcribe(request: Request) -> JSONResponse:
        return await voice.transcribe(request, reg)

    @app.post("/voice/speak")
    async def voice_speak(request: Request) -> JSONResponse:
        return await voice.speak(request, reg, manager, settings)

    # Middleware: the last added is the outermost. CORS is outermost so that 413 and 429
    # responses carry CORS headers too.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        buckets=TokenBuckets(settings.rate_limits, monotonic or time.monotonic),
        trusted_proxy=settings.trusted_proxy,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
        allow_credentials=False,
        max_age=600,
    )
    return app


async def _sse(log: EventLog, after: int, ping_s: float) -> AsyncIterator[str]:
    yield f"retry: {SSE_RETRY_MS}\n\n"
    cursor = after
    while True:
        for seq, ev in log.after(cursor):
            yield format_sse_frame(seq, ev)
            cursor = seq
        if log.closed and cursor >= len(log):
            return
        if not await log.wait_beyond(cursor, ping_s):
            yield SSE_PING_FRAME


__all__ = ["create_app", "live_available", "organ_infos"]
