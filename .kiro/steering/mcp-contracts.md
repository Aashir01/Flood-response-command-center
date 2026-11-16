---
inclusion: always
---

# MCP contracts (v0.3)

Single source of truth for organ tool I/O. `packages/stitch_common` mirrors these as Pydantic v2 models; the contract hook validates both directions. Schemas are written as compact JSON Schema (`?` = optional). Any change bumps `contract_version` and is logged at the bottom.

## 1. Conventions
- Every tool returns a `ToolResult<T>` envelope. Tools never raise to the client for domain failures; they return `ok:false` with an `error`.
- Dates are ISO 8601 UTC. Geometry is GeoJSON (WGS84). Areas in km². Discharge in m³/s. Rainfall in mm.
- Regions are identified by `region_id` (slug, e.g. `pk-sindh`) and optionally by `bbox: [west, south, east, north]`.
- `mode`: `"demo"` (committed data) or `"live"` (network). Every result states which one it used.
- Language codes: `"en"` or `"ur"`.
- Tool I/O is validated with `additionalProperties: false`.

## 2. Shared types

```jsonc
// ToolResult<T>
{ "ok": bool,
  "data": T | null,
  "error": { "code": "INVALID_INPUT|NOT_FOUND|NO_EVIDENCE|INFEASIBLE|UPSTREAM_UNAVAILABLE|TIMEOUT|INTERNAL",
             "message": str, "retryable": bool } | null,
  "provenance": Provenance,
  "warnings": [str] }

// Provenance  (attached to every result, ok or not)
{ "organ": "eyes|oracle|library|ledger|voice",
  "tool": str,
  "tool_version": str,
  "contract_version": str,
  "run_id": str,                 // uuid4
  "inputs_hash": str,            // sha256 of canonical input JSON
  "mode": "demo|live",
  "data_sources": [ { "id": str, "name": str, "license": str, "as_of": date|null } ],
  "model": { "name": str, "version": str, "sha256": str } | null,
  "generated_at": datetime }

// Interval
{ "p10": number, "p50": number, "p90": number }   // invariant: p10 <= p50 <= p90

// Citation
{ "doc_id": str, "title": str, "publisher": str, "page": int >= 1,
  "span": [int, int],            // char offsets within the page text
  "quote": str,                  // verbatim, <= 400 chars
  "lang": "en|ur",
  "url": str | null }

// EvidenceRef  (what the Brain stores for provenance)
{ "run_id": str, "organ": str, "tool": str, "json_pointer": str }  // e.g. "/data/forecast/3/p50"
```

## 3. eyes-mcp

`segment_flood`
```jsonc
in:  { "region_id": str, "date": date, "bbox"?: [n,n,n,n], "tile_size"?: int (default 256) }
out: { "flood_extent_km2": number,
       "extent_geojson": FeatureCollection,        // polygons of new flood water
       "permanent_water_km2": number,
       "confidence": number [0,1],                 // mean per-pixel max-prob over flood pixels
       "tiles_processed": int,
       "source_scene": { "sensor": str, "acquired": datetime, "scene_id": str },
       "validation": { "validated_for_region": bool,       // false for the Sindh demo scene
                       "eval_dataset": str,                 // "sen1floods11_test"
                       "note": str },
       "reference_overlay_geojson": FeatureCollection | null }   // UNOSAT/CEMS extent, qualitative only
```
`compare_with_permanent_water`
```jsonc
in:  { "region_id": str, "date": date, "bbox"?: [n,n,n,n] }
out: { "total_water_km2": number, "permanent_water_km2": number, "new_flood_km2": number,
       "by_district": [ { "district_id": str, "name": str, "flooded_km2": number, "flooded_fraction": number [0,1] } ] }
```

## 4. oracle-mcp

`forecast_river`
```jsonc
in:  { "station_id": str, "horizon_days": int [1,14], "as_of"?: date, "coverage"?: number (default 0.8) }
out: { "station_id": str, "unit": "m3/s", "as_of": date,
       "target_kind": "modeled_glofas",                   // never "gauge"
       "target_label": "Modeled river discharge (GloFAS via Open-Meteo)",
       "forecast": [ { "date": date, "lead_days": int, "discharge": Interval,
                       "rainfall_mm"?: Interval } ],
       "danger_threshold_m3s": number | null,
       "exceedance_prob": [ { "date": date, "p_exceed": number [0,1] } ],
       "calibration": { "method": "split_conformal", "nominal_coverage": number,
                        "n_calibration": int } }
```
`explain_forecast`
```jsonc
in:  { "run_id": str }          // run_id of a prior forecast_river result
out: { "drivers": [ { "feature": str, "contribution_m3s": number, "direction": "up|down" } ],
       "narrative": str,        // template-generated from drivers, not free LLM text
       "baseline_m3s": number }
```

## 5. library-mcp

`search_guidance`
```jsonc
in:  { "query": str, "lang"?: "en|ur|auto", "top_k"?: int [1,20] (default 8),
       "filters"?: { "publisher"?: [str], "doc_type"?: [str] } }
out: { "hits": [ { "doc_id": str, "page": int, "score": number, "bm25": number,
                   "dense": number, "rerank": number | null, "text": str, "lang": str } ] }
```
`answer_with_citations`
```jsonc
in:  { "query": str, "lang"?: "en|ur|auto", "top_k"?: int }
out: { "status": "answered|refused",
       "answer": str | null,                       // required iff status = answered
       "citations": [ Citation ],                  // >= 1 iff answered
       "refusal": { "reason": "INSUFFICIENT_EVIDENCE|OUT_OF_SCOPE|CONFLICTING_EVIDENCE",
                    "closest_hits": [ Citation ] } | null,   // required iff refused
       "claims": [ { "text": str, "citation_idx": [int] } ] }  // each answer sentence mapped to citations
```
Invariant: `(status=answered ∧ citations≠∅ ∧ every claim has ≥1 valid citation_idx) ∨ (status=refused ∧ refusal≠null)`.

