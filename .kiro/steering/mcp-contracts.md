---
inclusion: always
---

# MCP contracts (v0.5)

Single source of truth for organ tool I/O. `packages/stitch_common` mirrors these as Pydantic v2 models; the contract hook validates both directions. Schemas are written as compact JSON Schema (`?` = optional). Any change bumps `contract_version` and is logged at the bottom. v0.4 changes are all additive: every new input is optional and every new output field is optional (an absent field means "unknown"), so v0.3 payloads stay valid. Decisions per proposal: `docs/contract-v0.4-decisions.md`.

## 1. Conventions
- Every tool returns a `ToolResult<T>` envelope. Tools never raise to the client for domain failures; they return `ok:false` with an `error`.
- Dates are ISO 8601 UTC. Geometry is GeoJSON (WGS84). Areas in km². Discharge in m³/s. Rainfall in mm.
- Regions are identified by `region_id` (slug, e.g. `pk-sindh`) and optionally by `bbox: [west, south, east, north]`.
- `mode`: `"demo"` (committed data) or `"live"` (network). Every result states which one it used. v0.4: Eyes, Oracle `forecast_river` and Ledger `optimize_allocation` accept an optional input `mode?: "demo|live"` (the Brain passes the requested mode; absent means the organ's own `STITCH_MODE`). Tools keyed by a prior `run_id` do not take `mode`.
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
  "models"?: [ { "name": str, "version": str, "sha256": str } ],   // v0.4: organs with several models (Library: embedder, reranker, LLM). `model` stays the primary model or null. Absent means [].
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
// v0.4 clarification: run_id is the call-level provenance.run_id of the ToolResult the pointer points into
// (a Brain-generated id for Brain-origin evidence). It is the key of GET /evidence/{run_id}.
```

## 3. eyes-mcp

`segment_flood`
```jsonc
in:  { "region_id": str, "date": date, "bbox"?: [n,n,n,n], "tile_size"?: int (default 256), "mode"?: "demo|live" }
out: { "flood_extent_km2": number,
       "extent_geojson": FeatureCollection,        // polygons of new flood water
       "permanent_water_km2": number,
       "confidence": number [0,1] | null,          // mean per-pixel max-prob over flood pixels; null when no flood pixels exist (v0.4)
       "tiles_processed": int,
       "source_scene": { "sensor": str, "acquired": datetime, "scene_id": str },
       "validation": { "validated_for_region": bool,       // false for the Sindh demo scene
                       "eval_dataset": str,                 // "sen1floods11_test"
                       "note": str },
       "reference_overlay_geojson": FeatureCollection | null,    // UNOSAT/CEMS extent, qualitative only
       "reference_overlay_note"?: str | null,      // v0.4: source, product date, licence, "qualitative only"
       "valid_fraction"?: number [0,1],            // v0.4: share of window pixels with valid data
       "model_variant"?: "unet-resnet18-s1-int8|vh-threshold-baseline" }   // v0.4: honest fallback reporting
```
`compare_with_permanent_water`
```jsonc
in:  { "region_id": str, "date": date, "bbox"?: [n,n,n,n], "mode"?: "demo|live" }
out: { "total_water_km2": number, "permanent_water_km2": number, "new_flood_km2": number,
       "by_district": [ { "district_id": str, "name": str, "flooded_km2": number, "flooded_fraction": number [0,1],
                          "district_area_km2"?: number >= 0,    // v0.4: district area inside the window; explains flooded_fraction
                          "flooded_roads_km"?: number >= 0 } ] }  // v0.4: flooded road length in the district
```
v0.4 definition (both tools): `permanent_water_km2` is the permanent part of the detected water, the water that is also present in the permanent-water reference. `new_flood_km2` is `total_water_km2 - permanent_water_km2`.

## 4. oracle-mcp

`forecast_river`
```jsonc
in:  { "station_id": str, "horizon_days": int [1,14], "as_of"?: date, "coverage"?: number (default 0.8), "mode"?: "demo|live" }
out: { "station_id": str, "unit": "m3/s", "as_of": date,
       "target_kind": "modeled_glofas",                   // never "gauge"
       "target_label": "Modeled river discharge (GloFAS via Open-Meteo)",
       "forecast": [ { "date": date, "lead_days": int, "discharge": Interval,
                       "rainfall_mm"?: Interval } ],
       "danger_threshold_m3s": number | null,
       "exceedance_prob": [ { "date": date, "p_exceed": number [0,1] } ],
       "calibration": { "method": "split_conformal", "nominal_coverage": number,
                        "n_calibration": int,
                        "interval_lower_q"?: number [0,1],   // v0.4: quantile level of Interval.p10 at the requested coverage (0.05 at coverage 0.9)
                        "interval_upper_q"?: number [0,1] }, // v0.4: quantile level of Interval.p90 (0.95 at coverage 0.9)
       "station"?: { "name": str, "river": str, "cell_lat": number, "cell_lon": number,
                     "requested_lat": number, "requested_lon": number },   // v0.4: the GloFAS cell actually read
       "quantile_correction_applied"?: bool }                               // v0.4
```
v0.4 note: for any `coverage`, `Interval.p10` and `Interval.p90` are the lower and upper interval bounds at that coverage (the field names are historical). `forecast[].rainfall_mm` is optional and may be absent for every point; absence is normal.
```
`explain_forecast`
```jsonc
in:  { "run_id": str }          // run_id of a prior forecast_river result
out: { "drivers": [ { "feature": str, "contribution_m3s": number, "direction": "up|down",
                     "feature_group"?: str } ],                       // v0.4
       "narrative": str,        // template-generated from drivers, not free LLM text
       "baseline_m3s": number,
       "lead_days_explained"?: int >= 0 }                             // v0.4
```

## 5. library-mcp

`search_guidance`
```jsonc
in:  { "query": str, "lang"?: "en|ur|auto", "top_k"?: int [1,20] (default 8),
       "filters"?: { "publisher"?: [str], "doc_type"?: [str],
                     "lang"?: ["en"|"ur"], "doc_id"?: [str] } }       // filters.lang and filters.doc_id: v0.4
out: { "hits": [ { "doc_id": str, "page": int, "score": number, "bm25": number,
                   "dense": number, "rerank": number | null, "text": str, "lang": str,
                   "chunk_id"?: str, "span"?: [int, int], "title"?: str, "publisher"?: str } ] }   // v0.4 hit fields
```
`answer_with_citations`
```jsonc
in:  { "query": str, "lang"?: "en|ur|auto", "top_k"?: int,
       "answer_lang"?: "en|ur" }                    // v0.4: answer language; `lang` then only selects retrieval
out: { "status": "answered|refused",
       "answer": str | null,                       // required iff status = answered
       "citations": [ Citation ],                  // >= 1 iff answered
       "refusal": { "reason": "INSUFFICIENT_EVIDENCE|OUT_OF_SCOPE|CONFLICTING_EVIDENCE",
                    "closest_hits": [ Citation ] } | null,   // required iff refused
       "claims": [ { "text": str, "citation_idx": [int] } ],   // each answer sentence mapped to citations
       "generation"?: { "mode": "llm|extractive", "provider": str, "model": str | null },   // v0.4
       "quantities"?: [ { "value": number, "unit": str, "per": str | null, "claim_idx": int >= 0 } ] }   // v0.4; [] when none, always [] if refused
```
v0.4 clarification: a refusal is an `ok: true` result. The error code `NO_EVIDENCE` is reserved and is not used by the Library. `quantities[].per` is the denominator (for example `person_day`) or null for a plain amount.

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
       "solver_time_limit_s"?: number (default 10),
       "mode"?: "demo|live" }                     // v0.4
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
       "provider": "azure|google|deepgram|prerendered|local-mms|fake", "synthesized": "live|cache|prerendered",
       "voice"?: str }                            // v0.4: the resolved voice name
