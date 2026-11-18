# frontend: Tasks

Tags: `core` (must ship), `stretch`, `cuttable`. Each task lists the requirements and properties it satisfies, the tests that prove it, a "Done when", and an estimate. Ordered by dependency. Commit after each task (`feat(frontend): ...`).

Blocked by: **bootstrap** (exported JSON Schemas in `packages/stitch_common/schemas/`, `contracts.lock.json`, CI skeleton). **Not** blocked by the Brain: tasks 1 to 18 run against the mock Brain (task 5). Task 19 is the only task that needs the real Brain.

Schedule (docs/schedule.md): tasks 1, 2, 5 start before Nov 21 (they need no Brain); tasks 3 to 14 on Nov 21 to 24; tasks 15 to 22 on Nov 29 to 30 (polish). Estimated total 79 h; the minimal path is 58 h (tasks 1 to 12, 17, 19). That is more than the roughly 32 h of the Nov 21 to 24 window, so the schedule is tight; see "Estimates".

## Minimal path (if time runs out)
Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 17 (partial: smoke tests and axe), 19. This gives: bench with five jars and the reducer, mock and real Brain streaming, briefing cards with evidence drawer, conflict and refusal display, states, Urdu RTL, accessibility basics, Playwright smoke. The map is included at its simplest (flood layer plus the table), because it is the headline visual.

**Cut order (first cut first):** (1) Voice UI task 16, shown as disabled; (2) Sound task 15; (3) eval dashboard task 14 (keep the "no eval run yet" empty state only); (4) map time slider and reference overlay (part of task 9); (5) equity slider task 13 (keep a static table of `equity_tradeoff`); (6) Lightning bolt drawing (keep the fade); (7) `Ask the creature` microphone button (text box stays, FRN-R16.1). Never cut: honest labels (task 10), Modeled label (task 10), states, keyboard operation, reduced motion, Urdu RTL.

## Tasks

- [x] **1. Scaffold the app** `core` (2 h)
  - `frontend/` with Next.js (App Router, TypeScript strict, `noUncheckedIndexedAccess`), Tailwind, ESLint, Vitest, Testing Library, fast-check, Playwright. `output: 'export'`. Pin versions. Add THIRD_PARTY.md rows for every dependency (and their licenses).
  - Routes `/`, `/[lang]`, `/[lang]/evals`, `/[lang]/about` with `generateStaticParams` for `en` and `ur`; `<html lang dir>` set in `[lang]/layout`.
  - Verify a static export builds and serves from a plain static server and that `next/font/local` works under export.
  - Done when: `npm run build` produces `out/`, `npm test` runs one placeholder test, `npm run lint` is clean, and the export serves `/en/` and `/ur/`. Refs: FRN-R8.1, FRN-R12.

- [x] **2. Generated contract types and drift check** `core` (2 h)
  - `scripts/gen-types.mjs` using `json-schema-to-typescript` over `packages/stitch_common/schemas/*.json` to `src/gen/contracts.ts` with the `CONTRACT_VERSION` header. Commit the output. Add `npm run gen:types`.
  - CI step: regenerate and `git diff --exit-code src/gen`. Test `contract-version.test.ts`.
  - If `brain_api.py` models do not exist yet, hand-write interim types in `src/api/interim.ts` marked `TODO(contract)`, and file the proposed contract change.
  - Done when: changing a field in a schema makes CI fail until regenerated. Refs: FRN-R5, design §4.

- [x] **3. Design tokens, fonts, motion registry, base layout** `core` (4 h)
  - `tokens.css` (colors, spacing, type scale, radius, glow, z-index, motion), Tailwind theme mapping, `high-contrast` data attribute variant, logical-property utilities only.
  - Self-hosted fonts via `next/font/local`: Cinzel, Noto Sans, Noto Nastaliq Urdu, Noto Naskh Arabic (Urdu only on `[lang=ur]`). Measure and record woff2 sizes; subset Nastaliq if over 400 KB. THIRD_PARTY.md rows.
  - `motion/registry.ts`, `motion/flashRate.ts`, `FxProvider` (`full|lite|none`).
  - `AppShell`, `Header`, `SkipLinks`, `LiveRegion`, `Panel` (all states from design §10).
  - `scripts/check-budget.mjs`; record the first-load gzip size of the shell (the first real number; the design assumes none).
  - Tests: FRN-P5 (`flashRate.p5.test.ts`), physical-utility lint scan, `Panel` state matrix. Refs: FRN-R8, FRN-R10, FRN-R12, P5.
  - Done when: shell renders in both languages, FRN-P5 passes, budget script runs and its output is saved in the PR.

