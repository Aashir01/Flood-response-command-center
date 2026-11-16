"""Guidance claims from Library answers and refusals (design 5.4, 5.5).

Each answered Library claim becomes one verbatim guidance claim citing its own text and every
citation in ``citation_idx``. A claim with an empty or out-of-range ``citation_idx`` is not
rendered and is reported. A refusal renders as a refusal: the Brain never fills it in."""

from __future__ import annotations

from stitch_brain.core.claims import ClaimDraft, SectionId, id_token
from stitch_brain.core.evidence import EvidenceEntry
from stitch_brain.core.pointer import pointer_for
from stitch_brain.core.templates.common import RenderCtx, claim, leaf, lookup_slot

SEC: SectionId = "guidance"


def _inputs_entry(ctx: RenderCtx, node_id: str) -> tuple[EvidenceEntry, list[str | int]] | None:
    for meta_node in ("run_meta", "ask.input"):
        meta = ctx.ok(meta_node)
        if meta is None:
            continue
        inputs = meta.data().get("call_inputs", {})
        if node_id in inputs and "query" in inputs[node_id]:
            return meta, ["data", "call_inputs", node_id, "query"]
    return None


def render_library_result(
    ctx: RenderCtx, entry: EvidenceEntry, qid: str, order_base: int = 0
) -> list[ClaimDraft]:
    data = entry.data()
    out: list[ClaimDraft] = []
    if data.get("status") == "answered":
        n_cit = len(data.get("citations") or [])
        for i, c in enumerate(data.get("claims") or []):
            cid = f"guidance.{id_token(qid)}.{i}"
            idx = [j for j in c.get("citation_idx") or [] if isinstance(j, int)]
            if not idx or any(j < 0 or j >= n_cit for j in idx):
                ctx.issues.append(f"{cid}: C4 citation_idx empty or out of range")
                continue
            text = leaf("text", entry, ["data", "claims", i, "text"], "text")
            cites = [entry.ref(pointer_for(["data", "citations", j])) for j in idx]
            out.append(
                claim(
                    ctx,
                    cid=cid,
                    section=SEC,
                    kind="statement",
                    template_id="guidance.claim",
                    slots={"text": text},
                    order=order_base + i,
                    extra_refs=cites,
                    text=str(text.value),
                    verbatim=True,
                )
            )
    elif data.get("status") == "refused" and data.get("refusal"):
        reason = lookup_slot("reason", entry, ["data", "refusal", "reason"], "refusal", ctx.lang)
        slots = {"reason": reason}
        q = _inputs_entry(ctx, entry.node_id)
        if q is not None:
            slots["query"] = leaf("query", q[0], q[1], "text")
        hits = data["refusal"].get("closest_hits") or []
        extra = [
            entry.ref(pointer_for(["data", "refusal", "closest_hits", j])) for j in range(len(hits))
        ]
        extra.append(entry.ref("/data/status"))
        if "query" not in slots:
            ctx.issues.append(f"guidance.{qid}.refusal: query unavailable")
            return out
        out.append(
            claim(
                ctx,
                cid=f"guidance.{id_token(qid)}.refusal",
                section=SEC,
                kind="statement",
                template_id="guidance.refusal",
                slots=slots,
                order=order_base + 50,
                extra_refs=extra,
            )
        )
    return out


def render_guidance(ctx: RenderCtx) -> list[ClaimDraft]:
    out: list[ClaimDraft] = []
    for k, q in enumerate(ctx.scenario.guidance_questions):
        entry = ctx.ok(f"library.{q.id}")
        if entry is not None:
            out += render_library_result(ctx, entry, q.id, order_base=100 * k)
    return out
