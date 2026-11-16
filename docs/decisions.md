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
