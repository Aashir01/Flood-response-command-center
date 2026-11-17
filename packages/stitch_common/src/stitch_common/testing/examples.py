"""Valid example payloads for every contract model (JSON-compatible dicts).

``TOOL_EXAMPLES["ledger.optimize_allocation"] == (input_dict, output_dict)``. Organ tests and the
organ template reuse these for contract tests.
"""

from __future__ import annotations

from typing import Any

FC: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[67.0, 26.0], [67.1, 26.0], [67.1, 26.1], [67.0, 26.0]]],
            },
        }
    ],
}

CITATION: dict[str, Any] = {
    "doc_id": "ndma-2022-01",
    "title": "Flood contingency plan",
    "publisher": "NDMA",
    "page": 3,
    "span": [10, 80],
    "quote": "Evacuate households within 500 m of the embankment.",
    "lang": "en",
    "url": None,
}

PROVENANCE: dict[str, Any] = {
    "organ": "ledger",
    "tool": "optimize_allocation",
    "tool_version": "0.1.0",
    "contract_version": "0.5",
    "run_id": "2f5e2b0e-6b36-4b3c-8a55-5d7a1f2f9c11",
    "inputs_hash": "0" * 64,
    "mode": "demo",
    "data_sources": [{"id": "demo", "name": "Demo", "license": "CC0", "as_of": "2022-08-30"}],
    "model": None,
    "generated_at": "2026-01-01T00:00:00Z",
}

EVIDENCE: dict[str, Any] = {
    "run_id": "r1",
    "organ": "ledger",
    "tool": "optimize_allocation",
    "json_pointer": "/data/total_coverage",
}