```
Stable warning strings (v0.4, documented not enforced): `transcribe` may add `NO_SPEECH`, `REPETITION_TRIMMED`, `LANGUAGE_UNSUPPORTED:<code>`; `speak` may add `TTS_BUDGET_80PCT`.

## 8. Brain API (browser-facing, not MCP)
Defined in the brain spec. Streams `TaskEvent`s over SSE:
```jsonc
{ "event": "plan|organ_call|organ_result|conflict|critic|briefing|error|notice",
  "ts": datetime, "task_id": str, "organ"?: str, "tool"?: str, "payload": object }
```
`Briefing`:
```jsonc
{ "briefing_id": str, "scenario": str, "lang": "en|ur", "mode": "demo|live",
  "sections": [ { "id": "extent|forecast|guidance|allocation|caveats",
                  "title": str, "status": "ok|partial|unavailable",
                  "claims": [ { "id": str, "text": str,
                                "evidence": [EvidenceRef], "kind": "number|statement|recommendation",
                                "labels"?: ["modeled|unvalidated|recorded|demo|refusal|disputed"] } ],   // v0.4
                  "missing"?: [str] } ],                                // v0.4: what is missing, by name
  "conflicts": [ { "id": str, "description": str, "organs": [str], "resolution": "flagged|reconciled|escalated", "evidence": [EvidenceRef],
                   "rule_id"?: str, "status"?: "detected|reconciling|final", "subjects"?: [str] } ],   // v0.4
  "critic": { "passed": bool, "removed_claims": [str], "notes": [str] },
  "confidence": number [0,1],
  "generated_at": datetime,
  "organs"?: [ { "organ": str, "status": "ready|degraded|unwell|disabled|incompatible", "served_by"?: "real|recorded" } ],   // v0.4
  "disclaimer"?: str }                                                  // v0.4
