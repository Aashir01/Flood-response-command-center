"""Seeded conflict scenarios for the Brain eval and BRN-P6 (brain design 9.5).

A scenario is a set of mutations of the base demo world (organ results by plan node) plus the
rule ids it must raise. Mutators are pure functions of the world and a seeded ``random.Random``.

Default set: 30 scenarios = 6 per rule family (R1, R2, R3; single mutations) + 3 combined
+ 9 negative controls (design 9.5 asks for single, combined and control scenarios; the per-family
count is 6 so the total is 30).
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

World = dict[str, dict[str, Any] | None]
Mutator = Callable[[World, random.Random], None]

BASIN = (
    "pk-sindh-dadu",
    "pk-sindh-jamshoro",
    "pk-sindh-hyderabad",
    "pk-sindh-matiari",
    "pk-sindh-thatta",
    "pk-sindh-tando-muhammad-khan",
)


def _data(world: World, node: str) -> dict[str, Any]:
    res = world[node]
    assert res is not None and res.get("ok"), node
    data: dict[str, Any] = res["data"]
    return data


def oracle_low(world: World, rnd: random.Random) -> None:
    """Every modeled exceedance probability below 0.1 while Eyes stays flooded (expects R1)."""
    for p in _data(world, "oracle.forecast")["exceedance_prob"]:
        p["p_exceed"] = round(rnd.uniform(0.0, 0.099), 3)


#: R1 needs the basin flooded fraction at or above 0.10; a dried district must leave this much
#: so a combined scenario still expects R1 (decisions.md, BRN-P6 root cause).
BASIN_KEEP_FRAC = 0.12


def _area(row: dict[str, Any]) -> float:
    if row.get("district_area_km2") is not None:
        return float(row["district_area_km2"])
    return float(row["flooded_km2"]) / float(row["flooded_fraction"])


def dry_district(world: World, rnd: random.Random) -> None:
    """One basin district mapped dry (flooded fraction below the 0.01 noise floor) while the
    Oracle risk stays high (expects R2; the Ledger re-run with Eyes-only severity reconciles).

    The district keeps its area (written to ``district_area_km2``) and is chosen among basin
    districts whose drying leaves the basin flooded fraction at or above ``BASIN_KEEP_FRAC``,
    so the mutation does not silently cancel R1 in a combined scenario."""
    rows = {r["district_id"]: r for r in _data(world, "eyes.compare")["by_district"]}
    basin = [d for d in BASIN if d in rows]
    area = sum(_area(rows[d]) for d in basin)
    flooded = sum(float(rows[d]["flooded_km2"]) for d in basin)
    keep = [d for d in basin if (flooded - float(rows[d]["flooded_km2"])) / area >= BASIN_KEEP_FRAC]
    district = rnd.choice(keep or basin)
    r = rows[district]
    a = _area(r)
    r["district_area_km2"] = round(a, 1)
    r["flooded_fraction"] = round(rnd.uniform(0.0, 0.0099), 4)
    r["flooded_km2"] = round(r["flooded_fraction"] * a, 1)


def need_mismatch(world: World, rnd: random.Random) -> None:
    """Library water quantity scaled by a factor in [0.5, 0.85] or [1.15, 2] (expects R3)."""
    factor = rnd.uniform(0.5, 0.85) if rnd.random() < 0.5 else rnd.uniform(1.15, 2.0)
    _scale_water(world, factor)


def _scale_water(world: World, factor: float) -> None:
    data = _data(world, "library.water")
    q = data["quantities"][0]
    old = q["value"]
    new = round(old * factor, 1)
    q["value"] = new
    for c in data["claims"]:
        c["text"] = c["text"].replace(f"{old:g} litres", f"{new:g} litres")
    data["answer"] = data["claims"][0]["text"]


def control_oracle_high(world: World, rnd: random.Random) -> None:
    for p in _data(world, "oracle.forecast")["exceedance_prob"]:
        p["p_exceed"] = round(rnd.uniform(0.3, 0.95), 3)


def control_all_flooded(world: World, rnd: random.Random) -> None:
    for r in _data(world, "eyes.compare")["by_district"]:
        r["flooded_fraction"] = max(r["flooded_fraction"], round(rnd.uniform(0.02, 0.4), 3))


def control_need_within_tolerance(world: World, rnd: random.Random) -> None:
    _scale_water(world, rnd.uniform(0.95, 1.05))


@dataclass
class Scenario:
    name: str
    mutators: list[Mutator]
    expects: set[str]
    seed: int
    control: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def apply(self, base: World) -> World:
        world = copy.deepcopy(base)
        rnd = random.Random(self.seed)
        for m in self.mutators:
            m(world, rnd)
        return world


R1, R2, R3 = "R1_oracle_low_eyes_flooded", "R2_ledger_to_dry_district", "R3_library_vs_ledger_need"


def default_scenarios(seed: int = 0, per_family: int = 6) -> list[Scenario]:
    rnd = random.Random(seed)
    out: list[Scenario] = []

    def s() -> int:
        return rnd.randrange(1 << 30)

    for i in range(per_family):
        out.append(Scenario(f"oracle_low_{i}", [oracle_low], {R1}, s()))
        out.append(Scenario(f"dry_district_{i}", [dry_district], {R2}, s()))
        out.append(Scenario(f"need_mismatch_{i}", [need_mismatch], {R3}, s()))
    out.append(Scenario("combo_r1_r2", [oracle_low, dry_district], {R1, R2}, s()))
    out.append(Scenario("combo_r2_r3", [dry_district, need_mismatch], {R2, R3}, s()))
    out.append(Scenario("combo_all", [oracle_low, dry_district, need_mismatch], {R1, R2, R3}, s()))
    controls = [control_oracle_high, control_all_flooded, control_need_within_tolerance]
    for i in range(9):
        out.append(Scenario(f"control_{i}", [controls[i % 3]], set(), s(), control=True))
    return out
