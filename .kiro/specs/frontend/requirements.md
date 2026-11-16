# frontend: Requirements

Next.js lab-bench UI. Prefix `FRN`. Style: `ui-style.md`. API: Brain (`mcp-contracts.md` §8).

## Introduction
A polished mad-scientist lab bench where the user chooses a region and scenario, watches the Brain wake organs, and reads a vital-signs briefing, a haunted map, and an eval "heartbeat" dashboard.

## Requirements

### FRN-R1 Boot and awakening
1. WHEN the app loads, THE UI SHALL play the lightning awakening animation (max 2.5 s, skippable) while it fetches organ health.
2. WHEN a briefing completes, THE UI SHALL play the awakening animation again, shorter.
3. WHERE `prefers-reduced-motion` is set, THE UI SHALL replace the animations with a static single-frame flash or fade and no flashing above 3 Hz at any time.

### FRN-R2 Lab bench and organs
1. THE UI SHALL show five organs as jars/limbs on a table with name, status icon, and status text.
2. WHEN a `organ_call` event arrives, THE UI SHALL set that organ to `calling` (twitch and glow). On `organ_result`, `done`. On error, `unwell` with a message "the organ is unwell" and the reason.
3. WHEN the user selects an organ, THE UI SHALL show its last call, timing, and raw JSON summary in a drawer.
4. THE UI SHALL update organ states from the SSE stream within 200 ms of the event.

### FRN-R3 Scenario control
1. THE UI SHALL offer region and scenario selection, defaulting to Sindh Aug 2022 (demo), and a `live` toggle with Open-Meteo forecast.
2. WHEN the user starts a run, THE UI SHALL disable the control, show progress per organ, and allow cancel.
3. IF the network is offline, THEN THE UI SHALL show the demo/offline banner and keep demo mode usable.

### FRN-R4 Haunted map
1. THE UI SHALL render a MapLibre GL map in the dark "ouija board" style with district boundaries and engraved labels.
2. THE UI SHALL render flood extent as a luminous green-blue layer, and permanent water dimmer.
3. THE UI SHALL provide layers toggles (flood, permanent water, districts, allocation) and a time slider where multiple dates exist.
4. THE UI SHALL show allocation per district as proportional markers with tooltip details.
5. THE UI SHALL provide a table alternative for the map content.
6. THE map SHALL work with a self-hosted style and tiles/geometry from the demo dataset (no external tile API key).

### FRN-R5 Vital-signs briefing
1. THE UI SHALL render the briefing as vital-sign cards: flood extent, river forecast chart with p10/p50/p90 band and danger threshold, guidance with citations, allocation with cost-benefit, and caveats.
2. WHEN the user activates a claim, THE UI SHALL show its evidence (organ, tool, JSON pointer, value, and for guidance the quote and page).
3. THE UI SHALL show conflicts prominently with both sides' evidence.
4. THE UI SHALL show refusals from the Library as a normal, labelled outcome.
5. THE UI SHALL show the confidence "heartbeat" and the demo/live and decision-support notices.
6. THE UI SHALL show Ledger shadow prices in a readable "what would one more unit buy" panel.
7. THE UI SHALL show the coverage-versus-equity-floor trade-off as a chart with a slider moving along the precomputed `equity_tradeoff` points (no re-solve), marking the run's current floor and the `equity_cost`, and showing infeasible floors as such.

### FRN-R6 Voice
1. WHERE Voice is available, THE UI SHALL let the user play the spoken briefing and record a spoken question using Web Audio, with a visible waveform and permission handling.
2. IF microphone permission is denied or Voice is unwell, THEN THE UI SHALL show a clear message and a text input alternative.
3. THE UI SHALL never autoplay audio.

### FRN-R7 Sound toggle
1. THE UI SHALL provide a sound toggle, off by default, persisted per browser, covering ambient and effect sounds.

### FRN-R8 Language and RTL
1. THE UI SHALL provide `en`/`ur` switching that sets `lang` and `dir`, mirrors layout using logical CSS, and renders Urdu with Nastaliq/Naskh fonts.
2. THE UI SHALL keep numbers, units, citations, and identifiers legible in RTL using bidi isolation.
3. THE UI SHALL ship translated UI strings for all fixed text in both languages.

