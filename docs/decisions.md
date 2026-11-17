# Owner decisions: defaults already implied by the specs

Each line is a default a spec writer chose and asked the owner to confirm. Source in brackets. Nothing here was invented; change a line by editing the spec and this file.

- `EvidenceRef.run_id` is the call-level `provenance.run_id`; `/evidence/{run_id}` takes that id [brain design 20.1, contract v0.4].
- A recorded organ is chosen by configuration, never by silent failover [brain 20.2].
- Disclaimer and mode caveats are claims that cite Brain-origin evidence entries, so BRN-P1 holds without exemptions [brain 20.3].
- Brain-authored Urdu uses pre-authored templates; LLM translation applies only to organ-authored text [brain 20.4].
- The severity mapping, its five parameters and the road-access proxy are assumptions, flagged in every allocation caveat [brain 20.5].
- Conflict thresholds are judgement values: `oracle_low_p = 0.20`, `eyes_flooded_frac = 0.10`, `eyes_dry_frac = 0.01`, `need_rel_tol = 0.10` [brain 9.3, 20.6].
- Conflict rules R1 and R3 are flagged, not auto-reconciled; only R2 re-runs the Ledger, once [brain 20.7].
- A second scenario `demo-sindh-2022-conflicts` ships seeded fixtures; the headline `demo-sindh-2022` stays conflict-free [brain 20.8].
- `confidence` is a heuristic with judgement weights, not a calibrated probability [brain 20.10].
- Brain limits: 4 concurrent runs, rate limits per client (briefings 6/min, ask 20/min, voice 10/min), CORS allowlist `http://localhost:3000` and `https://stitch.aashirnoman.dev` [brain 14].
- Voice is never part of a briefing task graph. `POST /voice/speak` builds the script from the stored briefing; free text only with `STITCH_ALLOW_ARBITRARY_TTS=1`, off by default [voice design, contract v0.4].
- Library: answers are extractive by default, with an env switch to use an LLM [library 18.9].
- Library: pages that are neither English nor Urdu get language state `other` and are excluded like unreadable pages [library 18.1].
- Library: the 50-question set splits into a dev split of 20 and a test split of 30; confidence intervals will be wide [library 18.4].
- Library: derived artifacts (page text, chunks, embeddings) of a non-redistributable document are treated like the source file; `license_evidence` and `owner_confirmed` back the `redistributable` flag [library 18.7, 18.8].
- Library: quotes over 400 characters use a truncation rule (library design 7.3 step 2) [library 18.11].
- Eyes: the ledger spec owns `data/demo/boundaries/pk_districts.geojson` [eyes design 16 C7].
- Oracle: if contract changes were not approved, the fallback was a station note in `warnings` and cell coordinates in `MANIFEST.md`; with v0.4 approved, the contract fields are used [oracle tasks].
- Contract v0.4: new fields are optional; v0.3 payloads stay valid. Per-proposal reasons are in `docs/contract-v0.4-decisions.md`.
- Frontend: Urdu UI strings in `frontend/src/i18n/messages/ur.json` were written by the implementing agent, not a native speaker. A native-speaker proofread is needed before release [frontend task 20].
- Frontend: types are generated from the v0.4 JSON Schemas present in the working tree (`contracts.lock.json` contract_version 0.4); `npm run gen:types` is re-runnable [frontend task 2].
- Frontend: `GET /evidence/{run_id}` is always called in pointer form (`?pointer=/data`), because the Brain design returns no data without a pointer; the frontend design's "full ToolResult" form is not used [frontend design 4.3 vs brain design 14].
- Frontend: fonts use plain `@font-face` with woff2 from the Fontsource npm packages (OFL builds of the upstream fonts), not `next/font/local`, so the Urdu faces download only when `[lang=ur]` text is rendered. Nastaliq (arabic subset, 159 KB per weight) is under the 400 KB subsetting threshold, so no subsetting [frontend design 5.2].
- Frontend: the mock Brain also serves the static export (`--static out`) so Playwright and `npm run dev:mock` need one origin and one process; scenarios are switched with `POST /api/__mock/scenario` or the `X-Mock-Scenario` header, never from UI code [frontend design 16].
- Frontend: reducer keeps a per-run `calls` log (by plan node id) so charts can find the latest `ledger.optimize` run id after a rerun; the SSE `id` is the reducer `seq`, and `RUN_STARTING` resets `lastSeq` to 0 because seqs restart per run.- Ledger: the optional v0.4 `mode` input never makes the Ledger use the network. With the committed dataset the result reports `mode = demo`, and a `live` request adds a `MODE_FALLBACK: ...` warning; with caller-supplied `districts` the result carries the requested mode (else `STITCH_MODE`). `stitch_common.tooling.Outcome` gained optional `mode` and `run_id` fields for this (additive) [ledger task 12, contract v0.4].
- Ledger: `cost_per_person_covered` is `0.0` with a warning when nobody is covered, because the contract types it as a number; LED-R5.2 asked for null. Changing it needs a contract bump [ledger task 12].
- Ledger: `solver_time_limit_s` is capped at 30 s; a commodity missing from `supply` has supply 0 with a warning [ledger design 3, task 12].
- Ledger: the districts resource reports an unknown scenario as an MCP `ResourceError` whose message starts with `NOT_FOUND:` (resources have no envelope) [ledger task 12].
- Ledger: GLOP works to a tolerance relative to the objective scale, so coverage below about 1e-9 of `sum_d w_d` (tiny budgets) may come back as 0. Property tolerances (P10, P13) are relative to that scale; the found cases are named regression tests [ledger task 12].
- Oracle: Open-Meteo non-commercial terms accepted for the demo; attribution "Weather data by Open-Meteo.com (CC BY 4.0), GloFAS (Copernicus/ECMWF), ERA5 (Copernicus C3S)" is in `THIRD_PARTY.md`, `data/demo/oracle/MANIFEST.md` and every Oracle provenance `data_sources` entry [owner default, oracle design 2].
- Oracle: the Open-Meteo Flood API returns null for every day before 1997-01-01 at the chosen cells, although its docs say 1984. The demo dataset is 1997-01-01..2023-12-31; train_fit becomes 1997-2008 and train_val 2009-2011 (design said 1985-2007 and 2008-2011); calibration (2012-2016), test (2017-2023) and stress (2022-06..10) are unchanged [oracle design 3.3, found in the data build].
- Oracle: danger threshold = modeled 5-year return level from annual maxima of 1997-2016 (design said 1985-2016), `threshold_method = modeled_5yr_return_level`, labelled as an assumption in every result [owner default, oracle design 3.5].
- Oracle: station table picked by the build script (probe 5x5 offsets at 0.05 deg, highest mean discharge). The design's Guddu longitude 68.74 is not on the Indus; 69.72 (Guddu Barrage) is used. Owner review of the table in `data/demo/oracle/MANIFEST.md` is still pending [owner default, oracle design 12.2].
- Oracle: post-July-2022 continuity check passed for all 7 cells: no gaps in 2022-06-01..2023-12-31, the change at 2022-07-31/08-01 is below the 2012-2022 median daily change, and repeated-value days occur at the pre-2022 rate. The design fallback (restricting the stress window) was not needed [oracle design 13 R1].
- Oracle: `forecast_river` without `as_of` uses the last date in the dataset (demo: 2023-12-31) and says so in a warning; the Brain should pass `as_of` for the 2022 scenario [oracle design 5].
- Ledger: allowable ranges (task 16) are reported only for binding `supply:<k>` and `budget` constraints with a positive shadow price, from parametric LP re-solves with the run's floor bounds fixed; floor constraints are not ranged. New property LED-P20: shadow prices are exact on their range [ledger task 16].
- Ledger: after a SCIP solve the plan is checked against the LP plan rounded to whole units; if SCIP is more than 1e-3 worse, SCIP is re-run without the varbound upgrade and the better plan is returned with a warning (found by the Ledger eval) [ledger task 14].
- Ledger: integer repairs never remove units below `ceil(floor * share)`; at its integer floors a plan may exceed the budget by at most 1e-9 relative (the floor-feasibility tolerance) [ledger task 14].

- Brain: BRN-P6 root cause. The `dry_district` mutator could dry Dadu or Jamshoro, which carry most of the basin's flood area, so in `combo_r1_r2` the basin flooded fraction fell from 0.135 to about 0.08 and R1 correctly stopped firing; the scenario expectation was wrong, not the rule. It also wrote `flooded_km2 = frac * 1000` when `district_area_km2` was absent, changing the district's area. The mutator now keeps the area (writes `district_area_km2`) and only dries basin districts that leave the basin fraction at or above 0.12 [brain task 16].
