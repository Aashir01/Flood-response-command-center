"""Flood extent claims from Eyes (design 5.3)."""

from __future__ import annotations

from typing import Any

from stitch_brain.core.claims import ClaimDraft, SectionId, Slot
from stitch_brain.core.templates.common import RenderCtx, claim, derived, fill, leaf

SEC: SectionId = "extent"
TOP_N = 3


def render_extent(ctx: RenderCtx) -> list[ClaimDraft]:
    out: list[ClaimDraft] = []
    cmp_ = ctx.ok("eyes.compare")
    seg = ctx.ok("eyes.segment")
    if cmp_ is not None:
        slots: dict[str, Slot] = {
            "new": leaf("new", cmp_, ["data", "new_flood_km2"], "int", unit="km2"),
            "total": leaf("total", cmp_, ["data", "total_water_km2"], "int", unit="km2"),
            "perm": leaf("perm", cmp_, ["data", "permanent_water_km2"], "int", unit="km2"),
        }
        tid = "extent.flood_area_nodate"
        if seg is not None:
            acq = seg.data()["source_scene"]["acquired"]
            slots["date"] = derived(
                "date", [seg.ref("/data/source_scene/acquired")], [acq], "date_part", "date"
            )
            tid = "extent.flood_area"
        out.append(
            claim(
                ctx,
                cid="extent.flood_area",
                section=SEC,
                kind="number",
                template_id=tid,
                slots=slots,
                order=0,
            )
        )
        rows: list[tuple[int, dict[str, Any]]] = list(enumerate(cmp_.data().get("by_district", [])))
        rows = [r for r in rows if r[1]["flooded_km2"] > 0]
        rows.sort(key=lambda ir: (-float(ir[1]["flooded_km2"]), str(ir[1]["district_id"])))
        top = rows[:TOP_N]
        if top:
            all_slots: dict[str, Slot] = {}
            items: list[str] = []
            for k, (i, _) in enumerate(top, start=1):
                base: list[str | int] = ["data", "by_district", i]
                s = {
                    "name": leaf(f"name{k}", cmp_, [*base, "name"], "text"),
                    "km": leaf(f"km{k}", cmp_, [*base, "flooded_km2"], "int", unit="km2"),
                    "pct": leaf(f"pct{k}", cmp_, [*base, "flooded_fraction"], "pct", decimals=0),
                }
                items.append(fill(ctx, "extent.top_districts.item", s))
                all_slots.update({v.name: v for v in s.values()})
            sep = ctx.i18n.pack(ctx.lang).list_sep
            text = fill(ctx, "extent.top_districts", {}, items=sep.join(items))
            out.append(
                claim(
                    ctx,
                    cid="extent.top_districts",
                    section=SEC,
                    kind="number",
                    template_id="extent.top_districts",
                    slots=all_slots,
                    order=1,
                    text=text,
                )
            )
    if seg is not None:
        if seg.data().get("confidence") is not None:
            out.append(
                claim(
                    ctx,
                    cid="extent.confidence",
                    section=SEC,
                    kind="number",
                    template_id="extent.confidence",
                    slots={"conf": leaf("conf", seg, ["data", "confidence"], "dec", decimals=2)},
                    order=2,
                )
            )
        scene = ["data", "source_scene"]
        slots = {
            "sensor": leaf("sensor", seg, [*scene, "sensor"], "text"),
            "scene_id": leaf("scene_id", seg, [*scene, "scene_id"], "text"),
            "date": derived(
                "date",
                [seg.ref("/data/source_scene/acquired")],
                [seg.data()["source_scene"]["acquired"]],
                "date_part",
                "date",
            ),
        }
        out.append(
            claim(
                ctx,
                cid="extent.scene",
                section=SEC,
                kind="statement",
                template_id="extent.scene",
                slots=slots,
                order=3,
            )
        )
    return out
