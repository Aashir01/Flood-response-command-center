"""Caveat claims (design 5.3, 5.4). Every caveat cites evidence: organ entries, or the
Brain-origin entries ``static.disclaimer``, ``run_meta``, ``derive.ledger_input``, ``conflicts``
and ``critic``."""

from __future__ import annotations

from collections.abc import Iterable

from stitch_brain.core.claims import ClaimDraft, SectionId, Slot, id_token
from stitch_brain.core.evidence import EvidenceEntry
from stitch_brain.core.pointer import pointer_for
from stitch_brain.core.templates.common import RenderCtx, claim, derived, leaf, lookup_slot

RECORDED_PREFIX = "RECORDED_FIXTURE"
#: plan node -> section it feeds (design 7.4)
NODE_SECTION: dict[str, str] = {
    "eyes.segment": "extent",
    "eyes.compare": "extent",
    "oracle.forecast": "forecast",
    "oracle.explain": "forecast",
    "ledger.districts": "allocation",
    "ledger.optimize": "allocation",
    "ledger.sensitivity": "allocation",
    "ledger.rerun": "allocation",
}


def node_section(node_id: str) -> str | None:
    if node_id.startswith("library."):
        return "guidance"
    return NODE_SECTION.get(node_id)


def _joined(
    ctx: RenderCtx,
    entry: EvidenceEntry,
    path: list[str | int],
    items: list[str],
    name: str,
    sep: str,
) -> Slot:
    refs = [entry.ref(pointer_for([*path, i])) for i in range(len(items))]
    return derived(name, refs, items, "join", "text", params={"sep": sep})


def render_caveats_head(ctx: RenderCtx, organ_entries: Iterable[EvidenceEntry]) -> list[ClaimDraft]:
    """Disclaimer, mode, honesty labels, recorded organs and missing organs."""
    out: list[ClaimDraft] = []
    sec: SectionId = "caveats"
    disc = ctx.ok("static.disclaimer")
    if disc is not None:
        out.append(
            claim(
                ctx,
                cid="caveat.disclaimer",
                section=sec,
                kind="statement",
                template_id="caveat.disclaimer",
                slots={"text": leaf("text", disc, ["data", "text", ctx.lang], "text")},
                order=0,
            )
        )
    meta = ctx.ok("run_meta")
    entries = list(organ_entries)
    if meta is not None:
        d = meta.data()
        if d.get("mode_effective") == "live":
            tid, slots = "caveat.mode.live", {}
        else:
            tid = (
                "caveat.mode.fallback" if d.get("mode_requested") == "live" else "caveat.mode.demo"
            )
            slots = {"label": leaf("label", meta, ["data", "label", ctx.lang], "text")}
        refs = [meta.ref("/data/mode_effective")]
        refs += [e.ref("/provenance/mode") for e in entries if e.ok]
        out.append(
            claim(
                ctx,
                cid="caveat.mode",
                section=sec,
                kind="statement",
                template_id=tid,
                slots=slots,
                order=1,
                extra_refs=refs,
            )
        )
    seg = ctx.ok("eyes.segment")
    if seg is not None and seg.data().get("validation", {}).get("validated_for_region") is False:
        slots = {
            "eval_dataset": leaf(
                "eval_dataset", seg, ["data", "validation", "eval_dataset"], "text"
            )
        }
        out.append(
            claim(
                ctx,
                cid="caveat.eyes_unvalidated",
                section=sec,
                kind="statement",
                template_id="caveat.eyes_unvalidated",
                slots=slots,
                order=2,
                extra_refs=[seg.ref("/data/validation/validated_for_region")],
            )
        )
    fc = ctx.ok("oracle.forecast")
    if fc is not None:
        slots = {"label": leaf("label", fc, ["data", "target_label"], "text")}
        out.append(
            claim(
                ctx,
                cid="caveat.oracle_modeled",
                section=sec,
                kind="statement",
                template_id="caveat.oracle_modeled",
                slots=slots,
                order=3,
                extra_refs=[fc.ref("/data/target_kind")],
            )
        )
    seen: set[str] = set()
    for e in entries:
        if e.served_by != "recorded" or not e.ok or e.organ in seen:
            continue
        idx = [
            i
            for i, w in enumerate(e.result.get("warnings") or [])
            if isinstance(w, str) and w.startswith(RECORDED_PREFIX)
        ]
        if not idx:
            continue
        seen.add(e.organ)
        slots = {"organ": lookup_slot("organ", e, ["provenance", "organ"], "organ", ctx.lang)}
        out.append(
            claim(
                ctx,
                cid=f"caveat.recorded.{e.organ}",
                section=sec,
                kind="statement",
                template_id="caveat.recorded",
                slots=slots,
                order=10,
                extra_refs=[e.ref(pointer_for(["warnings", idx[-1]]))],
            )
        )
    for e in entries:
        section = node_section(e.node_id)
        if e.ok or section is None:
            continue
        latest = ctx.store.by_node(e.node_id)
        if latest is not None and latest.call_run_id != e.call_run_id:
            continue  # only the final attempt of a node
        slots = {
            "organ": lookup_slot("organ", e, ["provenance", "organ"], "organ", ctx.lang),
            "code": leaf("code", e, ["error", "code"], "text"),
        }
        out.append(
            claim(
                ctx,
                cid=f"caveat.missing.{id_token(e.node_id)}",
                section=sec,
                kind="statement",
                template_id=f"caveat.missing.{section}",
                slots=slots,
                order=20,
                extra_refs=[e.ref("/error/message")],
            )
        )
    return out


def render_assumptions(ctx: RenderCtx) -> list[ClaimDraft]:
    derive = ctx.ok("derive.ledger_input")
    if derive is None:
        return []
    items = list(derive.data().get("assumptions", {}).get(ctx.lang, []))
    if not items:
        return []
    slot = _joined(ctx, derive, ["data", "assumptions", ctx.lang], items, "items", "; ")
    return [
        claim(
            ctx,
            cid="caveat.assumptions",
            section="caveats",
            kind="statement",
            template_id="caveat.assumptions",
            slots={"items": slot},
            order=30,
        )
    ]
