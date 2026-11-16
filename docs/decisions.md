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
