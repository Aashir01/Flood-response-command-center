"""Facts: the only code a conflict rule can invoke (design 9.1). Each fact reads the evidence
store and returns a value with the refs it was read from, or ``Unavailable(reason)``.
Registry-whitelisted; rules name facts, never code."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from stitch_brain.config import ScenarioCfg
from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore
from stitch_brain.core.numbers import to_decimal
from stitch_brain.core.pointer import pointer_for
from stitch_common.types import EvidenceRef


@dataclass(frozen=True)
class Fact:
    value: Decimal
    refs: tuple[EvidenceRef, ...] = ()
    label: str | None = None  # display name of the subject (district or commodity name)


@dataclass(frozen=True)
class Unavailable:
    reason: str


Keyed = dict[str, Fact]
FactValue = Fact | Keyed | Unavailable


@dataclass
class FactCtx:
    store: EvidenceStore
    scenario: ScenarioCfg
    ledger_node: str = "ledger.final"
    trace: list[str] = field(default_factory=list)

    def ok(self, node: str) -> EvidenceEntry | None:
        return self.store.ok_node(node)


@dataclass(frozen=True)
class FactSpec:
    kind: Literal["scalar", "keyed"]
    key: str | None
    fn: Callable[[FactCtx], FactValue]


def oracle_max_exceedance(ctx: FactCtx) -> FactValue:
    fc = ctx.ok("oracle.forecast")
    if fc is None:
        return Unavailable("oracle.forecast unavailable")
    data = fc.data()
    probs = data.get("exceedance_prob") or []
    if data.get("danger_threshold_m3s") is None or not probs:
        return Unavailable("no danger threshold or no exceedance probabilities")
    i = max(range(len(probs)), key=lambda k: (float(probs[k]["p_exceed"]), -k))
    ref = fc.ref(pointer_for(["data", "exceedance_prob", i, "p_exceed"]))
    return Fact(to_decimal(probs[i]["p_exceed"]), (ref,))


def _district_area(row: dict[str, object]) -> Decimal | None:
    area = row.get("district_area_km2")
    if area is not None:
        return to_decimal(area)
    frac = to_decimal(row["flooded_fraction"])
    if frac > 0:
        return to_decimal(row["flooded_km2"]) / frac
    return None


def eyes_basin_flooded_fraction(ctx: FactCtx) -> FactValue:
    cmp_ = ctx.ok("eyes.compare")
    if cmp_ is None:
        return Unavailable("eyes.compare unavailable")
    rows = cmp_.data().get("by_district", [])
    flooded = Decimal(0)
    area = Decimal(0)
    refs: list[EvidenceRef] = []
    for i, r in enumerate(rows):
        if r["district_id"] not in ctx.scenario.basin_districts:
            continue
        a = _district_area(r)
        if a is None or a <= 0:
            continue
        flooded += to_decimal(r["flooded_km2"])
        area += a
        refs.append(cmp_.ref(pointer_for(["data", "by_district", i, "flooded_km2"])))
        key = "district_area_km2" if r.get("district_area_km2") is not None else "flooded_fraction"
        refs.append(cmp_.ref(pointer_for(["data", "by_district", i, key])))
    if area == 0:
        return Unavailable("no basin district with a known area")
    return Fact(flooded / area, tuple(refs))


def eyes_district_flooded_fraction(ctx: FactCtx) -> FactValue:
    cmp_ = ctx.ok("eyes.compare")
    if cmp_ is None:
        return Unavailable("eyes.compare unavailable")
    out: Keyed = {}
    for i, r in enumerate(cmp_.data().get("by_district", [])):
        ref = cmp_.ref(pointer_for(["data", "by_district", i, "flooded_fraction"]))
        out[str(r["district_id"])] = Fact(to_decimal(r["flooded_fraction"]), (ref,), r.get("name"))
    return out


def ledger_allocated_units_by_district(ctx: FactCtx) -> FactValue:
    led = ctx.ok(ctx.ledger_node) or ctx.ok("ledger.optimize")
    if led is None:
        return Unavailable("no Ledger result")
    sums: dict[str, Decimal] = {}
    refs: dict[str, list[EvidenceRef]] = {}
    for i, r in enumerate(led.data().get("allocation", [])):
        q = to_decimal(r["quantity"])
        if q <= 0:
            continue
        did = str(r["district_id"])
        sums[did] = sums.get(did, Decimal(0)) + q
        refs.setdefault(did, []).append(led.ref(pointer_for(["data", "allocation", i, "quantity"])))
    return {k: Fact(v, tuple(refs[k])) for k, v in sums.items()}


_PER_DAY = re.compile(
    r"(per person per day|per person a day|per person each day|per person daily|"
    r"each day|per day|a day|daily|فی شخص فی دن|روزانہ|یومیہ)",
    re.IGNORECASE,
)


def library_guidance_per_person_per_day(ctx: FactCtx) -> FactValue:
    from stitch_brain.core.numbers import UnitTable, scan

    out: Keyed = {}
    for q in ctx.scenario.guidance_questions:
        if q.quantity is None:
            continue
        lib = ctx.ok(f"library.{q.id}")
        if lib is None or lib.data().get("status") != "answered":
            ctx.trace.append(f"library.{q.id}: no answered result")
            continue
        commodity = ctx.scenario.commodity(q.quantity.commodity_id)
        if commodity is None:
            continue
        data = lib.data()
        values: dict[Decimal, list[EvidenceRef]] = {}
        for i, qty in enumerate(data.get("quantities") or []):
            if qty.get("per") == "person_day" and qty.get("unit") == commodity.unit:
                v = to_decimal(qty["value"])
                values.setdefault(v, []).append(lib.ref(pointer_for(["data", "quantities", i])))
        if not values:  # regex fallback over the claim texts (design 9.1)
            units = UnitTable({commodity.unit: q.quantity.units})
            for i, c in enumerate(data.get("claims") or []):
                text = str(c.get("text", ""))
                if not _PER_DAY.search(text):
                    continue
                for tok in scan(text, units).tokens:
                    if tok.unit == commodity.unit and not tok.word:
                        ref = lib.ref(pointer_for(["data", "claims", i, "text"]))
                        values.setdefault(tok.value, []).append(ref)
        if len(values) != 1:
            ctx.trace.append(f"library.{q.id}: {len(values)} distinct quantities, key omitted")
            continue
        ((v, refs),) = values.items()
        out[commodity.id] = Fact(v, tuple(refs), commodity.name.en)
    return out


def ledger_need_per_person_per_day(ctx: FactCtx) -> FactValue:
    derive = ctx.ok("derive.ledger_input")
    if derive is None:
        return Unavailable("derive.ledger_input unavailable")
    out: Keyed = {}
    for i, c in enumerate(derive.data().get("commodities", [])):
        v = c.get("per_person_need_per_day")
        if v is None:
            continue
        ref = derive.ref(pointer_for(["data", "commodities", i, "per_person_need_per_day"]))
        out[str(c["id"])] = Fact(to_decimal(v), (ref,), str(c.get("name", {}).get("en", c["id"])))
    return out


FACTS: dict[str, FactSpec] = {
    "oracle.max_exceedance": FactSpec("scalar", None, oracle_max_exceedance),
    "eyes.basin_flooded_fraction": FactSpec("scalar", None, eyes_basin_flooded_fraction),
    "eyes.district_flooded_fraction": FactSpec(
        "keyed", "district_id", eyes_district_flooded_fraction
    ),
    "ledger.allocated_units_by_district": FactSpec(
        "keyed", "district_id", ledger_allocated_units_by_district
    ),
    "library.guidance_per_person_per_day": FactSpec(
        "keyed", "commodity_id", library_guidance_per_person_per_day
    ),
    "ledger.need_per_person_per_day": FactSpec(
        "keyed", "commodity_id", ledger_need_per_person_per_day
    ),
}
