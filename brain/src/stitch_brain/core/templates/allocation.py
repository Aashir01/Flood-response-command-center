"""Allocation claims from the final Ledger run (design 5.3)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stitch_brain.core.claims import ClaimDraft, SectionId, Slot, id_token
from stitch_brain.core.evidence import EvidenceEntry
from stitch_brain.core.numbers import to_decimal
from stitch_brain.core.pointer import pointer_for
from stitch_brain.core.templates.common import (
    RenderCtx,
    claim,
    derived,
    find_index,
    leaf,
    lookup_slot,
    sig_decimals,
)
from stitch_common.types import EvidenceRef

TOP_N = 5
LEDGER_FINAL = "ledger.final"
DERIVE_NODE = "derive.ledger_input"


def final_ledger(ctx: RenderCtx) -> EvidenceEntry | None:
    e = ctx.store.by_node(LEDGER_FINAL) or ctx.store.by_node("ledger.optimize")
    return e if e is not None and e.ok else None


def _derive_entry(ctx: RenderCtx, ledger: EvidenceEntry) -> EvidenceEntry | None:
    """The ``derive.ledger_input`` entry whose args produced this Ledger run."""
    node = "derive.ledger_input.eyes_only" if ledger.node_id == "ledger.rerun" else DERIVE_NODE
    return ctx.ok(node) or ctx.ok(DERIVE_NODE)


def _district_name(ctx: RenderCtx, did: str, ledger: EvidenceEntry, row_ptr: list[Any]) -> Slot:
    districts = ctx.ok("ledger.districts")
    if districts is not None:
        items = districts.data().get("items", [])
        j = find_index(items, "district_id", did)
        if j is not None:
            return leaf("district", districts, ["data", "items", j, "name"], "text")
    return leaf("district", ledger, [*row_ptr, "district_id"], "text")


def _commodity_slots(ctx: RenderCtx, derive: EvidenceEntry | None, cid: str) -> dict[str, Slot]:
    if derive is None:
        return {}
    comms = derive.data().get("commodities", [])
    i = find_index(comms, "id", cid)
    if i is None:
        return {}
    return {
        "commodity": leaf(
            "commodity", derive, ["data", "commodities", i, "name", ctx.lang], "text"
        ),
        "unit": lookup_slot("unit", derive, ["data", "commodities", i, "unit"], "unit", ctx.lang),
    }


def _commodity_unit_key(derive: EvidenceEntry | None, cid: str) -> str | None:
    if derive is None:
        return None
    for c in derive.data().get("commodities", []):
        if c.get("id") == cid:
            return str(c.get("unit"))
    return None


def _unreached_ref(ledger: EvidenceEntry, i: int) -> EvidenceRef:
    return ledger.ref(pointer_for(["data", "coverage", i, "unreached_people"]))


def render_allocation(ctx: RenderCtx) -> list[ClaimDraft]:
    ledger = final_ledger(ctx)
    if ledger is None:
        return []
    data = ledger.data()
    derive = _derive_entry(ctx, ledger)
    out: list[ClaimDraft] = []
    sec: SectionId = "allocation"

    # summary
    status = lookup_slot("status", ledger, ["data", "status"], "solver_status", ctx.lang)
    cost = leaf("cost", ledger, ["data", "total_cost"], "int", unit="usd")
    people_raw = to_decimal(data["cost_benefit"]["people_covered"])
    if people_raw > 0:
        slots = {
            "people": leaf(
                "people", ledger, ["data", "cost_benefit", "people_covered"], "int", unit="people"
            ),
            "cpp": leaf(
                "cpp",
                ledger,
                ["data", "cost_benefit", "cost_per_person_covered"],
                "dec",
                decimals=2,
                unit="usd",
            ),
            "cost": cost,
            "status": status,
        }
        out.append(
            claim(
                ctx,
                cid="allocation.summary",
                section=sec,
                kind="number",
                template_id="allocation.summary",
                slots=slots,
                order=0,
            )
        )
    else:
        out.append(
            claim(
                ctx,
                cid="allocation.summary",
                section=sec,
                kind="number",
                template_id="allocation.summary_none",
                slots={"cost": cost, "status": status},
                order=0,
            )
        )
    if data.get("optimality_gap") is not None:
        gap = leaf("gap", ledger, ["data", "optimality_gap"], "pct", decimals=1)
        out.append(
            claim(
                ctx,
                cid="allocation.gap",
                section=sec,
                kind="number",
                template_id="allocation.gap",
                slots={"gap": gap},
                order=1,
            )
        )

    # recommendations per commodity
    rows: list[tuple[int, dict[str, Any]]] = list(enumerate(data.get("allocation", [])))
    order = 10
    for c in ctx.scenario.commodities:
        cslots = _commodity_slots(ctx, derive, c.id)
        if not cslots:
            continue
        unit_key = _commodity_unit_key(derive, c.id)
        mine = [(i, r) for i, r in rows if r["commodity_id"] == c.id and r["quantity"] > 0]
        mine.sort(key=lambda ir: (-float(ir[1]["quantity"]), str(ir[1]["district_id"])))
        for i, r in mine[:TOP_N]:
            row_ptr: list[Any] = ["data", "allocation", i]
            slots = {
                "qty": leaf("qty", ledger, [*row_ptr, "quantity"], "int", unit=unit_key),
                **cslots,
                "district": _district_name(ctx, r["district_id"], ledger, row_ptr),
            }
            cid = f"allocation.{id_token(c.id)}.{id_token(str(r['district_id']))}"
            out.append(
                claim(
                    ctx,
                    cid=cid,
                    section=sec,
                    kind="recommendation",
                    template_id="allocation.line",
                    slots=slots,
                    order=order,
                    extra_refs=[ledger.ref(pointer_for([*row_ptr, "district_id"]))],
                )
            )
            order += 1
        rest = mine[TOP_N:]
        if rest:
            refs = [ledger.ref(pointer_for(["data", "allocation", i, "quantity"])) for i, _ in rest]
            vals = [r["quantity"] for _, r in rest]
            slots = {
                "qty": derived("qty", refs, vals, "sum", "int", unit=unit_key),
                **cslots,
                "n": derived("n", refs, vals, "count", "int"),
            }
            out.append(
                claim(
                    ctx,
                    cid=f"allocation.{id_token(c.id)}.others",
                    section=sec,
                    kind="recommendation",
                    template_id="allocation.others",
                    slots=slots,
                    order=order,
                )
            )
            order += 1

    # people not covered, and districts nobody can reach
    cov = list(enumerate(data.get("coverage", [])))
    unc = [(i, r) for i, r in cov if r["unreached_people"] > 0]
    if unc:
        refs = [
            ledger.ref(pointer_for(["data", "coverage", i, "unreached_people"])) for i, _ in unc
        ]
        vals = [r["unreached_people"] for _, r in unc]
        people = derived("people", refs, vals, "sum", "int", unit="people")
        if people.value != Decimal(0):
            out.append(
                claim(
                    ctx,
                    cid="allocation.uncovered",
                    section=sec,
                    kind="number",
                    template_id="allocation.uncovered",
                    slots={"people": people},
                    order=200,
                )
            )
    unr = [(i, r) for i, r in cov if r["access_mode"] == "unreachable"]
    if unr:
        refs = [
            ledger.ref(pointer_for(["data", "coverage", i, "unreached_people"])) for i, _ in unr
        ]
        vals = [r["unreached_people"] for _, r in unr]
        people = derived("people", refs, vals, "sum", "int", unit="people")
        if people.value != Decimal(0):
            n = derived(
                "n",
                [ledger.ref(pointer_for(["data", "coverage", i, "access_mode"])) for i, _ in unr],
                [r["access_mode"] for _, r in unr],
                "count",
                "int",
            )
            out.append(
                claim(
                    ctx,
                    cid="allocation.unreachable",
                    section=sec,
                    kind="number",
                    template_id="allocation.unreachable",
                    slots={"people": people, "n": n},
                    order=201,
                )
            )

    # equity and shadow prices (sensitivity is optional)
    eq = {
        k: leaf(k, ledger, ["data", "equity", f], "dec", decimals=2)
        for k, f in (
            ("req", "floor_requested"),
            ("app", "floor_applied"),
            ("max", "max_feasible_floor"),
        )
    }
    sens = ctx.ok("ledger.sensitivity") if ledger.node_id == "ledger.optimize" else None
    if sens is not None and sens.data().get("equity_cost") is not None:
        eq["cost"] = leaf("cost", sens, ["data", "equity_cost"], "int")
        out.append(
            claim(
                ctx,
                cid="allocation.equity",
                section=sec,
                kind="statement",
                template_id="allocation.equity",
                slots=eq,
                order=300,
            )
        )
    else:
        out.append(
            claim(
                ctx,
                cid="allocation.equity",
                section=sec,
                kind="statement",
                template_id="allocation.equity_nocost",
                slots=eq,
                order=300,
            )
        )
    if sens is not None:
        prices = sens.data().get("shadow_prices", [])
        for c in ctx.scenario.commodities:
            j = find_index(prices, "constraint", f"supply:{c.id}")
            cslots = _commodity_slots(ctx, derive, c.id)
            if j is None or not prices[j].get("binding") or "commodity" not in cslots:
                continue
            v = to_decimal(prices[j]["value"])
            slots = {
                "commodity": cslots["commodity"],
                "v": leaf(
                    "v",
                    sens,
                    ["data", "shadow_prices", j, "value"],
                    "dec",
                    decimals=sig_decimals(v),
                ),
                "unit": leaf("unit", sens, ["data", "shadow_prices", j, "unit"], "text"),
            }
            out.append(
                claim(
                    ctx,
                    cid=f"allocation.shadow.{id_token(c.id)}",
                    section=sec,
                    kind="number",
                    template_id="allocation.shadow",
                    slots=slots,
                    order=310,
                )
            )
    return out