- [x] **4. i18n, RTL, number formatting** `core` (3 h)
  - `t()`, dictionaries (English complete for all chrome and states; Urdu translated, flagged "needs native review"), `Bdi` helper, `format.ts` (Western digits default, `ur-PK-u-nu-arabext` option), `LanguageToggle`.
  - Tests: FRN-P3 round trip, dictionary completeness (same keys, same placeholders), `Bdi` usage test for identifiers. Refs: FRN-R8.1 to R8.3, P3.
  - Done when: toggling twice restores DOM text and `html[dir]` flips; the completeness test passes.

- [x] **5. Mock Brain and fixtures** `core` (4 h)
  - `mock-brain/server.mjs` (Node built-ins only): `/api/organs`, `/api/briefings` (POST, GET, SSE with `Last-Event-ID` and `?last_event_id=`, `?drop_after=`, `?speed=`), `/api/evidence/:run_id`, `/api/ask`, `/api/voice/*`, `/api/evals/latest`, cancel. Scenarios: `default-demo`, `organ-error`, `refusal`, `conflict`, `partial`, `slow`, `brain-down`, `voice-cut`, `offline-fallback`.
  - Hand-author fixtures from `mcp-contracts.md` v0.3 (all five organ results with realistic Sindh numbers, a full `Briefing`, conflicts, equity trade-off with an infeasible tail, shadow prices, forecast with p10/p50/p90 and a threshold).
  - Fixture contract test: every REST body and SSE frame validates against the JSON Schemas (Ajv, dev dependency).
  - `scripts/record-stream.mjs` to record from a real Brain later.
  - Done when: `npm run dev:mock` serves the full demo flow with `curl -N` and the fixture contract test passes. Refs: FRN-R15.1, FRN-R13.

- [x] **6. API client, SSE wrapper, reducer, selectors** `core` (5 h)
  - `api/client.ts` (typed `Result`, timeouts, 429 and unreachable mapping), `api/sse.ts` (named events, `Last-Event-ID` resume, manual reconnect with backoff, watchdog, `STREAM_LOST`), `api/guards.ts`, `state/benchReducer.ts` (table in design §3.2), `selectors.ts`, `announcer.ts`.
  - Tests: FRN-P1 (reference-model property), FRN-P2 (determinism, duplicate/replay idempotence, batching), unit tests for each event row, SSE wrapper against the mock server with a forced mid-stream drop (resume yields no duplicate state), reconnect backoff with fake timers. Refs: FRN-R2.2, R2.4, R3.2, R10.2, P1, P2.
  - Done when: P1 and P2 pass under the CI profile and the resume test passes against the mock.

- [x] **7. Lab bench and organ jars** `core` (6 h)
  - Five hand-built SVG jars (eye, vial, book, scales, horn) with `glow`, `body`, `liquid` groups; five state variants via classes and Motion `m` with `LazyMotion`; status icons and text; `OrganDrawer` (last call, timing, raw JSON summary); `ScenarioControl` (region, scenario, live toggle, Run, Cancel, per-organ progress); health fetch on load.
  - Fallback for `fx=lite` and `none`. Announcements to the live region.
  - Tests: component test per state (icon, text, role, label); keyboard: Tab, Enter opens drawer, Esc closes, focus returns; state change appears within one frame of the event in a component test using fake timers (the 200 ms budget, FRN-R2.4). Refs: FRN-R2, R3.1 to R3.2, R11.5.
  - Done when: running the mock `default-demo` drives all five jars through idle, calling, done and `organ-error` shows "The organ is unwell" with the reason.

- [x] **8. Lightning awakening** `core` (3 h)
  - `LightningAwakening` with the boot timeline (2300 ms, two flashes 500 ms apart) and the shorter completion timeline; Skip button, Esc, click; reduced-motion single fade; never traps focus.
  - Tests: timeline declared in the registry passes FRN-P5; Playwright reduced-motion test (no bolt paths); skip with keyboard. Refs: FRN-R1.1 to R1.3, P5.
  - Done when: the animation is skippable by keyboard, finishes in at most 2.5 s, and the registry test is green.

