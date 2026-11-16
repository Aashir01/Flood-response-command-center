# Contract v0.4: decisions

Owner pre-approved every additive, optional proposal. Rule used: accept if a v0.3 payload stays valid and every new input is optional; reject renames, removals and tightened ranges; where two proposals disagree, take the more specific one. Contract text: `.kiro/steering/mcp-contracts.md` (v0.4, section 8c is new). Code: `stitch_common` (`CONTRACT_VERSION = "0.4"`, `brain_api.py`), schemas and `contracts.lock.json`. Tests: `packages/stitch_common/tests/test_contract_v04.py`.

Decisions: **A** accepted, **A\*** accepted with a changed shape, **D** documentation only (no schema change), **X** rejected, **Def** deferred.

## Library
| # | Proposal | Decision | Reason / field |
|---|---|---|---|
| L1 | `answer_with_citations.answer_lang` | A | `answer_lang?: "en\|ur"`; `lang` then only selects retrieval |
| L2 | `generation {mode, provider, model}` | A | optional on output; `mode: "llm\|extractive"` |
| L3 | hit `chunk_id`, `span`, `title`, `publisher` | A | optional; `span` needs `0 <= start <= end` |
| L4 | `filters.lang`, `filters.doc_id` | A | optional lists |
| L5 | refusal is `ok: true`; `NO_EVIDENCE` unused | D | stated in section 5. The code stays in the enum (removing it would break consumers) |
| L6 | `Provenance.models` | A | `models: [ModelInfo]`, default `[]`. `model` stays as the primary model, so no rename |
| C7 (brain) | `quantities` on answer | A | `quantities?: [{value, unit, per, claim_idx}]`; `claim_idx` must index `claims`; always empty when refused |

## Oracle
| # | Proposal | Decision | Reason / field |
|---|---|---|---|
| O1 | `calibration.interval_lower_q/upper_q` | A | optional, `[0,1]`. `p10`/`p90` names stay (renaming is non-additive); documented as lower/upper bounds at the requested coverage |
| O2 | `station {name, river, cell_lat, cell_lon, requested_lat, requested_lon}` | A | optional on output |
| O3 | `quantile_correction_applied` | A | optional bool |
| O4 | explain `lead_days_explained`, driver `feature_group` | A | optional |
| O5 | resource `oracle://stations` | A | model `StationInfo`; schema `oracle.resource.stations.json`. Fields `as_of_min`/`as_of_max` for the valid `as_of` window |
| O6 | `rainfall_mm` may be absent | D | already optional |

## Eyes
| # | Proposal | Decision | Reason / field |
|---|---|---|---|
| E1 | `confidence` nullable | A | `Unit \| None`, key still present. Widens an output: consumers must handle null (the Brain and UI specs already do) |
| E2 | `reference_overlay_note` | A | optional |
| E3 | `permanent_water_km2` definition | D | written in section 3 |
| E4 | `district_area_km2` | A | optional |
| E5 | `valid_fraction`, `model_variant` | A | `model_variant` is the closed literal `unet-resnet18-s1-int8 \| vh-threshold-baseline`; a new variant needs a contract bump |
| E6 | resource `eyes://scenes` | A | model `SceneInfo`; schema `eyes.resource.scenes.json` |
| E7 | ledger owns `pk_districts.geojson` | D | not a contract change |

## Voice
| # | Proposal | Decision | Reason / field |
|---|---|---|---|
| V1 | `speak.voice` | A | optional |
| V2 | `POST /voice/speak {briefing_id, lang, voice?}` | A\* | `SpeakRequest`: exactly one of `briefing_id` or `text`; `text` only with `STITCH_ALLOW_ARBITRARY_TTS=1`. Resolves the conflict with the Brain table (free text) and keeps the quota protection |
| V3 | Voice `/healthz` meta, forwarded in `/organs` | A | `VoiceOrganMeta`, in `OrganInfo.meta` |
| V4 | 4 MB limit on `/voice/transcribe` | A | `VOICE_TRANSCRIBE_MAX_BODY_BYTES`. Conflicts with the Brain table (14 MB): four specs say 4 MB and a 60 s recording is about 2.6 MB. The organ's own 10 MB audio limit is unchanged |
| V5 | Compose volume and env | D | deployment spec, not a contract |
| V6 | stable warning strings | D | listed in section 7, not enforced by schema |