```
Invariant (BRN-P1): every claim has `evidence.length >= 1` and every `EvidenceRef` resolves in the run's evidence store.

## 8b. Resources (read-only, MCP resources, not tools)
```
ledger://scenario/{scenario_id}/districts
-> [ { "district_id": str, "name": str, "population": int >= 0, "road_access": number [0,1],
       "alt_delivery_fraction": number [0,1], "default_severity": number [0,1] } ]
```

```
oracle://stations                                                      (v0.4)
-> [ { "station_id": str, "name": str, "river": str, "role": str, "cell_lat": number, "cell_lon": number,
       "danger_threshold_m3s": number | null, "threshold_method": str | null,
       "as_of_min": date, "as_of_max": date } ]                        // valid as_of window, inclusive
eyes://scenes                                                          (v0.4)
-> [ { "region_id": str, "date": date, "scene_id": str, "sensor"?: str, "validated_for_region"?: bool } ]
```
## 8c. Brain HTTP/SSE API (browser-facing, v0.4)
Models: `stitch_common.brain_api` (schemas `brain_api.<name>.json`). Errors on every route: `{ "error": { "code": "INVALID_INPUT|NOT_FOUND|RATE_LIMITED|BUSY|CANCELLED|PAYLOAD_TOO_LARGE|UPSTREAM_UNAVAILABLE|INTERNAL", "message": str, "details"?: object } }` (400/422, 404, 429 with `Retry-After`, 413, 503, 500). The browser talks only to these routes.

| Method and path | Request | Response |
|---|---|---|
| `POST /briefings` | `{ region: slug (<= 64), scenario: str, lang?: "en\|ur" = "en", mode?: "demo\|live" = "demo" }` | `202 { briefing_id, status: "running", events_url, result_url, task_id? }` (`task_id` equals `briefing_id`) |
| `GET /briefings/{id}` | | `{ briefing_id, status: "running\|done\|failed\|cancelled", request, created_at, finished_at?, briefing?: Briefing, error?: ApiErrorBody }` |
| `DELETE /briefings/{id}` | | `202`, idempotent cancel; the stream ends with a fatal `error` event (`CANCELLED`) |
| `GET /briefings/{id}/events` | `Last-Event-ID` header or `?last_event_id=` (non-integer is 400) | SSE, below |
| `GET /organs` | | `{ organs: [OrganInfo], live_available: bool, default_mode, brain_version, contract_version, llm_provider?, build_sha? }`; `OrganInfo { organ, status: "ready\|degraded\|unwell\|disabled\|incompatible", compat?, reason?, served_by?: "real\|recorded", stub, tools, last_check?, last_error?, version?, meta? }`. Voice `meta`: `{ capabilities: ["speak","transcribe"], tts_provider, hosted, whisper_model? }`. |
| `GET /evidence/{run_id}` | `run_id` is the call-level id | the full stored `ToolResult` |
| `GET /evidence/{run_id}?pointer=<RFC 6901>` | | `{ ref: EvidenceRef, value, organ, tool, served_by: "real\|recorded\|brain", mode, generated_at, node_id? }`. 404 for unknown run id or unresolved pointer. Responses over 10 MB return 413. |
| `POST /ask` | `{ question: str (1..500), lang?: "auto\|en\|ur" = "auto" }` | `{ ask_id, status: "answered\|refused", claims: [Claim], refusal_claim?: Claim, mode, library_run_id, result?: ToolResult<answer_with_citations out> }` |
| `POST /voice/transcribe` | the Voice `transcribe` input; body limit 4 MB on this route | the Voice `data` plus `served_by` |
| `POST /voice/speak` | `{ briefing_id \| text, lang, voice?, format? }`: exactly one of `briefing_id` (script built by the Brain from the stored briefing) or `text` (only with `STITCH_ALLOW_ARBITRARY_TTS=1`) | the Voice `data` plus `served_by` |
| `GET /evals/latest` | | `evals/results/latest.json` |
| `GET /healthz` | | `{ status: "ok\|degraded", organs_ready: int, db_ok: bool }` |

SSE frames: `retry: 2000`, then per event `id: <seq>` (per-run integer from 1, contiguous), `event: <type>`, `data: <TaskEvent JSON>`. A `: ping` comment every 15 s. Resume with `Last-Event-ID`. Order: `plan` first; each `organ_call` precedes its `organ_result`; `critic` events precede `briefing`; the last event is `briefing` (success) or an `error` with `fatal: true`.

Event payloads (`TaskEvent.payload`):
| Event | `task_id` | Payload |
|---|---|---|
| `plan` | `plan` | `{ plan_id, revision, planner, scenario, lang, mode_requested, nodes: [{ id, kind, organ?, tool?, deps, optional }], stub_organs: [str], added?: [str] }` |
| `organ_call` | node id | `{ attempt, max_attempts, timeout_s, served_by, started_at }` |
| `organ_result` | node id | `{ ok, attempt, duration_ms, served_by, run_id, mode, warnings: [str], error?: { code, message, retryable }, summary: { <= 10 scalar fields } }` |
| `conflict` | `conflicts` | the `Conflict` object |
| `critic` | `critic` | `{ pass: int >= 1, passed: bool, issues: [{ claim_id, check, detail }], removed: [str], reverted: [str] }` |
| `briefing` | `briefing` | the full `Briefing` |
| `error` | node id or `run` | `{ code, message, fatal: bool, retryable: bool }` |
| `notice` | node id or `run` | `{ code, message, details?: object }`; non-fatal, for example `MODE_FALLBACK` (live fell back to demo) |

## 9. Change log
- 0.1 draft: initial contracts.
- 0.2: eyes `validation` and `reference_overlay_geojson`; oracle `target_kind`/`target_label`; ledger `equity_tradeoff`, `equity_cost`, `floor_steps`; voice `provider`, `synthesized`.
- 0.3: ledger `districts` optional override, `alt_delivery_fraction`, `min_road_access`, `access_mode`, `unreached_people`; `min_coverage_fraction` replaced by `equity_floor` (fraction of proportional share) with `on_infeasible_floor` and `equity` output; resource `ledger://scenario/{id}/districts`.
- 0.4: all additive and optional. Provenance `models`; optional `mode` input on eyes, oracle `forecast_river` and ledger `optimize_allocation`; eyes nullable `confidence`, `reference_overlay_note`, `valid_fraction`, `model_variant`, per-district `district_area_km2` and `flooded_roads_km`, `permanent_water_km2` definition, resource `eyes://scenes`; oracle `calibration.interval_lower_q/upper_q`, `station`, `quantile_correction_applied`, explain `lead_days_explained` and `feature_group`, resource `oracle://stations`; library `answer_lang`, `generation`, `quantities`, hit `chunk_id/span/title/publisher`, `filters.lang/doc_id`, refusal is `ok: true` and `NO_EVIDENCE` unused; voice `speak.voice` and stable warning strings; brain `Claim.labels`, `Briefing.organs/disclaimer`, `Section.missing`, `Conflict.rule_id/status/subjects`, `notice` event, `EvidenceRef.run_id` clarified; new section 8c (Brain HTTP/SSE API and event payloads) and `stitch_common.brain_api`.
- 0.5: voice `provider` gains `deepgram` (Deepgram Nova-3 transcription and Aura-2 English speech). Additive.