- [x] **9. Haunted map** `core` (7 h)
  - `scripts/build-map-assets.mjs`: Natural Earth context, Sindh district polygons (same ids as the Ledger demo), simplification, centroids, `style.json` (no glyphs, no sprite, no external URLs). Commit outputs and `data/demo/MANIFEST.md` rows (coordinate with ledger demo data). THIRD_PARTY.md and on-map attribution (OSM/ODbL if used).
  - `HauntedMap` (lazy chunk): layers per design §8.1 (stacked blurred lines for flood glow), DOM label markers (`Bdi`), layer toggles, allocation circles with sqrt scaling and popup, keyboard instructions and `T` shortcut, `MapTable` (sortable, real `<table>`), WebGL-failure fallback, `fitBounds` once, reduced-motion jump.
  - Stretch inside this task (cut first): time slider (only when more than one date), reference-extent overlay labelled qualitative.
  - Tests: hygiene test (no external URLs in style), table renders from the same data as the map, `labelVisible` pure function, Playwright: toggles change layer visibility, table reachable by keyboard. Refs: FRN-R4, R14.2 (stretch part).
  - Done when: the demo scene shows glowing flood over dim permanent water with district labels in both languages, the table matches the map, and everything works with the network blocked.

- [x] **10. Briefing: vital cards, evidence, conflicts, refusal, honest labels** `core` (7 h)
  - `VitalSignsBriefing`, `VitalCard`, `ClaimItem` with `EvidenceButton`, `ClaimEvidenceDrawer` (native `<dialog>`, resolves via `getEvidence`, shows quote and page for guidance), `ConflictBanner` (both sides), `RefusalCard`, `EyesLabels` (two separate labels plus not-validated line), `ModeledLabel`/`OracleValue`, `DemoLiveNotice`, `DecisionSupportNotice`, `ConfidenceHeartbeat`, `CriticNotes`.
  - Tests: FRN-P4 (claims always have an evidence control), FRN-P6 (every Oracle value has the label; no "gauge" or "observed"), component tests for conflict display (both evidence buttons), refusal as a labelled normal outcome, Eyes labels never merged. Refs: FRN-R5.1 to R5.5, R14.1, R14.3, P4, P6.
  - Done when: P4 and P6 pass, `conflict` and `refusal` fixtures render as specified, and the drawer is fully keyboard operable.

- [x] **11. Charts: forecast band and heartbeat** `core` (3 h)
  - `lib/scale.ts`, `bandPath`, `ForecastBandChart` (p10/p50/p90 band, threshold, exceedance strip, table disclosure), heartbeat strip.
  - Tests: geometry unit tests (band monotone, threshold within domain), chart `role=img` label and data table equal the input numbers. Refs: FRN-R5.1, R14.3, P6.
  - Done when: the forecast card renders from the fixture and every number carries "Modeled (GloFAS)".

- [x] **12. Allocation card, shadow prices, and the states pass** `core` (4 h)
  - `AllocationTable`, `CostBenefit`, `ShadowPricePanel` (plain-language "one more unit buys"), full states for every panel (design §10): skeletons, empty, partial naming what is missing, error with retry, offline banner, "the creature sleeps" full-bench state with Retry.
  - Tests: state matrix per panel (component), Playwright `brain-down`, `partial`, `organ-error`, `offline-fallback`. Refs: FRN-R5.6, R10, R3.3.
  - Done when: every panel in the §10 table can be forced into every listed state from fixtures.

- [x] **13. Equity trade-off chart** `core` (3 h)
  - `lib/equitySegments.ts`, `EquityTradeoffChart`: native range slider over precomputed floors, `aria-valuetext`, segments only across feasible points, hatched infeasible tail with text, current floor marker and `equity_cost` annotation.
  - Tests: FRN-P7 property test, slider keyboard test, Playwright "infeasible floor shows text and no line across the gap". Refs: FRN-R5.7, P7.
  - Done when: P7 passes and the demo fixture shows the infeasible tail.
  - Cut path: replace with a static table of `equity_tradeoff` (still honors "infeasible" as text).

