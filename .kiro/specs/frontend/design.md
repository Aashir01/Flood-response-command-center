# frontend: Design

Implements `requirements.md` (FRN-R1..R16, FRN-P1..P7). Style: `ui-style.md`. API: Brain (`brain/requirements.md` BRN-R8, BRN-R14; `mcp-contracts.md` §8, v0.3).

## 1. Overview

A static Next.js app (App Router, TypeScript strict, Tailwind, Motion, MapLibre GL, Web Audio) that talks only to the Brain over HTTP and SSE. All state that matters (organ states, run progress, briefing) is derived by one pure reducer from the Brain's event stream. Everything else is presentation.

Four design choices drive the rest:

1. **Static export, no Node server.** The app is `output: 'export'`. All data arrives client-side from the Brain, so there is no server-side rendering need. The frontend container is a ~20 MB static file server instead of a Node runtime (saves ~150 to 250 MB RAM on the 4 GB floor, see deployment design §3). Cost: no middleware, no route handlers, no image optimizer. None are needed.
2. **One pure reducer, no state library.** `benchReducer(state, TaskEvent) -> state` plus `useReducer`. Replaying a recorded stream yields the same UI (FRN-P1, P2).
3. **Types come from the Pydantic models.** The browser never hand-writes a contract type (§4).
4. **No charts or map labels from big libraries.** Charts are hand-rolled SVG. Map labels are DOM elements, not glyph-based symbol layers, because MapLibre symbol labels need a separate RTL text plugin for Urdu shaping (§8).

## 2. Application structure

```
frontend/
  package.json, tsconfig.json (strict, noUncheckedIndexedAccess), next.config.mjs (output:'export')
  tailwind config + src/styles/tokens.css
  public/
    map/{style.json, districts.geojson, context.geojson}      generated, committed (§8)
    worklets/pcm-recorder.js                                  AudioWorklet (§12)
  fixtures/                                                   recorded and hand-authored Brain streams (§15)
    streams/*.ndjson, rest/*.json
  mock-brain/server.mjs                                       fixture server, Node built-ins only (§15)
  scripts/
    gen-types.mjs            JSON Schema -> TypeScript
    build-map-assets.mjs     Natural Earth + OSM extracts -> public/map/*
    check-budget.mjs         first-load JS gzip budget
    contrast.mjs             recomputes the contrast table (§11)
  src/
    app/
      layout.tsx                         root: fonts, metadata (static)
      page.tsx                           meta-refresh redirect to /en/ (Caddy also redirects)
      [lang]/layout.tsx                  sets <html lang dir>, provides dictionary
      [lang]/page.tsx                    the bench (everything on one screen)
      [lang]/evals/page.tsx              EvalHeartbeat dashboard
      [lang]/about/page.tsx              honest labelling, decision-support notice, data and font credits
    gen/contracts.ts                     generated types (committed, see §4)
    api/{client.ts, sse.ts, guards.ts, evidence.ts}
    state/{events.ts, benchReducer.ts, selectors.ts, uiReducer.ts, announcer.ts}
    motion/{registry.ts, flashRate.ts, tokens.ts, awakening.ts}
    sound/{engine.ts, voices.ts}
    i18n/{messages/en.json, messages/ur.json, t.ts, format.ts, bidi.tsx}
    a11y/{LiveRegion.tsx, focus.ts, SkipLinks.tsx}
    components/                          see §6
    lib/{scale.ts, equitySegments.ts, geo.ts, storage.ts}
  tests/{unit, property, component, e2e}/
```

### Routes
| Route | Content | Notes |
|---|---|---|
| `/` | redirect to `/en/` | Caddy `redir` and a `<meta refresh>` fallback in the static page |
| `/[lang]/` | LabBench, HauntedMap, VitalSignsBriefing, AskTheCreature, VoiceControls | `lang` is `en` or `ur`, produced by `generateStaticParams` |
| `/[lang]/evals/` | EvalHeartbeat | reads `GET /evals/latest` |
| `/[lang]/about/` | labelling, notices, credits | static text |

Language lives in the URL, so `<html lang dir>` is correct in the first byte of HTML (no flash of LTR for Urdu) and the toggle is a normal link that keeps run state (state is held in a provider above the route layout via a shared `app/[lang]/layout`, and the run id is kept in `sessionStorage` so a language switch can re-attach to the same run, §3.4).

Because the app is static, no secret or Brain URL is baked in: the Brain is reached at same-origin `/api` (Caddy routes it, deployment §5). In dev, `NEXT_PUBLIC_BRAIN_URL` points at the mock Brain or a local Brain.

## 3. State management

### 3.1 Shape (interface sketch, not implementation)

```ts
type OrganId = 'eyes'|'oracle'|'library'|'ledger'|'voice';
type OrganState = 'idle'|'calling'|'done'|'unwell'|'disabled';        // the five visible states

interface OrganView {
  state: OrganState;                 // exactly one (FRN-P1)
  degraded: boolean;                 // secondary text badge; does not change `state`
  lastCall?: { tool: string; startedAt: string; endedAt?: string; durationMs?: number;
               ok?: boolean; runId?: string; errorCode?: string; reason?: string; summary?: unknown };
}
interface BenchState {
  lastSeq: number;                   // highest applied event seq; duplicates <= lastSeq are ignored
  run: { taskId?: string; status: 'idle'|'starting'|'running'|'completed'|'failed'|'cancelled'|'disconnected';
         plan?: PlanPayload; startedAt?: string; endedAt?: string };
  organs: Record<OrganId, OrganView>;
  conflicts: Conflict[];
  critic?: Critic;
  briefing?: Briefing;               // set by the `briefing` event
  errors: { organ?: OrganId; code: string; message: string; ts: string }[];
  announcements: Announcement[];     // derived messages for the live region (ids are event seqs)
}
```
`ui` state (open drawer, selected organ, active map layers, slider position, sound/contrast toggles) lives in a separate `uiReducer`. The bench reducer never reads `Date.now()`, `Math.random()`, or the DOM; durations come from `event.ts` differences.

### 3.2 Event to state table (pure reducer)

| Event | Effect |
|---|---|
| (init) from `GET /organs` | organ `ready` to `idle`; `degraded` to `idle` with `degraded=true`; `unwell` or `incompatible` to `unwell`; `disabled` to `disabled`. Voice `disabled` stays `disabled`. |
| `plan` | `run.status=running`, store plan. Organs named in the plan and not `disabled` stay `idle` (they are queued, shown as "queued" secondary text from the plan). |
| `organ_call` | organ to `calling`; record `startedAt` and tool. Ignored for `disabled` organs. |
| `organ_result` (`ok:true`) | organ to `done`; record duration, `runId`, summary. |
| `organ_result` (`ok:false`) or `error` with `organ` | organ to `unwell`; record code, reason; push `errors`. |
| `conflict` | append to `conflicts` (dedupe by id). |
| `critic` | store critic. |
| `briefing` | store briefing; `run.status=completed`; every organ still `calling` becomes `unwell` with reason `no result` (defensive, cannot happen if the Brain is correct). |
| `error` without `organ` | `run.status=failed`, push error. |
| `RUN_CANCELLED` (local action after the Brain acknowledges cancel) | `run.status=cancelled`; organs in `calling` return to `idle`. |
| `STREAM_LOST` (local action after reconnect gives up) | `run.status=disconnected`. Organ states are kept (not reset to idle). |

