"""``POST /ask`` (design 14, BRN-R14, BRN-P21): one Library call, rendered like guidance.

Only ``library.answer_with_citations`` is called. Claims are the Library's own text with
citation refs (or the refusal template), with no phrasing or translation, and they pass the
same provenance checks as briefing claims (C1 refs resolve, C4 guidance cites a quote)."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

from stitch_brain.api.errors import ApiException
from stitch_brain.config import I18n, ScenarioCfg
from stitch_brain.core.briefing import labels_for
from stitch_brain.core.checks import claim_issues
from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore, brain_entry, sha256_json
from stitch_brain.core.templates.common import RenderCtx
from stitch_brain.core.templates.guidance import render_library_result
from stitch_brain.runtime.organs import CallContext
from stitch_brain.runtime.registry import DisabledOrgan, OrganRegistry
from stitch_common.brain_api import AskRequest, AskResponse

ASK_NODE = "ask.library"
ASK_FIXTURE_SET = "ask"
ASK_TIMEOUT_S = 25.0
_URDU = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


def clean_question(text: str) -> str:
    """Strip control characters (keeps letters, marks, spaces) and surrounding whitespace."""
    out = "".join(
        " " if ch in "\t\r\n" else ch for ch in text if unicodedata.category(ch)[0] != "C"
    )
    out = re.sub(r"\s+", " ", out).strip()
    if not out:
        raise ApiException("INVALID_INPUT", "question is empty after removing control characters")
    return out


def detect_lang(text: str) -> str:
    return "ur" if _URDU.search(text) else "en"


async def ask(
    req: AskRequest,
    registry: OrganRegistry,
    i18n: I18n,
    scenario: ScenarioCfg,
) -> tuple[AskResponse, EvidenceStore]:
    question = clean_question(req.question)
    lang = detect_lang(question) if req.lang == "auto" else req.lang
    client = registry.get("library")
    health = client.health() if client is not None else None
    if client is None or isinstance(client, DisabledOrgan) or health is None:
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "the Library is disabled",
            details={"organ": "library", "status": "disabled"},
        )
    if health.status in ("unwell", "disabled"):
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "the Library is unavailable",
            details={"organ": "library", "status": health.status},
        )
    ask_id = str(uuid.uuid4())
    args: dict[str, Any] = {"query": question, "lang": req.lang, "answer_lang": lang}
    ctx = CallContext(ask_id, ASK_NODE, 1, ASK_FIXTURE_SET)
    started = datetime.now(UTC)
    out = await client.call_tool("answer_with_citations", args, timeout_s=ASK_TIMEOUT_S, ctx=ctx)
    if out.result is None:
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "the Library did not answer",
            details={
                "organ": "library",
                "reason": out.transport_error.code if out.transport_error else None,
            },
        )
    result = out.result
    if not result.get("ok"):
        err = result.get("error") or {}
        code = str(err.get("code", "INTERNAL"))
        if code == "INVALID_INPUT":
            raise ApiException("INVALID_INPUT", str(err.get("message", "invalid question"))[:300])
        raise ApiException(
            "UPSTREAM_UNAVAILABLE",
            "the Library returned an error",
            details={"organ": "library", "code": code},
        )
    store = EvidenceStore(ask_id)
    entry = store.put(
        EvidenceEntry(
            call_run_id=str(result["provenance"]["run_id"]),
            briefing_id=ask_id,
            node_id=ASK_NODE,
            organ="library",
            tool="answer_with_citations",
            served_by=client.served_by,
            started_at=started,
            ended_at=datetime.now(UTC),
            result=result,
            original_sha256=out.original_sha256 or sha256_json(result),
            source=out.source,
        )
    )
    store.put(
        brain_entry(
            briefing_id=ask_id,
            node_id="ask.input",
            tool="ask.input",
            data={"call_inputs": {ASK_NODE: {"query": question}}},
            mode=entry.mode,
        )
    )
    rctx = RenderCtx(store=store, scenario=scenario, i18n=i18n, lang=lang)
    drafts = render_library_result(rctx, entry, "ask")
    kept = []
    for d in drafts:
        checks = {i.check for i in claim_issues(d, store, i18n, lang)}
        if checks & {"C1", "C4"}:
            continue  # same provenance gate as the briefing critic; never repaired
        d.labels = labels_for(d, store, False)
        kept.append(d)
    status = entry.data().get("status")
    claims = [d.to_contract() for d in kept if d.template_id != "guidance.refusal"]
    refusal = next((d.to_contract() for d in kept if d.template_id == "guidance.refusal"), None)
    if status == "answered" and not claims:
        status = "refused"  # nothing traceable is left: show the refusal state, never fill in
    resp = AskResponse(
        ask_id=ask_id,
        status="answered" if status == "answered" else "refused",
        claims=claims,
        refusal_claim=refusal,
        mode="live" if entry.mode == "live" else "demo",
        library_run_id=entry.call_run_id,
        result=result,
    )
    return resp, store


__all__ = ["ask", "clean_question", "detect_lang"]
