"""Severity mapping and the Ledger input (design section 8). Pure functions.

Every parameter is an assumption (``scenarios.yaml``), listed in ``caveat.assumptions``:
``f_noise`` (noise floor of the flooded fraction), ``f_sat`` (flooded fraction that counts as
fully affected), ``lambda`` (maximum severity uplift from forecast risk), ``pi`` (share of a dry,
exposed district treated as at risk), ``kappa`` (road access lost in a fully affected district;
flooded area stands in for flooded roads).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from stitch_brain.config import LangPack, ScenarioCfg, SeverityCfg
from stitch_brain.core.evidence import EvidenceEntry
from stitch_brain.core.numbers import format_number, to_decimal
from stitch_brain.core.plans import ledger_fallback_args
from stitch_brain.core.pointer import pointer_for
from stitch_brain.core.textfmt import render
from stitch_common.types import EvidenceRef

SeverityMode = Literal["full", "eyes_only"]
_Q4 = Decimal("0.0001")


def _d(x: Any) -> Decimal:
    return to_decimal(x) if not isinstance(x, Decimal) else x


@dataclass(frozen=True)
class DistrictBase:
    district_id: str
    population: int
    road_access: Decimal
    alt_delivery_fraction: Decimal
    flooded_fraction: Decimal  # 0 when Eyes has no row for the district
    in_basin: bool


@dataclass(frozen=True)
class DistrictMapped:
    district_id: str
    affected_share: Decimal  # a_d
    population_affected: int
    severity: Decimal
    road_access: Decimal
    alt_delivery_fraction: Decimal


def severity_map(
    districts: Sequence[DistrictBase],
    params: SeverityCfg,
    oracle_risk: Decimal,
    mode: SeverityMode = "full",
) -> list[DistrictMapped]:
    """``a_d``, ``population_affected``, ``severity`` and ``road_access`` per district."""
    f_noise, f_sat = _d(params.f_noise), _d(params.f_sat)
    lam, pi, kappa = _d(params.lambda_), _d(params.pi), _d(params.kappa)
    o_eff = oracle_risk if mode == "full" else Decimal(0)
    out: list[DistrictMapped] = []
    for d in districts:
        ff = d.flooded_fraction
        a = Decimal(0) if ff < f_noise else min(Decimal(1), ff / f_sat)
        b = Decimal(1) if d.in_basin else Decimal(0)
        exposed = pi * o_eff * b
        pop_aff = (Decimal(d.population) * max(a, exposed)).quantize(Decimal(1), ROUND_HALF_UP)
        sev = min(Decimal(1), a + lam * o_eff * b * (1 - a)).quantize(_Q4, ROUND_HALF_UP)
        road = (d.road_access * (1 - kappa * a)).quantize(_Q4, ROUND_HALF_UP)
        out.append(
            DistrictMapped(
                district_id=d.district_id,
                affected_share=a,
                population_affected=min(int(pop_aff), d.population),
                severity=max(Decimal(0), sev),
                road_access=max(Decimal(0), min(d.road_access, road)),
                alt_delivery_fraction=d.alt_delivery_fraction,
            )
        )
    return out


def oracle_risk(forecast: EvidenceEntry | None) -> tuple[Decimal, EvidenceRef | None]:
    """``O`` = max modeled exceedance probability; 0 if unavailable or no threshold."""
    if forecast is None or not forecast.ok:
        return Decimal(0), None
    data = forecast.data()
    if data.get("danger_threshold_m3s") is None:
        return Decimal(0), None
    probs = data.get("exceedance_prob") or []
    if not probs:
        return Decimal(0), None
    i = max(range(len(probs)), key=lambda k: (float(probs[k]["p_exceed"]), -k))
    return _d(probs[i]["p_exceed"]), forecast.ref(
        pointer_for(["data", "exceedance_prob", i, "p_exceed"])
    )


def _assumptions(
    scenario: ScenarioCfg,
    packs: Mapping[str, LangPack],
    notes: Sequence[str],
    mapped: bool,
) -> dict[str, list[str]]:
    p = scenario.severity
    out: dict[str, list[str]] = {}
    for lang, pack in packs.items():
        a = pack.assumptions
        items: list[str] = []
        if mapped:
            items.append(a["intro"])
            items.append(render(a["f_noise"], {"v": format_number(_d(p.f_noise), "pct", 0, lang)}))
            items.append(render(a["f_sat"], {"v": format_number(_d(p.f_sat), "pct", 0, lang)}))
            items.append(render(a["lambda"], {"v": format_number(_d(p.lambda_), "dec", 2, lang)}))
            items.append(render(a["pi"], {"v": format_number(_d(p.pi), "pct", 0, lang)}))
            items.append(render(a["kappa"], {"v": format_number(_d(p.kappa), "pct", 0, lang)}))
        needs: list[str] = []
        unit_tbl = pack.tables.get("unit", {})
        for c in scenario.commodities:
            unit = unit_tbl.get(c.unit, c.unit)
            if c.per_person_need_per_day is not None:
                qty = format_number(_d(c.need(scenario.period_days)), "dec", 1, lang)
                needs.append(
                    render(
                        a["need_item"],
                        {
                            "commodity": c.name.get(lang),
                            "qty": qty,
                            "unit": unit,
                            "days": format_number(Decimal(scenario.period_days), "int", 0, lang),
                        },
                    )
                )
            else:
                qty = format_number(_d(c.need(scenario.period_days)), "dec", 1, lang)
                needs.append(
                    render(
                        a["need_item_total"],
                        {"commodity": c.name.get(lang), "qty": qty, "unit": unit},
                    )
                )
        items.append(render(a["need"], {"items": pack.list_sep.join(needs)}))
        items += [a[n] for n in notes]
        out[lang] = items
    return out


def build_ledger_input(
    scenario: ScenarioCfg,
    *,
    eyes_compare: EvidenceEntry | None,
    oracle_forecast: EvidenceEntry | None,
    districts: EvidenceEntry | None,
    packs: Mapping[str, LangPack],
    mode: SeverityMode = "full",
    request_mode: str = "demo",
) -> dict[str, Any]:
    """Data of the ``derive.ledger_input`` Brain-origin entry, including the exact Ledger
    arguments (``args``), mapping inputs and outputs, assumptions and lineage refs."""
    notes: list[str] = []
    lineage: list[EvidenceRef] = []
    risk, o_ref = oracle_risk(oracle_forecast)
    if o_ref is None:
        notes.append("no_oracle")
    else:
        lineage.append(o_ref)
    commodities = [
        {
            "id": c.id,
            "name": {"en": c.name.en, "ur": c.name.ur},
            "unit": c.unit,
            "unit_cost": c.unit_cost,
            "per_person_need": c.need(scenario.period_days),
            "per_person_need_per_day": c.per_person_need_per_day,
        }
        for c in scenario.commodities
    ]
    args = ledger_fallback_args(scenario, request_mode)
    mapped_rows: list[dict[str, Any]] = []
    missing_from_eyes = 0
    ok_eyes = eyes_compare is not None and eyes_compare.ok
    ok_districts = districts is not None and districts.ok
    if not ok_eyes:
        notes.append("no_eyes")
    elif not ok_districts:
        notes.append("no_districts")
    if ok_eyes and ok_districts:
        assert eyes_compare is not None and districts is not None
        by_district = eyes_compare.data().get("by_district", [])
        ff_index = {str(r["district_id"]): i for i, r in enumerate(by_district)}
        bases: list[DistrictBase] = []
        for j, item in enumerate(districts.data().get("items", [])):
            did = str(item["district_id"])
            i = ff_index.get(did)
            if i is None:
                missing_from_eyes += 1
                ff = Decimal(0)
            else:
                ff = _d(by_district[i]["flooded_fraction"])
                lineage.append(
                    eyes_compare.ref(pointer_for(["data", "by_district", i, "flooded_fraction"]))
                )
            for f in ("population", "road_access", "alt_delivery_fraction"):
                lineage.append(districts.ref(pointer_for(["data", "items", j, f])))
            bases.append(
                DistrictBase(
                    district_id=did,
                    population=int(item["population"]),
                    road_access=_d(item["road_access"]),
                    alt_delivery_fraction=_d(item["alt_delivery_fraction"]),
                    flooded_fraction=ff,
                    in_basin=did in scenario.basin_districts,
                )
            )
        mapped = severity_map(bases, scenario.severity, risk, mode)
        args["districts"] = [
            {
                "district_id": m.district_id,
                "population_affected": m.population_affected,
                "severity": float(m.severity),
                "road_access": float(m.road_access),
                "alt_delivery_fraction": float(m.alt_delivery_fraction),
            }
            for m in mapped
        ]
        mapped_rows = [
            {
                "district_id": b.district_id,
                "population": b.population,
                "flooded_fraction": float(b.flooded_fraction),
                "in_basin": b.in_basin,
                "affected_share": float(m.affected_share),
                "population_affected": m.population_affected,
                "severity": float(m.severity),
                "road_access_base": float(b.road_access),
                "road_access": float(m.road_access),
            }
            for b, m in zip(bases, mapped, strict=True)
        ]
    severity_mode = mode if mapped_rows else "defaults"
    return {
        "severity_mode": severity_mode,
        "args": args,
        "commodities": commodities,
        "period_days": scenario.period_days,
        "params": scenario.severity.model_dump(by_alias=True),
        "oracle_risk": float(risk),
        "districts": mapped_rows,
        "districts_missing_from_eyes": missing_from_eyes,
        "assumptions": _assumptions(scenario, packs, notes, bool(mapped_rows)),
        "lineage": [r.model_dump() for r in lineage],
    }