### FRN-R9 Eval dashboard ("heartbeat")
1. THE UI SHALL show the latest eval results: Eyes IoU/F1, Oracle CRPS and coverage, Library citation accuracy and refusal rate, Ledger feasibility and optimality gap, and Brain faithfulness, each with value, target, trend, and timestamp.
2. THE UI SHALL show a clear state for "no eval run yet" and for stale results.

### FRN-R10 States
1. THE UI SHALL implement loading, empty, partial, error, and offline states for every panel, as in `ui-style.md`.
2. WHEN the Brain API is unreachable, THE UI SHALL show a full-bench "the creature sleeps" state with retry.

### FRN-R11 Accessibility and responsiveness
1. THE UI SHALL be fully operable by keyboard with visible focus, a skip link, and logical tab order.
2. THE UI SHALL meet WCAG 2.2 AA at minimum, with AAA for body text contrast, and provide a high-contrast toggle.
3. THE UI SHALL announce organ state changes and briefing completion via an ARIA live region.
4. THE UI SHALL be responsive at 360, 768, 1280, and 1920 px widths.
5. Status SHALL not rely on color alone.

### FRN-R12 Performance
1. THE UI SHALL reach Largest Contentful Paint under 2.5 s on a mid-range laptop over broadband, with first-load JS under 300 KB gzipped excluding map and chart chunks which load lazily.
2. THE UI SHALL maintain 60 fps animation on a mid-range laptop, falling back to simpler effects on low-power devices.

### FRN-R13 UI tests
1. THE project SHALL include Playwright smoke tests for: boot, run default briefing in demo mode, organ error state, evidence drill-down, Urdu RTL toggle, keyboard-only run, and reduced motion.
2. THE project SHALL run an automated accessibility scan (axe) in the Playwright suite and fail on serious violations.

### FRN-R14 Honest labeling
1. THE Eyes panel SHALL show two separate labels: "Demo scene: Sindh, Aug 2022" and "Model validated on Sen1Floods11 test split", and SHALL NOT present Sindh output as validated.
2. WHERE `reference_overlay_geojson` is present, THE map SHALL offer a "reference extent" overlay, labeled qualitative.
3. EVERY Oracle number, chart, and eval row SHALL carry the label "Modeled (GloFAS)". The UI SHALL NOT use the words gauge or observed for Oracle output.
4. THE UI SHALL show which TTS provider produced audio and disclose that briefing text is sent to a hosted provider before first live synthesis.

### FRN-R15 Demo-first and cuttable Voice
1. THE UI SHALL work fully against a Brain running in demo mode with no network.
2. THE UI SHALL render Voice as disabled (not broken) when Voice is cut or unavailable, and no other feature SHALL depend on it.

### FRN-R16 Ask the creature
1. THE UI SHALL provide a single text box ("ask the creature") that sends the question to `POST /ask` and shows the Library's answer with citations, or its refusal, in the same style as a briefing's guidance section.
2. WHERE Voice is available, THE UI SHALL offer a microphone button that fills the box from `transcribe`, and otherwise hide it.
3. THE box SHALL show loading, error ("the organ is unwell"), and refusal states, and be fully keyboard operable.

## Correctness properties (formalized in design)
- FRN-P1: every organ has exactly one visible state at any time, derived from the event stream via a pure reducer.
- FRN-P2: replaying the same event sequence yields the same UI state (reducer is deterministic).
- FRN-P3: switching language twice returns the same DOM text as before (round-trip).
- FRN-P4: no briefing claim renders without an accessible evidence control.
- FRN-P5: no animation exceeds 3 flashes per second.

- FRN-P6: every rendered Oracle-derived value has an adjacent "Modeled (GloFAS)" label (component-level test).
- FRN-P7: the equity trade-off chart never interpolates across infeasible points.

## Out of scope
Authentication. Native mobile apps. Editing the plan by hand.

## Decisions (resolved)
1. Organ art: hand-built SVG with CSS and Framer Motion, no raster art.
2. Fonts: OFL-licensed (e.g. Cinzel, Noto), self-hosted, listed in THIRD_PARTY.md.
3. Base map: self-hosted style from Natural Earth plus OSM-derived Sindh extracts in the demo dataset.