TOOL_EXAMPLES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "eyes.segment_flood": (
        {"region_id": "pk-sindh", "date": "2022-08-30"},
        {
            "flood_extent_km2": 120.5,
            "extent_geojson": FC,
            "permanent_water_km2": 20.0,
            "confidence": 0.82,
            "tiles_processed": 16,
            "source_scene": {
                "sensor": "Sentinel-1",
                "acquired": "2022-08-30T01:00:00Z",
                "scene_id": "S1A_demo",
            },
            "validation": {
                "validated_for_region": False,
                "eval_dataset": "sen1floods11_test",
                "note": "Demo scene, not validated for Sindh.",
            },
            "reference_overlay_geojson": None,
        },
    ),
    "eyes.compare_with_permanent_water": (
        {"region_id": "pk-sindh", "date": "2022-08-30", "bbox": [66.0, 25.0, 69.0, 28.0]},
        {
            "total_water_km2": 140.5,
            "permanent_water_km2": 20.0,
            "new_flood_km2": 120.5,
            "by_district": [
                {"district_id": "d1", "name": "Dadu", "flooded_km2": 60.0, "flooded_fraction": 0.3}
            ],
        },
    ),
    "oracle.forecast_river": (
        {"station_id": "guddu", "horizon_days": 3},
        {
            "station_id": "guddu",
            "unit": "m3/s",
            "as_of": "2022-08-30",
            "target_kind": "modeled_glofas",
            "target_label": "Modeled river discharge (GloFAS via Open-Meteo)",
            "forecast": [
                {
                    "date": "2022-08-31",
                    "lead_days": 1,
                    "discharge": {"p10": 900.0, "p50": 1000.0, "p90": 1200.0},
                    "rainfall_mm": {"p10": 0.0, "p50": 2.0, "p90": 8.0},
                }
            ],
            "danger_threshold_m3s": 1100.0,
            "exceedance_prob": [{"date": "2022-08-31", "p_exceed": 0.4}],
            "calibration": {
                "method": "split_conformal",
                "nominal_coverage": 0.8,
                "n_calibration": 200,
            },
        },
    ),
    "oracle.explain_forecast": (
        {"run_id": "r1"},
        {
            "drivers": [{"feature": "rain_3d", "contribution_m3s": 120.0, "direction": "up"}],
            "narrative": "Recent rain raises discharge.",
            "baseline_m3s": 880.0,
        },
    ),
    "library.search_guidance": (
        {"query": "evacuation distance", "top_k": 3, "filters": {"publisher": ["NDMA"]}},
        {
            "hits": [
                {
                    "doc_id": "ndma-2022-01",
                    "page": 3,
                    "score": 0.9,
                    "bm25": 4.2,
                    "dense": 0.8,
                    "rerank": None,
                    "text": "Evacuate households within 500 m.",
                    "lang": "en",
                }
            ]
        },
    ),
    "library.answer_with_citations": (
        {"query": "evacuation distance", "lang": "auto"},
        {
            "status": "answered",
            "answer": "Evacuate households within 500 m of the embankment.",
            "citations": [CITATION],
            "refusal": None,
            "claims": [{"text": "Evacuate within 500 m.", "citation_idx": [0]}],
        },
    ),
    "ledger.optimize_allocation": (
        {
            "scenario_id": "sindh-2022",
            "districts": [
                {
                    "district_id": "d1",
                    "population_affected": 1000,
                    "severity": 0.8,
                    "road_access": 0.6,
                    "alt_delivery_fraction": 0.1,
                    "unit_cost_multiplier": 1.2,
                }
            ],
            "commodities": [
                {
                    "id": "food",
                    "name": "Food packs",
                    "unit": "pack",
                    "unit_cost": 10.0,
                    "per_person_need": 1.0,
                }
            ],
            "supply": {"food": 800.0},
            "budget": 20000.0,
            "equity_floor": 0.5,
        },
        {
            "status": "optimal",
            "allocation": [{"district_id": "d1", "commodity_id": "food", "quantity": 800.0}],
            "coverage": [
                {
                    "district_id": "d1",
                    "fraction": 0.8,
                    "access_mode": "road",
                    "unreached_people": 200.0,
                }
            ],
            "equity": {"floor_requested": 0.5, "floor_applied": 0.5, "max_feasible_floor": 0.8},
            "total_coverage": 640.0,
            "total_cost": 8000.0,
            "optimality_gap": 0.0,
            "cost_benefit": {"cost_per_person_covered": 10.0, "people_covered": 800.0},
            "solver": {"name": "highs", "version": "1.7", "wall_time_s": 0.02},
        },
    ),
    "ledger.sensitivity_report": (
        {"run_id": "r1", "floor_steps": 3},
        {
            "shadow_prices": [
                {
                    "constraint": "supply:food",
                    "value": 0.8,
                    "unit": "coverage/pack",
                    "binding": True,
                }
            ],
            "reduced_costs": [{"district_id": "d1", "commodity_id": "food", "value": 0.0}],
            "ranges": [
                {
                    "constraint": "supply:food",
                    "allowable_increase": 100.0,
                    "allowable_decrease": 50.0,
                }
            ],
            "basis": "lp_relaxation",
            "equity_tradeoff": [
                {
                    "min_coverage_floor": 0.0,
                    "status": "optimal",
                    "total_coverage": 640.0,
                    "people_covered": 800.0,
                },
                {
                    "min_coverage_floor": 1.0,
                    "status": "infeasible",
                    "total_coverage": None,
                    "people_covered": None,
                },
            ],
            "equity_cost": 0.0,
            "notes": [],
        },
    ),
    "voice.transcribe": (
        {"audio_b64": "UklGRg==", "format": "wav", "lang_hint": "ur"},
        {
            "text": "pani barh raha hai",
            "lang": "ur",
            "segments": [{"start": 0.0, "end": 1.5, "text": "pani barh raha hai"}],
            "lang_confidence": 0.9,
        },
    ),
    "voice.speak": (
        {"text": "Evacuate now.", "lang": "en", "format": "wav"},
        {
            "audio_b64": "UklGRg==",
            "format": "wav",
            "duration_s": 1.2,
            "sample_rate": 22050,
            "lang": "en",
            "provider": "fake",
            "synthesized": "live",
        },
    ),
}

RESOURCE_EXAMPLES: dict[str, Any] = {
    "ledger.resource.districts.json": {
        "district_id": "d1",
        "name": "Dadu",
        "population": 1000,
        "road_access": 0.6,
        "alt_delivery_fraction": 0.1,
        "default_severity": 0.8,
    },
}