- [x] **14. Ask the creature and eval dashboard** `core` for Ask, `cuttable` for the dashboard beyond the empty state (4 h)
  - `AskTheCreature` (500-char counter, submit, loading, error, refusal, 429 states; renders through the shared guidance components). Microphone button appears only when Voice is `ready` (task 16).
  - `/[lang]/evals`: `EvalHeartbeat` cards by organ with value, target, direction, trend, timestamp, Oracle label; "No eval run yet" and "stale" states; pulse-line header.
  - Tests: Ask state tests, keyboard-only submit; eval fixtures: empty, stale, partial, full. Refs: FRN-R16, FRN-R9, R14.3.
  - Done when: Ask answers and refuses against the mock; the dashboard renders all four fixtures.

- [x] **15. Sound** `cuttable` (2 h)
  - `sound/voices.ts` recipes (hum, thunder, twitch, unwell, done), `sound/engine.ts` (context created after toggle, master gain 0.3), `SoundToggle` (`aria-pressed`, off by default, persisted).
  - Tests: recipes are pure descriptions (unit), toggle persistence, no `AudioContext` created before the toggle (Playwright spy). THIRD_PARTY.md note: sounds are synthesized, no files. Refs: FRN-R7.
  - Done when: sound is silent by default and plays all five cues after the toggle.

- [x] **16. Voice UI** `cuttable` (4 h)
  - `VoiceControls`: Play (no autoplay), waveform on an analyser canvas, provider disclosure dialog before the first hosted synthesis, "Voice by <provider>" line, Record via AudioWorklet to 16 kHz WAV (30 s cap), permission-denied and unsupported fallbacks to the text box, transcription fills the ask box without auto-submit; disabled state when Voice is cut.
  - Tests: component states (disabled, unwell, permission denied via a stubbed `getUserMedia`), disclosure dialog shown once per provider, no `.play()` without a click, WAV encoder unit test (header, length, 16-bit little-endian). Refs: FRN-R6, R14.4, R15.2.
  - Done when: against the mock, Play returns audio, Record produces a valid WAV and fills the ask box; with `voice-cut` the control is disabled and the rest works.
  - **Cut condition:** Voice go/no-go on Nov 28 fails. Then ship only the disabled state (30 min of this task).

- [x] **17. Accessibility and Playwright suite** `core` (5 h)
  - High-contrast toggle and `prefers-contrast` default. Focus ring, skip links, live region verified end to end.
  - Playwright scenarios from design §18.2 in the `mock` project (boot, default briefing, organ error, evidence drill-down, Urdu RTL, keyboard only, reduced motion, equity infeasible, ask, voice cut, brain-down) with axe scan after each; fail on serious or critical violations.
  - `scripts/contrast.mjs` regenerates the contrast table and fails if a documented pair drops below its requirement.
  - Manual NVDA pass recorded in the PR.
  - Done when: the whole suite is green locally and in CI, axe has no serious violations. Refs: FRN-R11, R13.

- [x] **18. Performance pass** `core` (2 h)
  - Bundle analysis, `LazyMotion` strict, lazy chunks for map, charts, recorder, drawer, evals; `check-budget.mjs` wired into CI at 300 KB; Lighthouse CI lab run for LCP on `/en/` and `/ur/`; frame-time sample during a run (Playwright tracing) on the dev laptop.
  - Done when: first-load JS ≤ 300 KB gzip, LCP under 2.5 s in the lab run, and the numbers are written into `docs/` and the PR. Refs: FRN-R12.

- [x] **19. Integrate with the real Brain** `core` (3 h; after Brain tasks complete, about Nov 22 to 24)
  - Record real streams with `record-stream.mjs` over the fixtures; reconcile payload shapes with the Brain's actual events; fix reducer assumptions; run the `stack` Playwright project against the Compose stack (deployment).
  - Done when: the default demo briefing runs against the real Brain in the browser, and the recorded fixtures replace the hand-authored ones with the fixture contract test still green. Refs: FRN-R15.1.

- [ ] **20. Polish and spooky details** `stretch` (3 h; Nov 29 to 30)
  - Jar illustration refinement, table texture, engraved label tuning, card stagger, awakening afterglow sequence, copy pass for tone, Urdu translation review with a native reader.
  - Done when: a reviewer rates the visual pass "coherent and finished" and tests stay green.

- [x] **21. About page, credits, THIRD_PARTY audit** `core` (1.5 h)
  - `/[lang]/about`: demo vs validated explanation, decision-support notice, data credits (OSM, Natural Earth, WorldPop where used), font credits. Audit THIRD_PARTY.md rows for every npm dependency and every font.
  - Done when: `check` script finds a THIRD_PARTY row for each runtime dependency in `package.json`.

