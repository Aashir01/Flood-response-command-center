# ruff: noqa: RUF001
"""Write the Brain's hand-authored recorded fixtures for Eyes, Oracle and Library.

    uv run python scripts/build_brain_fixtures.py

These organs are not available as real servers for the demo yet (Eyes, Oracle) or need
Postgres (Library), so the Brain demo and tests replay these files. Every value below is an
ILLUSTRATIVE DEMO VALUE chosen by hand, not a model output, an observation or a quotation
checked against a document page:

* Eyes: per-district flooded fractions for Sindh are hand-picked to resemble the pattern of the
  2022 floods (high on the right-bank districts, low in Karachi and Tharparkar). District areas
  come from ``data/demo/ledger/districts.parquet``. Geometry is a small square per flooded
  district, marked ``synthetic`` in its properties.
* Oracle: a seven-day modeled discharge curve and exceedance probabilities for the Indus near
  Kotri. The danger threshold is illustrative.
* Library: answers and quotes paraphrase well-known Sphere Handbook 2018 minimum standards. Page
  numbers are not verified. The real Library replaces these whenever it runs.

Every result lists the data source ``fixture-hand-authored``; the Brain labels every recorded
result in the briefing. Run ``scripts/record_organ_fixture.py`` afterwards to re-capture the
Ledger fixtures, whose arguments depend on these Eyes and Oracle values.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "demo" / "recorded"
HAND = {
    "id": "fixture-hand-authored",
    "name": "Hand-authored Brain demo fixture (illustrative values)",
    "license": "MIT (Stitch)",
    "as_of": None,
}
GEN_AT = "2026-11-17T00:00:00Z"
CONTRACT = "0.4"

#: flooded fraction of district area (illustrative, design 8 inputs)
FLOODED: dict[str, float] = {
    "pk-sindh-badin": 0.12,
    "pk-sindh-dadu": 0.28,
    "pk-sindh-ghotki": 0.05,
    "pk-sindh-hyderabad": 0.04,
    "pk-sindh-jacobabad": 0.22,
    "pk-sindh-jamshoro": 0.19,
    "pk-sindh-karachi": 0.004,
    "pk-sindh-kashmore": 0.09,
    "pk-sindh-khairpur": 0.21,
    "pk-sindh-matiari": 0.06,
    "pk-sindh-mirpur-khas": 0.11,
    "pk-sindh-naushahro-feroze": 0.14,
    "pk-sindh-nawabshah": 0.13,
    "pk-sindh-qambar-shahdadkot": 0.31,
    "pk-sindh-sanghar": 0.16,
    "pk-sindh-shikarpur": 0.15,
    "pk-sindh-sukkur": 0.07,
    "pk-sindh-tando-allahyar": 0.08,
    "pk-sindh-tando-muhammad-khan": 0.07,
    "pk-sindh-tharparkar": 0.006,
    "pk-sindh-thatta": 0.05,
    "pk-sindh-umerkot": 0.03,
}
#: seeded conflict (design 9.5): a basin district mapped dry while the Oracle risk is high
CONFLICT_DRY = "pk-sindh-thatta"
PERMANENT_SHARE = 0.08  # share of detected water that is permanent (illustrative)


def run_id(*parts: str) -> str:
    h = bytearray(hashlib.sha256("/".join(parts).encode()).digest()[:16])
    h[6] = (h[6] & 0x0F) | 0x40
    h[8] = (h[8] & 0x3F) | 0x80
    x = h.hex()
    return f"{x[:8]}-{x[8:12]}-{x[12:16]}-{x[16:20]}-{x[20:]}"


def prov(organ: str, tool: str, key: str, inputs: dict[str, Any]) -> dict[str, Any]:
    canon = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "organ": organ,
        "tool": tool,
        "tool_version": "fixture",
        "contract_version": CONTRACT,
        "run_id": run_id(organ, tool, key),
        "inputs_hash": hashlib.sha256(canon.encode()).hexdigest(),
        "mode": "demo",
        "data_sources": [HAND],
        "model": None,
        "models": [],
        "generated_at": GEN_AT,
    }


def ok(organ: str, tool: str, key: str, inputs: dict[str, Any], data: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "error": None,
        "provenance": prov(organ, tool, key, inputs),
        "warnings": ["hand-authored demo fixture: illustrative values, not a model output"],
    }


def write(organ: str, tool: str, name: str, match: dict[str, Any], result: dict[str, Any]) -> None:
    path = OUT / organ / tool / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "match": match,
        "authoring": "hand_authored",
        "captured_from": {"script": "scripts/build_brain_fixtures.py"},
        "result": result,
    }
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(REPO).as_posix()}")


def districts() -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = pq.read_table(
        REPO / "data/demo/ledger/districts.parquet"
    ).to_pylist()
    return rows


def centroids() -> dict[str, tuple[float, float]]:
    g = json.loads((REPO / "data/demo/boundaries/pk_districts.geojson").read_text(encoding="utf-8"))
    out: dict[str, tuple[float, float]] = {}
    for f in g["features"]:
        ring = f["geometry"]["coordinates"][0]
        if f["geometry"]["type"] == "MultiPolygon":
            ring = f["geometry"]["coordinates"][0][0]
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        out[f["properties"]["district_id"]] = (sum(xs) / len(xs), sum(ys) / len(ys))
    return out


def eyes(fset: str, flooded: dict[str, float]) -> None:
    rows = districts()
    cents = centroids()
    by = []
    feats = []
    for r in rows:
        ff = flooded[r["district_id"]]
        area = round(r["area_km2"], 1)
        km = round(area * ff, 1)
        by.append(
            {
                "district_id": r["district_id"],
                "name": r["name"],
                "flooded_km2": km,
                "flooded_fraction": ff,
                "district_area_km2": area,
            }
        )
        if ff >= 0.05 and r["district_id"] in cents:
            x, y = cents[r["district_id"]]
            h = 0.25 * ff**0.5
            feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "district_id": r["district_id"],
                        "synthetic": True,
                        "note": "hand-authored illustrative shape, not a segmentation",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [round(x - h, 4), round(y - h, 4)],
                                [round(x + h, 4), round(y - h, 4)],
                                [round(x + h, 4), round(y + h, 4)],
                                [round(x - h, 4), round(y + h, 4)],
                                [round(x - h, 4), round(y - h, 4)],
                            ]
                        ],
                    },
                }
            )
    new = round(sum(b["flooded_km2"] for b in by), 1)
    perm = round(new * PERMANENT_SHARE / (1 - PERMANENT_SHARE), 1)
    args = {"region_id": "pk-sindh", "date": "2022-08-30"}
    compare = {
        "total_water_km2": round(new + perm, 1),
        "permanent_water_km2": perm,
        "new_flood_km2": new,
        "by_district": by,
    }
    write(
        "eyes",
        "compare_with_permanent_water",
        fset,
        {"scenario": fset, "args": args},
        ok("eyes", "compare_with_permanent_water", fset, args, compare),
    )
    seg = {
        "flood_extent_km2": new,
        "extent_geojson": {"type": "FeatureCollection", "features": feats},
        "permanent_water_km2": perm,
        "confidence": 0.82,
        "tiles_processed": 64,
        "source_scene": {
            "sensor": "Sentinel-1 IW GRD",
            "acquired": "2022-08-30T13:41:00Z",
            "scene_id": "demo-s1-sindh-20220830",
        },
        "validation": {
            "validated_for_region": False,
            "eval_dataset": "sen1floods11_test",
            "note": "Demo scene. Validated on the Sen1Floods11 test split only.",
        },
        "reference_overlay_geojson": None,
        "valid_fraction": 0.97,
    }
    write(
        "eyes",
        "segment_flood",
        fset,
        {"scenario": fset, "args": args},
        ok("eyes", "segment_flood", fset, args, seg),
    )


def oracle() -> None:
    p50 = [11800, 13200, 14600, 15900, 16400, 15700, 14300]
    days = [f"2022-08-{d:02d}" for d in range(26, 33)]
    days[-1] = "2022-09-01"
    forecast = []
    for i, (d, m) in enumerate(zip(days, p50, strict=True)):
        w = 0.12 + 0.03 * i
        forecast.append(
            {
                "date": d,
                "lead_days": i + 1,
                "discharge": {"p10": round(m * (1 - w)), "p50": m, "p90": round(m * (1 + w))},
            }
        )
    thr = 14000.0
    pex = [0.08, 0.31, 0.58, 0.74, 0.79, 0.69, 0.52]
    args = {"station_id": "indus-kotri", "horizon_days": 7, "as_of": "2022-08-25"}
    data = {
        "station_id": "indus-kotri",
        "unit": "m3/s",
        "as_of": "2022-08-25",
        "target_kind": "modeled_glofas",
        "target_label": "Modeled river discharge (GloFAS via Open-Meteo)",
        "forecast": forecast,
        "danger_threshold_m3s": thr,
        "exceedance_prob": [{"date": d, "p_exceed": p} for d, p in zip(days, pex, strict=True)],
        "calibration": {
            "method": "split_conformal",
            "nominal_coverage": 0.8,
            "n_calibration": 412,
            "interval_lower_q": 0.1,
            "interval_upper_q": 0.9,
        },
        "station": {
            "name": "Indus near Kotri",
            "river": "Indus",
            "cell_lat": 25.375,
            "cell_lon": 68.325,
            "requested_lat": 25.37,
            "requested_lon": 68.31,
        },
        "quantile_correction_applied": False,
    }
    write(
        "oracle",
        "forecast_river",
        "indus-kotri-2022-08-25",
        {"args": args},
        ok("oracle", "forecast_river", "kotri", args, data),
    )
    rel = "data/demo/recorded/oracle/forecast_river/indus-kotri-2022-08-25.json"
    explain = {
        "drivers": [
            {
                "feature": "upstream_discharge_sukkur_lag2",
                "contribution_m3s": 2100.0,
                "direction": "up",
                "feature_group": "upstream",
            },
            {
                "feature": "rain_7d_basin",
                "contribution_m3s": 900.0,
                "direction": "up",
                "feature_group": "rainfall",
            },
            {
                "feature": "day_of_year",
                "contribution_m3s": -350.0,
                "direction": "down",
                "feature_group": "season",
            },
        ],
        "narrative": "Upstream modeled discharge near Sukkur and recent basin rainfall push the "
        "forecast up; the seasonal baseline pulls it down slightly.",
        "baseline_m3s": 13750.0,
        "lead_days_explained": 4,
    }
    write(
        "oracle",
        "explain_forecast",
        "indus-kotri-2022-08-25",
        {"run_id_of": rel, "args": {}},
        ok("oracle", "explain_forecast", "kotri-explain", {"run_id": "fixture"}, explain),
    )


def citation(doc: str, title: str, page: int, quote: str, lang: str = "en") -> dict[str, Any]:
    return {
        "doc_id": doc,
        "title": title,
        "publisher": "Sphere Association",
        "page": page,
        "span": [0, len(quote)],
        "quote": quote,
        "lang": lang,
        "url": None,
    }


SPHERE = "The Sphere Handbook 2018 (hand-authored demo fixture)"


def library() -> None:
    gen = {"mode": "extractive", "provider": "fixture", "model": None}
    qs = {
        "water": (
            "How much drinking water does each person need per day in a flood emergency?",
            "سیلاب کی ہنگامی صورتحال میں ہر شخص کو روزانہ کتنا پینے کا پانی چاہیے؟",
        ),
        "food": (
            "What food ration should displaced flood-affected families receive?",
            "سیلاب سے بے گھر خاندانوں کو کتنا خوراک کا راشن ملنا چاہیے؟",
        ),
        "shelter": (
            "What emergency shelter should be provided to families displaced by floods?",
            "سیلاب سے بے گھر خاندانوں کو کیسی ہنگامی پناہ گاہ دی جائے؟",
        ),
    }

    def water(litres: str, value: float, key: str, lang: str = "en") -> dict[str, Any]:
        if lang == "ur":
            text = (
                "پینے، کھانا پکانے اور ذاتی صفائی کے لیے ہر شخص کو روزانہ کم از کم "
                f"{litres} لیٹر پانی درکار ہے۔"
            )
            quote = f"کم از کم {litres} لیٹر فی شخص فی دن"
        else:
            text = (
                f"Each person needs at least {litres} litres of water per day for drinking, "
                "cooking and personal hygiene."
            )
            quote = (
                f"Average volume of water used for drinking and domestic hygiene per "
                f"household: minimum {litres} litres per person per day"
            )
        args = {"query": qs["water"][1 if lang == "ur" else 0], "answer_lang": lang}
        return ok(
            "library",
            "answer_with_citations",
            key,
            args,
            {
                "status": "answered",
                "answer": text,
                "citations": [citation("fixture-sphere-2018", SPHERE, 106, quote, lang)],
                "refusal": None,
                "claims": [{"text": text, "citation_idx": [0]}],
                "generation": gen,
                "quantities": [
                    {"value": value, "unit": "litre", "per": "person_day", "claim_idx": 0}
                ],
            },
        )

    for lang in ("en", "ur"):
        q = qs["water"][1 if lang == "ur" else 0]
        write(
            "library",
            "answer_with_citations",
            f"water-{lang}",
            {"args": {"query": q, "answer_lang": lang}},
            water("15", 15.0, f"water-{lang}", lang),
        )
    q = qs["water"][0]
    write(
        "library",
        "answer_with_citations",
        "water-en-conflicts",
        {"scenario": "demo-sindh-2022-conflicts", "args": {"query": q, "answer_lang": "en"}},
        water("7.5", 7.5, "water-conflicts"),
    )
    q = qs["water"][1]
    write(
        "library",
        "answer_with_citations",
        "water-ur-conflicts",
        {"scenario": "demo-sindh-2022-conflicts", "args": {"query": q, "answer_lang": "ur"}},
        water("7.5", 7.5, "water-conflicts-ur", "ur"),
    )
    food_text = (
        "A general food ration should provide at least 2,100 kcal per person per day, "
        "with protein and fat in the planned ration."
    )
    food_quote = (
        "The average requirement is 2,100 kcal per person per day, with 10 to 12 per "
        "cent of total energy from protein and 17 per cent from fat."
    )
    for lang in ("en", "ur"):
        args = {"query": qs["food"][1 if lang == "ur" else 0], "answer_lang": lang}
        write(
            "library",
            "answer_with_citations",
            f"food-{lang}",
            {"args": args},
            ok(
                "library",
                "answer_with_citations",
                f"food-{lang}",
                args,
                {
                    "status": "answered",
                    "answer": food_text,
                    "citations": [citation("fixture-sphere-2018", SPHERE, 199, food_quote)],
                    "refusal": None,
                    "claims": [{"text": food_text, "citation_idx": [0]}],
                    "generation": gen,
                    "quantities": [],
                },
            ),
        )
        args = {"query": qs["shelter"][1 if lang == "ur" else 0], "answer_lang": lang}
        hit = citation(
            "fixture-sphere-2018",
            SPHERE,
            246,
            "Shelter and settlement responses aim to provide a safe and secure living environment.",
        )
        write(
            "library",
            "answer_with_citations",
            f"shelter-{lang}",
            {"args": args},
            ok(
                "library",
                "answer_with_citations",
                f"shelter-{lang}",
                args,
                {
                    "status": "refused",
                    "answer": None,
                    "citations": [],
                    "refusal": {"reason": "INSUFFICIENT_EVIDENCE", "closest_hits": [hit]},
                    "claims": [],
                    "generation": gen,
                    "quantities": [],
                },
            ),
        )


def main() -> int:
    eyes("demo-sindh-2022", FLOODED)
    eyes("demo-sindh-2022-conflicts", {**FLOODED, CONFLICT_DRY: 0.004})
    oracle()
    library()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