# --- contract v0.4 -----------------------------------------------------------------------------
# Shallow overlays: ``{**TOOL_EXAMPLES[key][side], **V04_*[key]}`` is the example with every new
# optional field set. ``TOOL_EXAMPLES`` itself stays v0.3-shaped, which proves compatibility.
V04_IN: dict[str, dict[str, Any]] = {
    "eyes.segment_flood": {"mode": "demo"},
    "eyes.compare_with_permanent_water": {"mode": "live"},
    "oracle.forecast_river": {"mode": "demo"},
    "ledger.optimize_allocation": {"mode": "demo"},
    "library.search_guidance": {
        "filters": {"publisher": ["NDMA"], "lang": ["en", "ur"], "doc_id": ["ndma-2022-01"]}
    },
    "library.answer_with_citations": {"answer_lang": "ur"},
}
V04_OUT: dict[str, dict[str, Any]] = {
    "eyes.segment_flood": {
        "reference_overlay_note": "UNOSAT product 2022-09-02, CC BY 4.0, qualitative only.",
        "valid_fraction": 0.97,
        "model_variant": "unet-resnet18-s1-int8",
    },
    "eyes.compare_with_permanent_water": {
        "by_district": [
            {
                "district_id": "d1",
                "name": "Dadu",
                "flooded_km2": 60.0,
                "flooded_fraction": 0.3,
                "district_area_km2": 200.0,
                "flooded_roads_km": 41.5,
            }
        ]
    },
    "oracle.forecast_river": {
        "calibration": {
            "method": "split_conformal",
            "nominal_coverage": 0.8,
            "n_calibration": 200,
            "interval_lower_q": 0.1,
            "interval_upper_q": 0.9,
        },
        "station": {
            "name": "Guddu Barrage",
            "river": "Indus",
            "cell_lat": 28.425,
            "cell_lon": 69.725,
            "requested_lat": 28.42,
            "requested_lon": 69.72,
        },
        "quantile_correction_applied": True,
    },
    "oracle.explain_forecast": {
        "drivers": [
            {
                "feature": "rain_3d",
                "contribution_m3s": 120.0,
                "direction": "up",
                "feature_group": "rainfall",
            }
        ],
        "lead_days_explained": 3,
    },
    "library.search_guidance": {
        "hits": [
            {
                "doc_id": "ndma-2022-01",
                "page": 3,
                "score": 0.9,
                "bm25": 4.2,
                "dense": 0.8,
                "rerank": None,
                "text": "Evacuate households within 500 m.",
                "lang": "en",
                "chunk_id": "ndma-2022-01:p3:c1",
                "span": [0, 33],
                "title": "Flood contingency plan",
                "publisher": "NDMA",
            }
        ]
    },
    "library.answer_with_citations": {
        "generation": {"mode": "extractive", "provider": "fake", "model": None},
        "quantities": [{"value": 500.0, "unit": "m", "per": None, "claim_idx": 0}],
    },
    "voice.speak": {"voice": "ur-PK-UzmaNeural"},
}
V04_RESOURCES: dict[str, Any] = {
    "oracle.resource.stations.json": {
        "station_id": "guddu",
        "name": "Guddu Barrage",
        "river": "Indus",
        "role": "primary",
        "cell_lat": 28.425,
        "cell_lon": 69.725,
        "danger_threshold_m3s": 1100.0,
        "threshold_method": "reanalysis p95",
        "as_of_min": "2022-06-01",
        "as_of_max": "2022-09-30",
    },
    "eyes.resource.scenes.json": {
        "region_id": "pk-sindh",
        "date": "2022-08-30",
        "scene_id": "S1A_demo",
        "sensor": "Sentinel-1",
        "validated_for_region": False,
    },
}

BRIEFING: dict[str, Any] = {
    "briefing_id": "b1",
    "scenario": "sindh-2022",
    "lang": "en",
    "mode": "demo",
    "sections": [
        {
            "id": "allocation",
            "title": "Allocation",
            "status": "ok",
            "claims": [
                {
                    "id": "c1",
                    "text": "800 food packs cover 800 people.",
                    "evidence": [EVIDENCE],
                    "kind": "number",
                }
            ],
        }
    ],
    "conflicts": [
        {
            "id": "k1",
            "description": "Extent and guidance disagree on distance.",
            "organs": ["eyes", "library"],
            "resolution": "flagged",
            "evidence": [EVIDENCE],
        }
    ],
    "critic": {"passed": True, "removed_claims": [], "notes": []},
    "confidence": 0.7,
    "generated_at": "2026-01-01T00:00:00Z",
}

TASK_EVENT: dict[str, Any] = {
    "event": "organ_call",
    "ts": "2026-01-01T00:00:00Z",
    "task_id": "t1",
    "organ": "ledger",
    "tool": "optimize_allocation",
    "payload": {"scenario_id": "sindh-2022"},
}