- [ ] **22. Documentation** `core` (1.5 h)
  - `frontend/README.md` (run with mock, with the real Brain, regenerate types, record streams), `docs/frontend-design.md` summary, Kiro write-up notes (steering `ui-style.md` use, property tests with fast-check, mock-first workflow).
  - Done when: a new developer can run the app with the mock Brain in under 5 minutes.

## Estimates

| Task | Hours | Tag | Task | Hours | Tag |
|---|---|---|---|---|---|
| 1 | 2 | core | 12 | 4 | core |
| 2 | 2 | core | 13 | 3 | core |
| 3 | 4 | core | 14 | 4 | core / cuttable |
| 4 | 3 | core | 15 | 2 | cuttable |
| 5 | 4 | core | 16 | 4 | cuttable |
| 6 | 5 | core | 17 | 5 | core |
| 7 | 6 | core | 18 | 2 | core |
| 8 | 3 | core | 19 | 3 | core |
| 9 | 7 | core | 20 | 3 | stretch |
| 10 | 7 | core | 21 | 1.5 | core |
| 11 | 3 | core | 22 | 1.5 | core |

Total 79 h with everything; the minimal path is 58 h (tasks 1 to 12, 17, 19). The schedule gives 4 days (Nov 21 to 24) plus 2 polish days (Nov 29 to 30); at 8 h per day that is 48 h, less than the minimal path. Mitigations: start tasks 1, 2, 5 (scaffold, types, mock; 8 h) before Nov 21, in parallel with Brain work, since they need no Brain; run task 17's Playwright scenarios incrementally as each feature lands rather than at the end; treat tasks 13, 14 (dashboard), 15, 16, 20 as polish-window work; and apply the cut order above early. If the Brain slips, nothing here blocks, because the mock Brain stands in until task 19. This is flagged as a schedule risk.

## Traceability

| Requirement | Tasks |
|---|---|
| FRN-R1 | 3, 8 |
| FRN-R2 | 6, 7 |
| FRN-R3 | 7, 12 |
| FRN-R4 | 9 |
| FRN-R5 | 10, 11, 12, 13 |
| FRN-R6 | 16 |
| FRN-R7 | 15 |
| FRN-R8 | 1, 3, 4 |
| FRN-R9 | 14 |
| FRN-R10 | 3, 12 |
| FRN-R11 | 3, 7, 17 |
| FRN-R12 | 1, 3, 18 |
| FRN-R13 | 5, 17 |
| FRN-R14 | 9, 10, 11, 14, 16 |
| FRN-R15 | 5, 16, 19 |
| FRN-R16 | 14, 16 |

| Property | Task | Test file |
|---|---|---|
| FRN-P1 | 6 | `property/reducer.p1.test.ts` |
| FRN-P2 | 6 | `property/reducer.p2.test.ts` |
| FRN-P3 | 4 | `component/i18n.p3.test.tsx` |
| FRN-P4 | 10 | `component/claims.p4.test.tsx` |
| FRN-P5 | 3 (registry), 8 | `property/flashRate.p5.test.ts` |
| FRN-P6 | 10, 11, 14 | `component/oracleLabel.p6.test.tsx` |
| FRN-P7 | 13 | `property/equitySegments.p7.test.ts` |

## Status (final audit)

Ticked: 1 to 19 and 21. Code is in `frontend/src`. Tests: Vitest unit, component and property tests (FRN-P1 to P7) in `frontend/tests/{unit,component,property}` (150 passing) and the Playwright scenarios in `frontend/tests/e2e/smoke.spec.ts` (with axe) and `perf.spec.ts` (LCP, frame time). `npm run build` enforces the 300 KB first-load budget, and `npm run check:third-party` finds a THIRD_PARTY row for all 28 npm packages and every font. The app runs against the real Brain at https://stitch.aashirnoman.dev.

Urdu and RTL ship as an experimental capability: the Urdu strings are machine-translated and not reviewed by a native reader.

Open:
- 20 (polish, `stretch`): the native Urdu review is not planned; the visual polish items were not tracked as a separate pass.
- 22 (documentation): `frontend/README.md` and `docs/frontend-design.md` were not written. The root README covers running the stack.