Only the `organ_result` after a run changes `done` back; a new run resets `idle` organs but keeps `unwell` and `disabled` from health until the new run overwrites them.

Payload shapes for each event type are not fixed by the contract; this table assumes them (see **Proposed contract changes**).

### 3.3 Selectors
`selectBriefingSections`, `selectClaimEvidence(claimId)`, `selectOracleValues`, `selectMissingSections` (names what is missing for partial states), `selectConfidence`. Selectors are pure and memoized by reference.

### 3.4 Run lifecycle
1. `POST /briefings {region, scenario, lang, mode}` returns `{briefing_id, task_id}`.
2. Open `EventSource(/api/briefings/{id}/events)`. Dispatch each event to the reducer.
3. On `briefing`, fetch the full ToolResults needed by charts (§4.3), close the stream, play the short awakening animation.
4. `sessionStorage['stitch.run']` keeps `{briefing_id, lastSeq}`. On reload or language switch, `GET /briefings/{id}` renders the result immediately if completed, else re-attaches to SSE with resume.

### 3.5 SSE with `Last-Event-ID`
`EventSource` sends `Last-Event-ID` automatically on its own reconnects, so resume costs no code if the Brain writes `id:` fields (BRN-R8.4). The wrapper adds:
- Named-event listeners for the seven event types (the Brain sends `event: plan` etc.).
- Reducer-level dedupe by `seq` (taken from the SSE `id`), so a replay of already-seen events is a no-op.
- After the browser gives up (`readyState === CLOSED`), up to 5 manual reconnects with backoff 0.5, 1, 2, 4, 8 s, passing `?last_event_id=N` (the Brain should accept the query form too, because manual `new EventSource` cannot set the header). Then dispatch `STREAM_LOST` and show "the creature sleeps" only if `GET /organs` also fails; otherwise show a partial "connection lost, retry" banner on the run panel.
- A watchdog: if no event (including the Brain's `: ping` comment every 15 s, a proposed requirement) arrives for 30 s during a run, treat the stream as stalled and reconnect.

## 4. Typed API client and drift prevention

### 4.1 Types come from `stitch_common`
`packages/stitch_common/schemas/*.json` is committed and exported from the Pydantic models (BOOT-R3), including `Briefing`, `Claim`, `EvidenceRef`, `TaskEvent`, and each organ tool I/O. The frontend generates its types from those files:

- Tool: `json-schema-to-typescript` (MIT, verified from its repository license file). `frontend/scripts/gen-types.mjs` compiles every schema in the folder into `src/gen/contracts.ts` with `bundleRefs`, `additionalProperties: false` preserved, and a header comment holding `CONTRACT_VERSION` from `contracts.lock.json`.
- `src/gen/contracts.ts` is **committed**. CI step: `npm run gen:types && git diff --exit-code src/gen`. If a Pydantic model changes and the lock is updated but the frontend is not regenerated, CI fails.
- A Vitest test `contract-version.test.ts` asserts the version header equals `contracts.lock.json`.
- Types are compile-time only. No runtime validator (Ajv, Zod) ships in the bundle. At the one trust boundary where shape matters at runtime (SSE events), `api/guards.ts` has a tiny hand-written `isTaskEvent` check (discriminant and required fields) that drops malformed events and logs a console warning.
- In tests, fixtures are validated against the real JSON Schemas with Ajv (dev dependency), so the mock Brain cannot drift from the contract either (§15).

Brain-specific request/response shapes that are not in `stitch_common` today (`BriefingRequest`, `BriefingAccepted`, `OrganHealth`, `AskRequest`, `AskResponse`, `EvalsLatest`, event payloads) must be added to `stitch_common` as `brain_api.py` so they flow through the same pipeline. This is a proposed contract change.

### 4.2 Client
`api/client.ts` is a thin typed `fetch` wrapper: `getOrgans()`, `startBriefing()`, `cancelBriefing()`, `getBriefing()`, `getEvidence(runId, pointer?)`, `ask()`, `transcribe()`, `speak()`, `getEvals()`. Each call has a timeout (AbortController), maps HTTP 429 to `RATE_LIMITED`, network errors to `UNREACHABLE`, and returns a discriminated `Result<T, ApiError>` (no thrown exceptions in UI paths).

### 4.3 Evidence and chart data
The briefing's claims only carry `EvidenceRef`s. Charts need whole tool outputs (forecast arrays, equity points, shadow prices, districts). The client collects the unique `run_id`s from the briefing's evidence and calls `GET /evidence/{run_id}` for each, expecting the full `ToolResult` (a proposed clarification of BRN-R5.4; the pointer query form `?pointer=` returns one value). Results are cached in a `Map<run_id, ToolResult>`. Selectors then read typed fields (`ledger.sensitivity_report.out.equity_tradeoff`, and so on). Evidence resolution for the drawer uses the same cache.

## 5. Visual system

Consistent with `ui-style.md`; additions are marked **new**.

### 5.1 Spacing, radius, layout
- Spacing: 4 px scale: `1=4, 2=8, 3=12, 4=16, 5=20, 6=24, 8=32, 10=40, 12=48, 16=64`.
- Radius: `sm 2`, `md 4`, `lg 8`, `jar 12` (jars and cards). 
- Container: max 1680 px at 1920; gutters 16 (360), 24 (768), 32 (1280+).
- **Min target size 44 px** (AA requires 24, WCAG 2.5.8). 
- z-index scale: `base 0, map-ui 10, header 20, drawer 40, awakening 50, toast 60`.

### 5.2 Type scale (**new**; base 16 px, ratio 1.25)
| Token | Size / line-height | Use |
|---|---|---|
| `text-xs` | 12 / 16 | map engraving, captions (never body) |
| `text-sm` | 14 / 20 | secondary, table cells |
| `text-base` | 16 / 26 | body (fg-0) |
| `text-lg` | 20 / 28 | card headings |
| `text-xl` | 25 / 32 | section headings (display serif) |
| `text-2xl` | 31 / 38 | page title |
| `text-3xl` | 39 / 46 | awakening title only |

Fonts: Cinzel (display, OFL), Noto Sans (body, OFL), Noto Sans Mono not needed (tabular figures via `font-variant-numeric: tabular-nums` on Noto Sans). Urdu: Noto Nastaliq Urdu for display, Noto Naskh Arabic for body (both OFL). Nastaliq needs generous leading, so `[lang=ur]` overrides: display line-height ×1.8, body (Naskh) line-height 1.9, and `text-xs` is not used for Urdu below 14 px. All loaded with `next/font/local` from `public/fonts` (woff2), `display: swap`; Urdu faces are only referenced by `[lang=ur]` rules so English users never download them. The Nastaliq file is large; its size is measured in task 4 and, if over 400 KB, it is subset to the Urdu and Arabic-script blocks plus digits. Font licenses go into THIRD_PARTY.md (FRN decision 2).

### 5.3 Colors and tokens
Base tokens exactly as in `ui-style.md`, plus (**new**):

| Token | Value | Use |
|---|---|---|
| `--border-ui` | `#5f7280` | borders of controls (non-text 3:1) |
| `--border-subtle` | `#3a4752` | decorative dividers only |
| `--blood-text` | `#ff8a94` | text-size danger labels (AAA); `--blood` is for icons and fills |
| `--water-perm` | `#2a6f68` | permanent water fill on the map |
| `--surface-focus` | `--lightning` | 2 px focus ring, 2 px offset |

Glow tokens (static; only opacity of the glow layer animates):
```
--glow-flood : 0 0 6px #2cf5c099, 0 0 18px #2cf5c055
--glow-organ-calling : 0 0 8px #9fd3ffcc, 0 0 24px #9fd3ff66
--glow-organ-done    : 0 0 6px #2cf5c066
--glow-organ-unwell  : 0 0 8px #ff9d3caa, 0 0 20px #ff4d5e55
```
Glow never replaces a border (`ui-style.md`). High-contrast mode sets all glow tokens to `none`, `--border-ui` to `#8fa09d`, `--fg-0` to `#ffffff`, backgrounds to `#000`, and removes background textures.

### 5.4 Motion specs
All animations are declared in `motion/registry.ts` (id, kind, duration, repeat, flash timestamps) and consumed by components, so the flash-rate test (FRN-P5) can inspect every animation without rendering.

Durations: `instant 80 ms`, `quick 160`, `base 240`, `slow 400`, `awaken ≤ 2400`. Easings: `out = cubic-bezier(.22,1,.36,1)` (enter), `inOut = cubic-bezier(.65,0,.35,1)` (state change), `linear` (waveform, pulse line).

| Animation | Spec |
|---|---|
| Jar `calling` twitch | `transform` only: x ∈ [0,-2,2,-1,1,0] px, rotate ∈ [0,-1,1,0]°, 420 ms `inOut`, repeating every 1300 ms until result. Glow layer opacity 0.55 to 1 on a 1300 ms sine. |
| Jar `done` | glow layer opacity eases to 0.6 in 400 ms, then static. |
| Jar `unwell` | gentle flicker: opacity of the amber glow 0.7 to 1 and back over 900 ms, repeating; no layout change; plus static icon and text. |
| Jar `idle` / `disabled` | no animation; disabled is desaturated with a strike-through icon and text "disabled". |
| Card enter | opacity 0 to 1 and `translateY(8px)` to 0, 240 ms `out`, 40 ms stagger, max 8 cards staggered. |
| Pulse line | SVG path dash-offset scroll, 2400 ms linear loop. |
| Heartbeat strip | path scaled in y by confidence; one pulse every 1200 ms. |
| Lightning awakening | §5.5 |

Low-power fallback (`fx=lite`): no twitch, no stagger, glows static, no SVG filter blur (replace with a solid 1 px outer ring), lightning becomes the reduced-motion fade. `fx` is chosen once per session: `none` if `prefers-reduced-motion`, `lite` if `hardwareConcurrency <= 2` or `deviceMemory <= 2` or the boot frame-rate probe averages under 40 fps over the first 500 ms, else `full`. Only `transform` and `opacity` are animated, which keeps the compositor path and the 60 fps target (FRN-R12.2).

### 5.5 Lightning awakening (FRN-R1)
Overlay `LightningAwakening`, `aria-hidden="true"`, fixed, `pointer-events: none` except the Skip button.

Boot timeline (total 2300 ms, under 2500):
| t (ms) | Event |
|---|---|
| 0 to 600 | charge-up: SVG bolt paths draw in (stroke-dashoffset), background stays dark, no flash |
| 700 | flash 1: overlay opacity 0 to 0.30 in 60 ms, back to 0 in 200 ms |
| 1200 | flash 2: same envelope (gap 500 ms from flash 1) |
| 1300 to 2300 | afterglow: jars light in sequence (eyes, oracle, library, ledger, voice, 100 ms apart) as health arrives; overlay fades out |

Flash rule: **at most 2 flash onsets in any sliding 1000 ms window and a peak overlay luminance step of ≤ 0.30 of full white** (stricter than 3 Hz, and below the WCAG general-flash threshold area/luminance rules). Completion timeline (after `briefing`): 1200 ms, one flash at 300 ms, afterglow.

Skip: the button is the first focusable element while the overlay is visible; Esc, Enter, Space, or a click anywhere also skip. The overlay never traps focus and never blocks the page for longer than the health fetch plus the timeline. If health fetch takes longer than the timeline, the animation ends and jars show skeleton "loading" state.

Reduced motion (`fx=none`): a single 200 ms opacity fade of the overlay to 0.12 and back (one flash event, no bolts drawn, no repeat), and the afterglow becomes an instant state paint.

## 6. Component tree

```
<Providers: LangProvider, FxProvider, BenchProvider (reducer), UiProvider, SoundProvider, StorageProvider>
<SkipLinks/> <LiveRegion/> <LightningAwakening/>
<AppShell>
  <Header>  Logo  <ModeBadge demo|live/>  <LiveToggle/>  <LanguageToggle/>  <HighContrastToggle/>  <SoundToggle/>  <NavLinks evals about/>
  <OfflineBanner/>  <DecisionSupportNotice/>
  <main>
    <ScenarioControl/>          region, scenario select, live toggle, Run, Cancel, per-organ progress
    <LabBench>                  table surface
      <OrganJar id=eyes/> <OrganJar id=oracle/> <OrganJar id=library/> <OrganJar id=ledger/> <OrganJar id=voice/>
    </LabBench>
    <OrganDrawer/>              last call, timing, raw JSON summary
    <section aria-label=map>   <HauntedMap/> <MapLayerToggles/> <TimeSlider/> <MapTable/> </section>
    <VitalSignsBriefing>
      <ConfidenceHeartbeat/>
      <ConflictBanner/>
      <VitalCard extent> <EyesLabels/> <ClaimList/> </VitalCard>
      <VitalCard forecast> <ForecastBandChart/> <ModeledLabel/> <ClaimList/> </VitalCard>
      <VitalCard guidance> <GuidanceCitations/> | <RefusalCard/> </VitalCard>
      <VitalCard allocation> <AllocationTable/> <CostBenefit/> <ShadowPricePanel/> <EquityTradeoffChart/> </VitalCard>
      <VitalCard caveats> <CriticNotes/> <DemoLiveNotice/> </VitalCard>
    </VitalSignsBriefing>
    <ClaimEvidenceDrawer/>      native <dialog>, focus returns to the invoking button
    <AskTheCreature/>
    <VoiceControls/>            Play briefing, Record, waveform, provider disclosure
  </main>
  <Footer/>
</AppShell>
```

Each component below lists inputs and rules.

- **OrganJar** (hand-built SVG, FRN decision 1). One `<button>` per jar (name, status icon, status text, `aria-describedby` for secondary text). Five SVG illustrations (eye-in-jar, crystal vial, book-in-jar, brass scales, horn) drawn on a shared 96 × 120 viewBox with a `glow` layer group, a `body` group, and a `liquid` group; state variants change only classes and the glow opacity (Motion `m.g` with `LazyMotion`). Status icon set (24 px SVG, each distinct by shape): idle `circle-dot`, calling `bolt`, done `check`, unwell `warning-triangle`, disabled `slash-circle`. Status text from dictionary: "Idle", "Calling…", "Done", "The organ is unwell", "Disabled".
- **LightningAwakening**: §5.5.
- **HauntedMap**: §8.
- **VitalSignsBriefing** and **VitalCard**: card per section id; `status: ok|partial|unavailable` selects the panel state (§10). Claims render as `<ClaimItem>`: text plus an `EvidenceButton` (`aria-label` "Show evidence for: <first 60 chars>"); a claim without evidence cannot render the item (FRN-P4: the component throws in dev and renders a hidden "unverified claim removed" notice in prod, and the test asserts the former).
- **ClaimEvidenceDrawer**: native `<dialog>` with `showModal()` (focus trap and Esc for free), lists each `EvidenceRef` with organ icon, tool, JSON pointer (in `<bdi dir=ltr>`), resolved value (via `getEvidence`), and for guidance claims the quote (`<blockquote lang=...>`), `publisher`, `title`, `page`, and `url` if present. Loading and error states inside the dialog. Focus returns to the invoking button on close.
- **ConflictBanner**: always above the cards when `conflicts.length > 0`; heading "The creature disagrees with itself"; one card per conflict with description, resolution tag (text: flagged, reconciled, escalated), and **both sides' evidence buttons side by side**. No side is styled as "correct".
- **RefusalCard**: labelled outcome ("Refused: insufficient evidence", etc.), reason text, `closest_hits` as citations. Neutral tone, not an error style (FRN-R5.4).
- **ShadowPricePanel**: from `sensitivity_report.shadow_prices`. Binding supply constraints show "One more <unit> of <commodity> adds about <value> <unit-of-value>"; budget shows "One more budget unit buys about X"; non-binding shows "Not limiting: more of this buys nothing right now". A footnote states `basis = lp_relaxation` in plain words. Values formatted with the same number formatter as the rest.
- **EquityTradeoffChart**: §9.2.
- **ForecastBandChart**: §9.1. Every Oracle number sits inside `<OracleValue>` which always renders `ModeledLabel` ("Modeled (GloFAS)", from `target_label` when present). The words "gauge" and "observed" are never used for Oracle output (FRN-R14.3).
- **EyesLabels**: two separate chips, always both visible together in the extent card and in the Eyes drawer: (1) "Demo scene: Sindh, Aug 2022" built from `source_scene` and `mode`; (2) "Model validated on Sen1Floods11 test split" built from `validation.eval_dataset`. When `validation.validated_for_region` is false a third plain-text line states "Not validated for this region." The Sindh extent is never labelled validated.
- **AskTheCreature**: one `<textarea>` (max 500 chars, live counter, `aria-describedby`), submit, optional mic button (rendered only when Voice is `ready`). Calls `POST /ask`. Result renders through the same `GuidanceCitations` or `RefusalCard`. States: loading, error ("the organ is unwell"), refusal, rate limited (429), too long.
- **EvalHeartbeat**: §13.
- **VoiceControls**: §12.
- **SoundToggle**: `<button aria-pressed>`, default off, persisted (`localStorage['stitch.sound']`). §14.
- **LanguageToggle**: a link to the same route in the other `lang`. `hreflang`, current language marked `aria-current`.
- **HighContrastToggle**: `<button aria-pressed>`; sets `data-contrast` on `<html>`; default follows `prefers-contrast: more`; persisted.

## 7. Scenario control and run flow (FRN-R3)
Region and scenario come from a small static `scenarios.json` in the frontend (Sindh Aug 2022 demo default; it matches the demo dataset ids). `live` toggle is disabled with an explanation when `navigator.onLine` is false or `GET /organs` reports `live_available: false` (proposed field). While running: the Run button is disabled (`aria-disabled` with reason), per-organ progress shows queued/calling/done/unwell from the reducer, and Cancel calls `DELETE /briefings/{id}` (proposed endpoint; the Brain spec has no cancel route). If cancel is not implemented, Cancel closes the stream locally and marks the run "abandoned", and says so.

## 8. Haunted map (FRN-R4)

### 8.1 Data and style, all self-hosted
- **No tiles for the demo.** A demo scene covers one province (about 30 districts), so geometry is plain GeoJSON served from `public/map/`. This removes the tile server, the PMTiles library, and all HTTP range-request configuration. PMTiles (BSD-3-Clause reference implementation, public-domain spec, verified) is the documented upgrade path if a second, larger region is added; it would be served as a static file by Caddy, which supports range requests.
- `context.geojson`: Natural Earth (public domain) country and admin-1 lines, clipped to a generous bbox around Sindh and simplified so the file stays under about 150 KB.
- `districts.geojson`: district polygons with the same `district_id`s as the Ledger demo dataset (`ledger://scenario/{id}/districts`), simplified with a 0.005° tolerance, plus a precomputed `centroid` property for markers and labels. Source and license (OSM-derived extract, ODbL, or geoBoundaries CC BY 4.0, whichever matches the Ledger MANIFEST; the geometry must be identical to the Ledger's so that `district_id`s join) is recorded in `data/demo/MANIFEST.md` and on-map attribution.
- `style.json`: MapLibre style spec v8 with `sources` pointing at same-origin GeoJSON, **no `glyphs` and no `sprite`** (no symbol layers), so no external fonts or tile URLs exist. A CI test greps the style and all JS for `http` URLs other than same-origin.
- Layers, bottom to top: `background` (`#07090c`), `context-fill` (`#0d1217`), `context-line` (bone at 0.25 opacity, 0.5 px), `water-perm` (fill `--water-perm` at 0.55 opacity), `flood-fill` (fill `--flood-glow` at 0.45), `flood-glow-outer` (line, width 10, `line-blur` 8, color `--flood-glow`, opacity 0.25), `flood-glow-mid` (line, width 5, blur 3, opacity 0.45), `flood-edge` (line, width 1.2, opacity 0.95), `districts-line` (bone, 0.8 px, dashes none), `reference-line` (dashed bone, `line-dasharray [2,2]`), `allocation-circles`.
- **Why the glow is stacked blurred lines.** MapLibre fill layers have no blur property. Line layers do (`line-blur`), so the flood polygon outline is drawn three times with different widths and blur for the luminous halo, over a translucent fill. This is a documented style-spec technique, costs three layers, and animates nothing.
- **Permanent water is dimmer** than flood (`#2a6f68` at 0.55 versus `#2cf5c0` at 0.45 plus halo). Contrast between the two fills is 4.18:1 (computed), so they remain distinguishable, and a legend with text and pattern swatches repeats the difference (not color alone).
- "Ouija board" look: near-black parchment-toned background, a subtle SVG noise overlay as a CSS background on the map container (not in WebGL), and engraved labels (§8.2).

### 8.2 Labels without glyphs
District names are `maplibregl.Marker`s with DOM elements: `<span lang dir><bdi>name</bdi></span>` in Cinzel (en) or Noto Nastaliq (ur), styled with `text-shadow` to look engraved. This gives correct Urdu shaping using the browser, avoids shipping glyph PBFs and the MapLibre RTL text plugin, and lets labels be real text for assistive tech. Markers are decluttered by zoom (hide labels for districts whose projected area is under 1,200 px²), computed in a pure `lib/geo.ts` function. Names come from district properties (`name_en`, `name_ur`).

### 8.3 Interaction
- Layer toggles (flood, permanent water, districts, allocation, reference extent) are real checkboxes in a `<fieldset>`; each sets layer `visibility`.
- Time slider: `<input type=range>` shown only when the briefing carries more than one Eyes date (otherwise hidden, FRN-R4.3). Keyboard native.
- Allocation: one `circle` layer; radius is `["*", k, ["sqrt", ["get","people_covered"]]]` so area is proportional to value; `k` is computed so the largest circle is 28 px at 1280 px. A text legend states the scale. Hover or keyboard focus opens a `Popup` with district, flooded km², allocation per commodity, coverage, access mode, unreached people.
- **Keyboard**: the canvas is focusable (`tabindex=0`, MapLibre's keyboard handler: arrows pan, `+`/`-` zoom, shift-arrows rotate which is disabled), a visible focus ring, and a persistent instruction line: "Arrow keys pan. Plus and minus zoom. Press T for the table." (`T` toggles the table; the table is also reachable by a visible button.) Each marker is also a Tab stop via a hidden-until-focused list in the table, not through the canvas.
- **Table alternative** (`MapTable`, FRN-R4.5): a real `<table>` with `<caption>`, columns: district, flooded km², flooded fraction, population affected, allocation (per commodity), coverage, access mode. Sortable (buttons in `<th>`, `aria-sort`). It renders even if WebGL fails (`maplibregl.supported()` false or context lost), in which case the map area shows "map unavailable" and the table is shown by default.
- `fitBounds` once per run; no auto-camera motion in reduced-motion mode (jump instead of ease).
- Map is always LTR geographically; only the surrounding chrome mirrors.
- The map chunk is `next/dynamic` loaded with `ssr:false` (moot for export but explicit) and mounts when the section is near the viewport (IntersectionObserver), so it never counts toward first-load JS.

## 9. Charts: hand-rolled SVG

**Decision.** Three simple charts (forecast band, equity trade-off, heartbeat strip) are drawn as SVG by small React components over a 60-line `lib/scale.ts` (linear and time scales, nice ticks). No chart library ships.
- Why: libraries such as Recharts or Chart.js are tens to hundreds of KB gzip (not measured here; size is a budget risk, not a certainty) and add their own accessibility gaps. Our needs (band, line, step marker, slider) are small. d3-shape (ISC license, unverified here) is a possible add for path generation; not needed at this scale.
- Cost: more tests of our own. Mitigated by pure geometry functions (`bandPath`, `equitySegments`) that are unit and property tested.
- Every chart: wrapped in `<figure>` with `<figcaption>`, `role="img"` and an `aria-label` summary, plus a "show data table" disclosure with the same numbers as a real `<table>`. Time axes stay left to right in RTL (`dir="ltr"` on the chart, labels in `<bdi>`).

### 9.1 ForecastBandChart (FRN-R5.1)
Inputs: `forecast[]` (date, `discharge` p10/p50/p90), `danger_threshold_m3s`, `exceedance_prob[]`. Draws: a band (p10 to p90, 0.25 opacity `--lightning`), p50 line, danger threshold as a dashed `--ember` line with a text label, exceedance probability as a bar strip below. The title and legend always contain "Modeled (GloFAS)" and the unit `m³/s` inside `<bdi>`. Axis values and the tooltip are `<OracleValue>` elements. Pulse-line decoration is separate and decorative (`aria-hidden`).

### 9.2 EquityTradeoffChart (FRN-R5.7, FRN-P7)
Data: `equity_tradeoff[]` (floor, status, total_coverage, people_covered), the run's `equity.floor_applied` and `equity_cost`.
- `lib/equitySegments.ts`: `buildSegments(points)` sorts by floor and returns `{segments: Point[][], infeasible: {from,to}[]}`. A segment is a maximal run of consecutive `optimal|feasible` points. A polyline is drawn **per segment only**; the line is never drawn across or into an infeasible point. Infeasible floors render as a hatched band with text "No feasible plan at this floor" and an icon.
- Slider: native `<input type=range>` whose steps are the precomputed floors (index slider, `min=0 max=n-1 step=1`), `aria-valuetext` "Floor 60%: covers 12,300 people" or "Floor 90%: infeasible". It snaps to points. No re-solve and no interpolation (FRN-R5.7). Left/right arrows move one point; Home/End jump to ends.
- Markers: the run's current floor (a labelled vertical line) and the `equity_cost` (an annotation: "Equity floor cost: X people covered").
- Right-to-left note: the floor axis is numeric and stays left to right.

### 9.3 Heartbeat strip
`ConfidenceHeartbeat`: an SVG pulse path whose amplitude and beat rate come from `briefing.confidence` (beat period fixed at ≥ 1200 ms to respect FRN-P5); the numeric value and a text band (low/medium/high) are always shown beside it.

## 10. States per panel (FRN-R10, `ui-style.md`)

`<Panel>` is the single wrapper. It takes `state: loading|empty|partial|error|offline|success` and renders slots, so every panel is covered by one test matrix.

| Panel | loading | empty | partial | error | offline/demo |
|---|---|---|---|---|---|
| Bench (jars) | skeleton jars, health fetch | n/a | some jars `unwell`/`disabled` | whole bench: "The creature sleeps" with Retry (Brain unreachable) | demo banner |
| Map | skeleton + "stirring the board" | "Run a briefing to see the flood" | extent missing: base map + table says "Eyes is unwell" | map unavailable, table shown | labelled demo scene |
| Extent card | skeleton lines | before first run | section `partial`, names what is missing | Eyes `unwell`: reason + retry + "briefing is missing flood extent" | demo label |
| Forecast card | skeleton chart | before first run | some days missing | Oracle `unwell` (same pattern) | demo + Modeled label |
| Guidance | skeleton | before first run | answered, some citations missing | Library `unwell` | demo corpus label |
| Allocation | skeleton table | before first run | Ledger ran without sensitivity (no trade-off chart, notes why) | Ledger `unwell` | demo |
| Ask | spinner in button | placeholder | n/a | "the organ is unwell" | demo |
| Voice | "preparing audio" | idle | text only | Voice unwell: text alternative shown | disabled (cut) |
| Evals | skeleton | "No eval run yet" | some organs `not_run` | fetch error | demo |

Error copy always has: the plain message, the machine reason (`error.code` and message), a Retry (when `retryable`), and **what the briefing is missing** (derived from `selectMissingSections`). Offline: a banner "Offline: showing the demo scene" when `navigator.onLine` is false or a live run fell back to demo (briefing `mode=demo` while `live` was requested).

## 11. Accessibility (FRN-R11)

### 11.1 Contrast verification
Computed with the WCAG 2.x relative-luminance formula (`scripts/contrast.mjs` regenerates this table in CI; the values below were computed during design).

| Foreground | on `bg-0` #07090c | on `bg-1` #0d1217 | on `bg-2` #151c24 | Requirement | Result |
|---|---|---|---|---|---|
| `fg-0` #eef3f2 (body) | 17.79 | 16.79 | 15.32 | AAA body ≥ 7 | pass |
| `fg-1` #b7c4c2 (secondary) | 11.10 | 10.47 | 9.55 | AA ≥ 4.5 (exceeds AAA) | pass |
| `flood-glow` #2cf5c0 | 14.17 | 13.38 | 12.20 | text/icons | pass |
| `lightning` #9fd3ff (focus ring, links) | 12.56 | 11.86 | 10.82 | non-text ≥ 3, text AAA | pass |
| `ember` #ff9d3c | 9.63 | 9.09 | 8.29 | text AAA | pass |
| `bone` #e8dfc8 | 15.02 | 14.18 | 12.93 | text AAA | pass |
| `blood` #ff4d5e | 6.15 | 5.80 | 5.29 | AA only | **icons and fills only**; not for body text |
| `blood-text` #ff8a94 (new) | 8.84 | n/a | 7.61 | AAA | pass; used for danger text |
| `border-ui` #5f7280 on bg-2 | n/a | n/a | 3.44 | non-text ≥ 3 | pass |
| `border-subtle` #3a4752 on bg-2 | n/a | n/a | 1.80 | decorative only | not used for control boundaries |
| `bg-0` text on `flood-glow` button | 14.17 | | | AAA | pass |
| high-contrast border #8fa09d on #000 | 7.68 | | | | pass |

Findings: the `ui-style.md` tokens meet the AAA body requirement. `--blood` (#ff4d5e) reaches only 5.29:1 on `bg-2`, so it must not carry text-size copy; this design adds `--blood-text`. A lint test fails if `text-blood` is used on a text element.

### 11.2 Plan
- **WCAG 2.2 AA** checklist items beyond contrast: 2.4.11 focus not obscured (sticky header height is added to `scroll-padding-top`), 2.5.8 target size (44 px), 2.5.7 dragging alternatives (map pan has arrow keys, sliders are native inputs), 3.3.7 redundant entry (the question text survives a failed submit), 1.4.10 reflow at 360 px, 1.4.12 text spacing (no fixed heights on text containers).
- **Keyboard**: Tab order follows DOM order = visual order in both LTR and RTL (no `tabindex>0`, no order hacks). Skip links: "Skip to bench", "Skip to briefing", "Skip to ask". Visible focus: 2 px `--lightning` ring, 2 px offset, on every interactive element, including SVG jars (wrapped in `<button>`).
- **Live region**: `LiveRegion` (polite, `aria-atomic=false`) receives `announcements` from the reducer: "Eyes is calling", "Eyes finished in 3.2 seconds", "Oracle is unwell: <reason>" (assertive via a second `role=alert` region), "Briefing ready: 5 sections, 1 conflict". Queue is deduped by seq and rate-limited to one message per 400 ms.
- **Dialogs**: native `<dialog>` for the evidence drawer and the TTS disclosure.
- **Status without color**: every state has icon shape plus text.
- **Headings**: one `<h1>`; each VitalCard has an `<h2>`; landmarks `header`, `nav`, `main`, `footer`; map section `role="region"` with a label.
- **Language**: element-level `lang` on mixed content (Brain claims in Urdu inside an English UI shell and the reverse).

## 12. Voice UI (FRN-R6, R14.4, R15)
- `VoiceControls` renders only a **disabled** state when the Voice organ is `disabled` or `unwell` (visible, labelled, with the text input alternative nearby); nothing else depends on it (FRN-R15.2).
- **Play briefing**: user presses Play; the client sends `POST /voice/speak {briefing_id, lang}` (the Brain builds the spoken script server-side, so the endpoint cannot be used as an open TTS proxy; see voice-mcp design §12) and plays the returned `audio_b64` via a Blob URL in an `<audio controls>` element (mp3 or wav, whichever `format` the result states). Never autoplays; the first `.play()` happens in the click handler. Audio is also routed through an `AnalyserNode` for the waveform canvas (decorative, `aria-hidden`, redrawn at ≤ 30 fps).
- **Disclosure** (FRN-R14.4): `GET /organs` carries Voice `meta: {tts_provider, hosted}` (proposed). When `hosted` is true and no consent is stored, a `<dialog>` states which provider receives the briefing text (and that no user audio is ever sent to it) before the first request. Consent is stored per provider in `localStorage`. After each synthesis, the UI shows "Voice by <provider> (live|cache|prerendered)" from the `speak` result.
- **Record**: press Record (permission prompt only on click). Capture uses an `AudioWorklet` that emits 16 kHz mono Float32 frames, and the client encodes a 16-bit PCM **WAV** itself (≤ 60 s is 1.9 MB). Reasons: Safari's MediaRecorder produces `audio/mp4`, which is not in the contract's `wav|webm|mp3|ogg`; WAV needs no decoder dependency on the server for the common path; the same samples feed the waveform. `MediaRecorder` with `audio/webm;codecs=opus` is the fallback when no AudioWorklet is available. Max 30 s in the UI (hard stop), well under the 60 s limit. A visible timer, level meter, and Stop button.
- **Permission handling**: `NotAllowedError` shows "Microphone blocked. Use the text box instead." and focuses the textarea; `NotFoundError` similar; insecure context (no `getUserMedia`) similar. HTTPS is required in production, and localhost counts as secure in dev.
- **Transcribe**: result fills the ask box, language auto-detected, editable, **never auto-submitted**.
- Size: the worklet and recorder code is a lazy chunk loaded on first Record or Play click.

## 13. Eval dashboard (FRN-R9)
Reads `GET /evals/latest` (shape: `evals/results/schema.json`, bootstrap design §7). One section per organ in order Eyes, Oracle, Library, Ledger, Brain; each metric is a card: label, value, target, direction arrow, pass/fail (icon + text), timestamp, dataset, mode, and a sparkline of up to 10 earlier values when history exists (not in the current schema; proposed). Oracle rows carry "Modeled (GloFAS)". A pulse line header decorates the page and flatlines when no data. States: "No eval run yet" when every organ is `not_run`; "stale" when `generated_at` is older than 7 days or `git_sha` differs from the Brain's reported build sha (shows a banner with timestamp, results still visible); partial when some organs are `not_run`. All metrics have a table view (it is a table).

## 14. Sound (FRN-R7)
All sounds are **synthesized at runtime** with Web Audio (no audio files, so no licensing or attribution burden and a smaller repo). `sound/voices.ts` defines the recipes; `sound/engine.ts` owns one `AudioContext`, created only after the user turns sound on (autoplay policy), with a master gain capped at 0.3.
| Sound | Recipe |
|---|---|
| Ambient hum | two detuned sawtooth oscillators (50 and 50.7 Hz) through a 120 Hz low-pass, gain 0.03, slow LFO on the cutoff (0.1 Hz), fades in 800 ms |
| Thunder (awakening) | white-noise buffer through a low-pass sweeping 900 to 80 Hz over 1.8 s, gain envelope attack 20 ms, decay 1.6 s, peak 0.35 of master |
| Jar twitch | 30 ms band-passed noise click at 1.2 kHz, gain 0.05 |
| Unwell | 220 Hz sine gliding down to 140 Hz over 400 ms, gain 0.06 |
| Done | soft 440 Hz sine ping, 120 ms, gain 0.04 |
Toggle off ramps master gain to 0 and suspends the context. Persisted in `localStorage['stitch.sound']`. Sound does not depend on `prefers-reduced-motion` but is off by default regardless. Voice playback is separate and always user-initiated. Tests use an `OfflineAudioContext`-free fake: recipes are pure descriptions (node graph objects) and the engine is a thin interpreter, so the recipes are unit-testable.

## 15. Internationalization and RTL (FRN-R8)
- `messages/en.json` and `messages/ur.json`: flat keys, `{name}` placeholders, plural keys use `Intl.PluralRules` (`key.one`, `key.other`). `t(key, params)` is typed from the English file's keys. Only the active language's dictionary is loaded by the `[lang]` layout.
- Completeness test: Urdu has exactly the English key set and identical placeholder names.
- **Logical CSS only**: Tailwind logical utilities (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`, `text-start`, `border-s`), and `inset-inline` in custom CSS. A Vitest scan fails the build if physical utilities (`ml-`, `mr-`, `pl-`, `pr-`, `left-`, `right-`, `text-left`, `text-right`, `rounded-l`, `rounded-r`) appear in `src/` (allow-list for the map, which is always LTR).
- **Bidi isolation**: `<Bdi>` helper (wrapping `<bdi>`) for identifiers, units, numbers with units, JSON pointers (also `dir=ltr`), run ids, and citations (publisher and page). Brain-supplied text is rendered with `dir="auto"` per element.
- **Digits**: Western digits by default. The option "Urdu-Indic digits" uses `Intl.NumberFormat('ur-PK-u-nu-arabext')` (extended Arabic-Indic digits, U+06F0 to U+06F9, which are the digits Urdu uses; `ui-style.md` says "Eastern Arabic-Indic", which names the Arabic block U+0660 to U+0669 whose 4, 5, and 6 are drawn differently from the Urdu forms. See issue list). Numbers inside claim text come from the Brain unchanged (BRN-R7.5); the UI formats only the numbers it renders itself.
- Mirroring: layout mirrors; charts' time axes, numerals' meaning, and the map do not (`dir=ltr` on those containers). Icons with direction (arrows, play) have mirrored variants via `rtl:` utility.
- Language switch round trip (FRN-P3): the DOM text of the static chrome is a pure function of `(lang, state)`; the test normalizes whitespace and compares `textContent` before and after en to ur to en.
- Briefing content is language-specific (the Brain produces it in the requested language). If the UI language differs from `briefing.lang`, a banner offers "Regenerate in Urdu" (a new run; demo mode is deterministic and fast). The chrome never auto-regenerates.

## 16. Mock Brain (build the frontend before the Brain exists)
`frontend/mock-brain/server.mjs`: a ~200-line Node server using only built-ins (`node:http`). Same origin routes as the Brain (`/api/organs`, `/api/briefings`, `/api/briefings/:id/events`, `/api/evidence/:run_id`, `/api/ask`, `/api/voice/*`, `/api/evals/latest`).
- **SSE replay**: reads `fixtures/streams/<scenario>.ndjson` (one `{delayMs, seq, event, data}` per line) and writes `id:`, `event:`, `data:` frames with the recorded delays (scaled by `?speed=`, instant in tests). It honors `Last-Event-ID` and `?last_event_id=` by skipping frames with `seq <= N`, and can drop the connection at frame K (`?drop_after=K`) to test resume.
- **Scenarios** (selected by `scenario` in the request or `X-Mock-Scenario`): `default-demo` (all five organs ok, one conflict, Library answered), `organ-error` (Oracle `unwell`), `refusal` (Library refuses), `conflict`, `partial` (Ledger without sensitivity), `slow` (6 s), `brain-down` (connection refused), `voice-cut` (Voice `disabled`), `offline-fallback` (live requested, demo returned).
- **Fixtures start hand-authored** from the contract, then `scripts/record-stream.mjs` records real Brain streams (`npm run record -- --brain http://localhost:8000 --out fixtures/streams/default-demo.ndjson`) once the Brain exists, replacing them. The fixture contract test validates every frame and REST body against the JSON Schemas (Ajv, dev only).
- MSW was considered (it also runs in Vitest) and rejected: SSE support and service-worker lifecycle add moving parts, and one fixture server serves dev, Vitest integration, and Playwright. Component tests pass props directly and need no mocking layer.

## 17. Performance (FRN-R12)
| Budget | Plan |
|---|---|
| First-load JS ≤ 300 KB gzip, excluding map and chart chunks | React and Next runtime, `LazyMotion` with `domAnimation` and `m` components (not the full `motion` bundle), Tailwind compiled CSS (JIT, small), one dictionary. Map, charts, recorder, evidence drawer, and the evals route are separate lazy chunks. `scripts/check-budget.mjs` gzips the JS files that the `[lang]/index.html` references and fails CI above 300 KB; it prints the top contributors. Real numbers are measured in task 3 (bench shell) and tracked in the PR description; this design does not assume them. |
| LCP < 2.5 s | the LCP element is static prerendered text (title and the bench skeleton), not data. The lightning overlay is SVG with no images. Fonts: only Cinzel and Noto Sans woff2 on the English path, `display: swap`, `preload` for the two used above the fold. Lighthouse CI run (lab) on the built export with network throttle "broadband" and 4x CPU slowdown. |
| 60 fps | transform/opacity only, `will-change: transform` only on jars while calling, no animated `filter` or `box-shadow`, `fx=lite` fallback (§5.4). Map: `GeoJSON` data under 600 KB total; `setData` once per run. |
| Caching | hashed static assets `immutable`, map assets cached 7 days (deployment §5). |
| Bundle hygiene | Motion's `LazyMotion` strict mode (`strict`) so accidental `motion.div` fails; ESLint `no-restricted-imports` for `motion/react` full `motion` export. |

## 18. Test plan

### 18.1 Unit and property (Vitest, Testing Library, fast-check)
`fast-check` is MIT (verified). Vitest profile: 200 runs in CI (`FC_NUM_RUNS`), 30 in dev, with seeds logged.

| ID | Test | File |
|---|---|---|
| FRN-P1 | Generator makes arbitrary valid `TaskEvent` sequences (any order of the five organs, repeats, errors, `briefing`, cancels, stream-lost). A reference model computes each organ's expected state from the last relevant event. Assert: every organ has exactly one state in the five-value set and it equals the model's. | `property/reducer.p1.test.ts` |
| FRN-P2 | (a) `reduce(events)` deep-equals `reduce(events)` on a second run; (b) feeding any prefix, then replaying the whole stream with duplicates, gives the same final state as the plain stream (idempotent resume); (c) splitting the stream at any point and applying in two batches equals one batch. | `property/reducer.p2.test.ts` |
| FRN-P3 | Render the bench chrome with fast-check generated sequences of language toggles of even length; `textContent` equals the initial. Also the dictionary completeness test. | `component/i18n.p3.test.tsx` |
| FRN-P4 | For generated `Briefing`s (claims with 1..3 evidence refs, plus a negative claim with none), every rendered claim has an accessible button named by the evidence label; a claim without evidence throws in test mode. | `component/claims.p4.test.tsx` |
| FRN-P5 | `motion/flashRate.ts` computes the maximum number of flash onsets in any 1000 ms sliding window from `registry.ts`. Test asserts ≤ 2 for every registered animation (boot, completion, reduced-motion, jar loops) and that repeating animations have period ≥ 800 ms. Property: for generated timelines the function equals a brute-force window count. | `property/flashRate.p5.test.ts` |
| FRN-P6 | Render every Oracle-bearing component (ForecastBandChart, claim list for an oracle-evidenced claim, tooltip, eval rows) with generated data; every `[data-oracle-value]` has a `[data-modeled-label]` in the same container; no rendered string contains "gauge" or "observed" for Oracle components (en and ur dictionaries scanned too). | `component/oracleLabel.p6.test.tsx` |
| FRN-P7 | For generated points with arbitrary infeasible subsets: every polyline segment contains only feasible points, no segment spans an infeasible index, infeasible ranges equal the complement, and the slider's snap values equal the input floors (no interpolated values). | `property/equitySegments.p7.test.ts` |
| geo | `bandPath` monotone, `labelVisible` pure; `scale.ts` round trip | `unit/*.test.ts` |
| contracts | generated types are current, fixtures validate against schemas, `contracts.lock.json` version equals types header | `unit/contracts.test.ts` |
| lint | no physical CSS utilities, no `text-blood` on text, no external URLs in `public/map/style.json` or built JS | `unit/hygiene.test.ts` |
| panels | `<Panel>` renders every state (table in §10) without a11y errors in jsdom | `component/panel.test.tsx` |

### 18.2 Playwright (FRN-R13)
Two projects: `mock` (static export served locally plus the mock Brain; runs in the frontend CI job and in dev) and `stack` (the same smoke subset against the Compose stack, run by the deployment CI).

| Scenario | Steps | Assertion |
|---|---|---|
| boot | load `/en/` | overlay appears, Skip works with Esc, five jars render with status text, health fetched |
| default briefing | press Run (demo) | jars go calling then done in order, briefing sections render, awakening plays shorter, live region announces completion |
| organ error | scenario `organ-error` | Oracle jar shows "The organ is unwell" with reason, forecast card shows error pattern and what is missing, other sections intact |
| evidence drill-down | click a claim's evidence button | dialog opens, shows organ, tool, pointer, value; guidance shows quote and page; Esc closes; focus returns |
| Urdu RTL | switch to `ur` | `html[lang=ur][dir=rtl]`, chrome mirrored (bounding boxes), identifiers inside `<bdi>`, charts stay LTR, switch back restores text |
| keyboard only | no mouse: Tab to scenario, Run, to a claim, open drawer, close | everything reachable and visible focus; skip links work |
| reduced motion | `reducedMotion: 'reduce'` | no bolt paths in DOM, no repeating animation, single fade |
| equity chart | move slider to an infeasible floor | text "infeasible", no line across the gap |
| ask | submit a question; refusal scenario | answer with citations; refusal card |
| voice cut | scenario `voice-cut` | Voice jar `disabled`, text input present, nothing else broken |
| offline/brain-down | `brain-down` | "The creature sleeps" with Retry |

**Accessibility scan.** `@axe-core/playwright` runs after each scenario state above; the test fails on `serious` or `critical` violations (FRN-R13.2). `@axe-core/playwright` and axe-core are developer dependencies; their license (believed MPL-2.0) is not verified here and must be checked and listed in THIRD_PARTY.md when added.

### 18.3 Manual checks (recorded in the PR)
Screen-reader pass (NVDA on Windows) of boot, run, evidence drawer, map table; 200% zoom; Windows High Contrast; a real Urdu reader reviewing the translated strings.

## 19. Risks

| Risk | Mitigation |
|---|---|
| Brain event payload shapes undefined | Proposed contract change; reducer isolates assumptions in `events.ts`; fixtures are the executable spec until the Brain lands |
| Brain not finished when frontend starts (Nov 21) | Mock Brain and hand-authored fixtures; no frontend task depends on a real Brain until task 19 |
| Nastaliq font weight hurts Urdu LCP | Urdu LCP measured separately; subset and `swap`; Urdu is not the default |
| Static export blocks a needed Next feature | None required; if one appears, switch to `output: 'standalone'` (a Node container) with the budget in deployment §3 |
| Hand-rolled charts accessibility bugs | tables for every chart, axe in the Playwright suite |
| Map WebGL failure on weak machines | table fallback; `maplibregl.supported()` check |
| 3 Hz rule violated by an unnoticed animation | `registry.ts` is the only place animations are declared; ESLint bans raw `animate=` outside it |
| ODbL share-alike for OSM-derived district geometry | attribution on the map, `MANIFEST.md`, ODbL notes in THIRD_PARTY.md; the derived GeoJSON is itself published under ODbL in the repo (README note) |

## 20. Facts checked while writing this design
- Licenses (from each repository's LICENSE via the GitHub API): `json-schema-to-typescript` MIT, `fast-check` MIT, `motion` MIT, MapLibre GL JS BSD-3-Clause, PMTiles reference implementation BSD-3-Clause (spec public domain), `msw` MIT.
- Contrast ratios computed with the WCAG relative-luminance formula (table §11.1).
- Not verified (no source fetched): exact gzip sizes of Next, MapLibre, Motion, and Noto Nastaliq Urdu; `@axe-core/playwright` license; Tailwind and Next current major versions (pin at scaffold time); the claim that `domAnimation` features cut Motion's size (documented by Motion, to be confirmed in task 3's bundle analysis).

## Proposed contract changes
None to `mcp-contracts.md` tool schemas. Additions to the Brain API (brain spec and `stitch_common/brain_api.py`) that the frontend needs:
1. **Event envelope and ids**: every SSE frame carries `id: <seq>` (monotonic integer per task) and `event: <type>`; payload shapes defined for `plan` (tasks and organs), `organ_call` (`organ`, `tool`), `organ_result` (`ok`, `duration_ms`, `run_id`, `error?` with `code`, `message`, `retryable`, a small `summary`), `conflict`, `critic`, `briefing` (the full `Briefing`), `error`. A `: ping` comment every 15 s.
2. **`GET /organs`** returns `{organs: [{organ, status: ready|degraded|unwell|disabled|incompatible, reason?, meta?}], live_available: bool, mode_default, brain_version, contract_version, build_sha}`; Voice `meta` has `tts_provider` and `hosted`.
3. **`POST /briefings`** returns `{briefing_id, task_id}`; **`DELETE /briefings/{id}`** cancels.
4. **`GET /evidence/{run_id}`** returns the full `ToolResult`; `?pointer=` returns one value (with organ and tool).
5. **`POST /ask`** returns `{ask_id, result: ToolResult<answer_with_citations out>}`; error `429` body uses the `ToolResult` error shape.
6. **`GET /healthz`** on the Brain (for Compose and the status page).
7. **Evals results**: optional `history: [{timestamp, value}]` (last 10) per metric, and `generated_at` plus `git_sha` at the top level (already in bootstrap design §7).
8. Accept `Last-Event-ID` header and `?last_event_id=`.
9. Brain request body limit large enough for a 60 s base64 WAV (≈2.6 MB); set 4 MB for `/voice/transcribe`.
10. **`POST /voice/speak` takes `{briefing_id, lang, voice?}`**, not free text (voice-mcp design §12, protects the TTS quota). The Voice `speak` result gains an optional `voice` field (contract 0.4 proposal in the voice design) and `GET /organs` Voice `meta` includes `capabilities` so the UI can hide only the microphone when just `speak` is available.