## Brain
| # | Proposal | Decision | Reason / field |
|---|---|---|---|
| B-C1 | optional `mode` input | A | on `eyes.segment_flood`, `eyes.compare_with_permanent_water`, `oracle.forecast_river`, `ledger.optimize_allocation`. Not on `explain_forecast` or `sensitivity_report` (keyed by `run_id`) |
| B-C2 | `Claim.labels` | A | `modeled, unvalidated, recorded, demo, refusal, disputed` |
| B-C3 | `Briefing.organs`, `disclaimer`, `Section.missing` | A | `BriefingOrgan {organ, status, served_by?}` |
| B-C4 | `notice` event, `fatal` on `error` | A | `TaskEvent.event` gains `notice`; `NoticePayload`, `ErrorPayload` |
| B-C5 | `EvidenceRef.run_id` is the call-level id | D | docstring and section 2 |
| B-C6 | `Conflict.rule_id/status/subjects` | A | optional; `status: detected\|reconciling\|final` |
| B-C7 | library quantities | A | see L-table |
| B-C8 | `flooded_roads_km` per district | A | optional on `DistrictFlood` |

## Frontend and deployment (Brain HTTP/SSE, section 8c, `brain_api.py`)
| # | Proposal | Decision | Reason |
|---|---|---|---|
| F1 | SSE `id`, event payload shapes, `: ping` | A | `format_sse_frame`, `EVENT_PAYLOADS`, `SSE_PING_FRAME`. Payloads follow the Brain design (more specific); `critic` uses key `pass` (alias `pass_no`) |
| F2 | `GET /organs` meta, `live_available` | A\* | Merge of both shapes. Name conflict: used the Brain's `default_mode`, not the frontend's `mode_default`. Status has five values (`incompatible` included) so both specs are satisfied |
| F3 | `POST /briefings` returns `{briefing_id, task_id}` | A\* | Brain's `{briefing_id, status, events_url, result_url}` plus optional `task_id` equal to `briefing_id` |
| F3b | `DELETE /briefings/{id}` | A | idempotent cancel, 202 |
| F4 | `GET /evidence/{run_id}` full `ToolResult` | A\* | Accepted per the owner list; replaces the Brain's "no data" form. With `?pointer=` returns `EvidenceValue`. 10 MB cap returns 413 |
| F5 | `POST /ask` shape | A\* | Union: Brain's `claims`/`refusal_claim` (they carry provenance) plus the frontend's `result: ToolResult`. Error body for 429 is the Brain `ApiError`, not a `ToolResult` error: `RATE_LIMITED` is not in the tool `ErrorCode` enum and extending it would touch every organ |
| F6 | `GET /healthz` | A | `BrainHealth` |
| F7 | evals `history` per metric | Def | `evals/models.py` is evals-owned, not a contract; add as an optional field when the dashboard needs it |
| F8 | `Last-Event-ID` / `?last_event_id=` | A | documented in section 8c |
| F9 | 4 MB body for transcribe | A | see V4 |
| F10 | speak by `briefing_id` | A | see V2 |
| D1-D5 | `STITCH_ORGANS_DISABLED`, `*_FILE` secrets, Library seed CLI, lazy load, Voice health meta | D | operational requirements for the Brain, `stitch_common` settings and organs. Not schemas. Voice meta is in `VoiceOrganMeta` |

## Not done
- Rejected (non-additive): none of the proposals needed rejecting once the additive form was chosen. The non-additive readings that were set aside: renaming `p10`/`p90`, removing `NO_EVIDENCE`, making `model` a list, and extending the tool `ErrorCode` enum.
- Ledger sources were not edited. `organs/ledger/README.md` and its contract-test docstring still say v0.3; the schema checks pass because they read the exported schemas.