## 6. ledger-mcp

`optimize_allocation`
```jsonc
in:  { "scenario_id": str,
       "districts"?: [ { "district_id": str, "population_affected": int >= 0,   // override; omitted => dataset for scenario_id
                         "severity": number [0,1], "road_access": number [0,1],
                         "alt_delivery_fraction"?: number [0,1] (default 0),     // share carried by air/boat
                         "unit_cost_multiplier"?: number > 0 } ],
       "min_road_access"?: number [0,1] (default 0.1),                        // below this a district is road-denied
       "commodities": [ { "id": str, "name": str, "unit": str, "unit_cost": number >= 0,
                          "per_person_need": number > 0 } ],
       "supply": { "<commodity_id>": number >= 0 },
       "budget"?: number >= 0,
       "equity_floor"?: number [0,1],             // fraction of each district's proportional share
       "on_infeasible_floor"?: "relax|error" (default "relax"),
       "integer"?: bool (default true),           // trucks/pallets as integers
       "solver_time_limit_s"?: number (default 10) }
out: { "status": "optimal|feasible|infeasible",
       "allocation": [ { "district_id": str, "commodity_id": str, "quantity": number >= 0 } ],
       "coverage": [ { "district_id": str, "fraction": number [0,1],
                       "access_mode": "road|air_boat|unreachable",
                       "unreached_people": number >= 0 } ],
       "equity": { "floor_requested": number, "floor_applied": number, "max_feasible_floor": number },
       "total_coverage": number,                  // objective value (severity/access-weighted people covered)
       "total_cost": number,
       "optimality_gap": number | null,           // from solver bound; 0 for LP optimal
       "cost_benefit": { "cost_per_person_covered": number, "people_covered": number },
       "solver": { "name": str, "version": str, "wall_time_s": number },
       "infeasibility_reason"?: str }
```
`sensitivity_report`
```jsonc
in:  { "run_id": str, "floor_steps"?: int [2,21] (default 11) }
out: { "shadow_prices": [ { "constraint": "supply:<commodity_id>|budget|equity_floor|min_coverage:<district_id>",
                            "value": number, "unit": str, "binding": bool } ],
       "reduced_costs": [ { "district_id": str, "commodity_id": str, "value": number } ],
       "ranges": [ { "constraint": str, "allowable_increase": number, "allowable_decrease": number } ],
       "basis": "lp_relaxation",                  // shadow prices come from the LP relaxation when integer=true
       "equity_tradeoff": [ { "min_coverage_floor": number [0,1],
                              "status": "optimal|feasible|infeasible",
                              "total_coverage": number | null,
                              "people_covered": number | null } ],
       "equity_cost": number | null,              // coverage given up by the run's own floor
       "notes": [str] }
```

## 7. voice-mcp

`transcribe`
```jsonc
in:  { "audio_b64": str, "format": "wav|webm|mp3|ogg", "lang_hint"?: "en|ur|auto" }   // <= 60 s, <= 10 MB
out: { "text": str, "lang": "en|ur", "segments": [ { "start": number, "end": number, "text": str } ],
       "lang_confidence": number [0,1] }
```
`speak`
```jsonc
in:  { "text": str (<= 4000 chars), "lang": "en|ur", "voice"?: str, "format"?: "wav|mp3" }
out: { "audio_b64": str, "format": str, "duration_s": number, "sample_rate": int, "lang": str,
       "provider": "azure|google|prerendered|local-mms|fake", "synthesized": "live|cache|prerendered" }
```

## 8. Brain API (browser-facing, not MCP)
Defined in the brain spec. Streams `TaskEvent`s over SSE:
```jsonc
{ "event": "plan|organ_call|organ_result|conflict|critic|briefing|error",
  "ts": datetime, "task_id": str, "organ"?: str, "tool"?: str, "payload": object }
```
`Briefing`:
```jsonc
{ "briefing_id": str, "scenario": str, "lang": "en|ur", "mode": "demo|live",
  "sections": [ { "id": "extent|forecast|guidance|allocation|caveats",
                  "title": str, "status": "ok|partial|unavailable",
                  "claims": [ { "id": str, "text": str,
                                "evidence": [EvidenceRef], "kind": "number|statement|recommendation" } ] } ],
  "conflicts": [ { "id": str, "description": str, "organs": [str], "resolution": "flagged|reconciled|escalated", "evidence": [EvidenceRef] } ],
  "critic": { "passed": bool, "removed_claims": [str], "notes": [str] },
  "confidence": number [0,1],
  "generated_at": datetime }
```
Invariant (BRN-P1): every claim has `evidence.length >= 1` and every `EvidenceRef` resolves in the run's evidence store.

## 8b. Resources (read-only, MCP resources, not tools)
```
ledger://scenario/{scenario_id}/districts
-> [ { "district_id": str, "name": str, "population": int >= 0, "road_access": number [0,1],
       "alt_delivery_fraction": number [0,1], "default_severity": number [0,1] } ]
```

## 9. Change log
- 0.1 draft: initial contracts.
- 0.2: eyes `validation` and `reference_overlay_geojson`; oracle `target_kind`/`target_label`; ledger `equity_tradeoff`, `equity_cost`, `floor_steps`; voice `provider`, `synthesized`.
- 0.3: ledger `districts` optional override, `alt_delivery_fraction`, `min_road_access`, `access_mode`, `unreached_people`; `min_coverage_fraction` replaced by `equity_floor` (fraction of proportional share) with `on_infeasible_floor` and `equity` output; resource `ledger://scenario/{id}/districts`.
