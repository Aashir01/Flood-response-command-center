# brain: Design

Implements `requirements.md` (BRN-R1..R14). Contracts: `mcp-contracts.md` v0.3 (§2 shared types, §8 Brain API, §8b resource). The Brain is a FastAPI service plus an MCP client. It is not an MCP server.

## 1. Overview

The Brain turns a request `{region, scenario, lang, mode}` into a `Briefing` in which every claim traces to an organ output.

1. A planner produces a task graph (a DAG). A custom asyncio executor runs it. No agent framework.
2. Every organ `ToolResult` is stored in an evidence store before anything reads it.
3. Claims are produced by code: templates fill typed slots from evidence. An LLM may only rephrase prose or translate organ-authored text, and every rewrite passes number, unit and language checks or is discarded in favour of the template text.
4. A rule engine (declarative YAML, typed, no `eval`) compares organ outputs and raises conflicts. One rule can trigger a single automated reconciliation.
5. A critic re-verifies every claim from the stored evidence, repairs or removes failures, and sets `critic.passed`.
6. Progress streams to the browser as `TaskEvent`s over SSE.

All logic that decides what the briefing says lives in `core/` as pure functions. `runtime/` holds I/O (MCP clients, executor, LLM calls, stores). `api/` is thin. This keeps the property tests fast and deterministic.

Central invariant (BRN-P1): the text of a claim is a deterministic function of (template, slot values, language), and each slot value is read from, or derived by a named pure function from, resolvable evidence.

## 2. Layout

```
brain/
  pyproject.toml  README.md
  config/
    scenarios.yaml          scenario catalogue: region, date, station, basin districts, commodities, supply, guidance questions, severity params
    organs.yaml             transport per organ (stdio command or http url), timeouts, concurrency
    conflict_rules.yaml     declarative rules (section 9)   + conflict_rules.schema.json (generated)
    confidence.yaml         weights and penalties (section 11)
    i18n/en.yaml  ur.yaml   claim text patterns per template id and language, unit aliases, conflict descriptions
  src/stitch_brain/
    core/                   pure, no I/O
      pointer.py            RFC 6901 pointer parse, escape, resolve
      evidence.py           EvidenceEntry, EvidenceStore (in-memory), brain-origin entries
      numbers.py            digit normalization, number extraction, units, matching, formatting
      derive.py             named derivations registry, severity mapping (section 8)
      claims.py             ClaimDraft, Slot, DerivationCall, claim ids
      templates/            extent.py forecast.py guidance.py allocation.py caveats.py (renderers: evidence -> ClaimDrafts)
      textfmt.py            restricted formatter for i18n patterns
      graph.py              Plan, Node, validation, topological levels
      plans.py              default plan builders per scenario, plan schema
      facts.py              fact registry used by rules (section 9)
      rules.py              rule AST, YAML loader, evaluator, reconcile policy
      critic.py             checks, repair loop
      confidence.py         formula
      briefing.py           assemble sections, statuses, caveats, ordering
    runtime/
      organs.py             OrganClient protocol, McpOrganClient, registry, health, circuit breaker
      recorded.py           RecordedOrgan, fixture sources (directory, trace)
      executor.py           asyncio executor, retries, deadlines, cancellation
      runner.py             one run: plan -> execute -> conflicts -> reconcile -> synth -> critic -> assemble
      llm_steps.py          phrase, translate, judge, plan-variation (all optional, all with fallbacks)
      store.py              RunStore (DuckDB), event log, trace
      clock.py              Clock protocol (real, virtual)
    api/
      app.py  models.py  sse.py  ratelimit.py  errors.py  voice.py  evals.py
    settings.py
    cli.py                  python -m stitch_brain.cli run --scenario demo-sindh-2022 --lang en
  tests/{unit,property,contract,integration}/   strategies.py holds shared Hypothesis strategies
data/demo/recorded/<organ>/<tool>/*.json         recorded ToolResult fixtures (section 3.3)
data/demo/llm/brain.jsonl                        recorded LLM responses for FakeLLM (section 12)
evals/brain/                                     seeded scenarios, verifier, metrics, traces
docs/brain-design.md                             architecture write-up (task 31)
```

The directory is `brain/` at the repo root, as in `structure.md`. The Python package is `stitch_brain`.

## 3. Organs: discovery, health, recorded stubs

### 3.1 OrganClient and registry (BRN-R1)
```python
class OrganClient(Protocol):
    organ: str
    served_by: Literal["real", "recorded"]
    async def list_tools(self) -> list[ToolInfo]: ...
    async def call_tool(self, tool: str, args: dict, *, timeout_s: float) -> CallOutcome: ...
    async def read_resource(self, uri: str, *, timeout_s: float) -> ResourceOutcome: ...
    def health(self) -> OrganHealth: ...
```
`McpOrganClient` wraps the MCP Python SDK `ClientSession` over `stdio_client` (local, Windows pipes allowed by `no_network`) or `streamablehttp_client` (Compose). One long-lived session per organ, owned by a supervisor task in the registry. `CallOutcome` is either a validated `ToolResult` or a `transport_error` (`TIMEOUT`, `CONNECTION`, `PROTOCOL`).

Startup: for each organ in `organs.yaml`, connect, `tools/list` (and `resources/list` for Ledger). A connection failure never blocks startup. The supervisor retries with backoff 1, 2, 4, 8, 16, 30 s (cap 30 s), with jitter from a seeded RNG injected for tests.

### 3.2 Compatibility and health states (BRN-R1.2, R1.3)
- **Compatibility.** Each discovered tool's `inputSchema` is normalized (sorted keys, descriptions removed) and compared with the schema exported by `stitch_common` (`TOOL_SCHEMAS` / `contracts.lock.json`). Missing tool, missing required property, or a type mismatch marks the organ `compat = incompatible`. An incompatible organ is never called and shows `status = unwell` with `reason = "incompatible"` (the requirement lists four health values plus `incompatible`; this design treats `incompatible` as a compatibility flag, see section 22).
- **Health.** `status` is one of `ready | degraded | unwell | disabled`.
  - `disabled`: named in `STITCH_ORGANS_DISABLED`.
  - `unwell`: not connected, `/healthz` failing, incompatible, or at least 3 of the last 5 calls failed.
  - `degraded`: connected, but 1 or 2 of the last 5 calls failed, or `/healthz` reports a degraded dependency.
  - `ready`: otherwise.
- `/healthz` is polled every 10 s for HTTP organs. For stdio organs the poll is an MCP `ping`.
- **Circuit breaker.** An `unwell` organ with a failure younger than 15 s fails fast (`UPSTREAM_UNAVAILABLE`, `retryable = true`, no wait). After 15 s one half-open call is allowed.

### 3.3 Recorded organs (stubs) and how they are labelled
Eyes, Oracle and Voice may not exist early, and the whole demo must run offline. A **recorded organ** is an `OrganClient` with `served_by = "recorded"` that replays committed `ToolResult` JSON.

- **Fixtures**: `data/demo/recorded/<organ>/<tool>/<name>.json`:
  ```json
  { "match": { "scenario": "demo-sindh-2022", "args": { "region_id": "pk-sindh" } },
    "authoring": "captured | hand_authored",
    "captured_from": { "organ_version": "0.1.0", "date": "2026-11-20" },
    "result": { "...a complete ToolResult..." } }
  ```
  `match.args` is a deep subset match against the call arguments; the most specific match wins; ties break by file name. No match returns `ToolResult(ok=false, error=NOT_FOUND "no recorded fixture for <organ>.<tool>")`. A recorded organ never invents a result.
- **Validation**: fixtures are validated at load against the `stitch_common` models for the tool (the contract hook covers them). A cross-fixture test checks that district ids in Eyes fixtures exist in the Ledger resource fixture.
- **Capture**: `scripts/record_organ_fixture.py --organ ledger --scenario demo-sindh-2022` runs the real organ in demo mode and writes the fixture (`authoring = captured`). Hand-authored fixtures must put a data source `{id: "fixture-hand-authored"}` in `provenance.data_sources`.
- **Selection is explicit.** `STITCH_RECORDED_ORGANS=eyes,oracle,voice` lists the organs served from fixtures. There is no silent automatic substitution of a failed real organ. (`STITCH_RECORDED_ORGANS=auto` exists for tests of the fallback path and is not a default anywhere.)
- **Labelling.** The decision "this organ is recorded" is made by the Brain from configuration, never from the fixture content. It shows in five places:
  1. `GET /organs`: `served_by: "recorded"`, `stub: true`.
  2. `organ_call` and `organ_result` events: `payload.served_by`.
  3. The stored evidence entry: `served_by = "recorded"`, plus the string `"RECORDED_FIXTURE: served from data/demo/recorded/..., not a live organ call"` appended to the stored `result.warnings` (the original hash is kept in the entry as `original_sha256`).
  4. The briefing: a caveat claim `caveat.recorded.<organ>` that cites that warning (`/warnings/<i>`), and every claim sourced from a recorded organ is flagged in the caveat text.
  5. `confidence` is not reduced for recorded organs (they replay real-shaped demo data), but the briefing `mode` is `demo`.
- Recorded organs are also the replay mechanism for traces (section 15): same class, different fixture source.

## 4. Evidence store and provenance

### 4.1 Entries
```python
class EvidenceEntry(BaseModel):
    call_run_id: str          # ToolResult.provenance.run_id (real) or uuid5(briefing_id, node_id, attempt) (recorded, brain-origin)
    briefing_id: str
    node_id: str              # plan node id, e.g. "eyes.compare"
    organ: str                # eyes|oracle|library|ledger|voice|brain
    tool: str                 # tool name, "resource:ledger.districts", or "derive.ledger_input"
    served_by: Literal["real", "recorded", "brain"]
    attempt: int
    started_at: datetime; ended_at: datetime; duration_ms: int
    result: dict              # the ToolResult as JSON (mode="json"). Pointers resolve against this document.
    original_sha256: str      # hash of the result before the Brain appended any warning
```
- `EvidenceStore.put(entry)` is called by the executor before the node is marked done. `get(call_run_id)`. `by_node(node_id)` returns the latest attempt. The store is per briefing, kept in memory, and written to DuckDB (section 15).
- A failed call is stored too. When there is no `ToolResult` (timeout, transport error), the Brain synthesizes `ToolResult(ok=false, error={TIMEOUT|UPSTREAM_UNAVAILABLE|INTERNAL}, provenance.organ/tool set, run_id = uuid5(...))` with `served_by` of the attempted client. Caveats about missing organs cite `/error/code` of that entry.
- A result that fails `stitch_common` validation is stored as a synthesized `ok=false` `INTERNAL` result ("contract violation: <first error>"), with the raw payload kept in the trace only.

### 4.2 EvidenceRef semantics
`EvidenceRef.run_id` is the **call-level** run id: the organ call's `provenance.run_id`. It is unique per call (uuid4 from the organ, uuid5 for recorded and brain-origin entries), so a ref is unambiguous even when the Ledger is called twice (reconciliation). `organ` and `tool` are redundant checks. `json_pointer` is an RFC 6901 pointer into the stored `ToolResult` document, for example `/data/forecast/3/discharge/p50`, `/provenance/mode`, `/warnings/0`, `/error/code`.

### 4.3 Resolver (`core/pointer.py`)
- `parse(ptr)`: `""` is the whole document. Otherwise it must start with `/`. Tokens are split on `/`, then `~1` is replaced by `/` and then `~0` by `~` (in that order).
- `resolve(doc, ptr)`: on an object, the token is a key. On an array, the token must match `0|[1-9][0-9]*` and be in range (`-` and leading zeros are errors). Missing key, bad index, or traversal through a scalar returns `Unresolved(reason)` and never raises.
- `escape(token)` is the inverse (`~` to `~0`, then `/` to `~1`). A helper `pointer_for(path: list[str|int])` builds pointers, so code never concatenates strings by hand.
- `store.resolve(ref) -> Resolved(value, entry_meta) | Unresolved(reason)` checks that `ref.run_id` exists, `ref.organ` and `ref.tool` match the entry, and the pointer resolves. A ref to a failed entry resolves only into `/error`, `/provenance`, `/warnings`.
- JSON round-trip (BRN-P8): the store is serializable with `json.dumps`/`loads` and resolves identically afterwards. Floats are kept as parsed. NaN and infinity are rejected at `put`.

### 4.4 Brain-origin entries
Some claim values do not come from one organ output. They are stored as entries with `organ = "brain"`, `served_by = "brain"`, and `result = {"ok": true, "data": {...}, "provenance": {...}, "warnings": []}`:

| Entry (`tool`) | Content | Used by |
|---|---|---|
| `derive.ledger_input` | the exact `districts` override and commodities sent to the Ledger, per-district severity mapping inputs and outputs, assumptions list, `lineage` (EvidenceRefs of every organ value used) | allocation caveat on assumptions, rule R3 (needs per person per day) |
| `run_meta` | requested and effective mode, `served_by` per organ, organ health at run start, fallback reasons | mode caveat |
| `static.disclaimer` | disclaimer text (en, ur), version | disclaimer claim |
| `critic` | final critic result | critic-failed caveat |

A brain-origin entry is derived data, so its `lineage` must itself resolve. A test walks lineage to organ entries (BRN-P1 extension).

## 5. Claims

### 5.1 Model
Internal model (richer than the contract `Claim`, which is the projection `{id, text, evidence, kind}`):
```python
class Slot(BaseModel):
    name: str
    value: Decimal | str | date          # Decimal parsed from the JSON number via Decimal(repr(x))
    unit: str | None                     # canonical unit key: "km2", "m3/s", "people", "litre", "usd", "pct", None
    decimals: int | None                 # display precision for numbers
    fmt: Literal["int", "dec", "pct", "date", "text"]
    refs: list[EvidenceRef]              # >= 1, every ref must resolve
    derivation: DerivationCall | None    # {fn: "sum", args: [...]} named pure function; None means "value is the resolved leaf"

class ClaimDraft(BaseModel):
    id: str                              # deterministic: f"{section}.{template_id}" + ".{subject}" (e.g. allocation.water.sukkur)
    section: Literal["extent","forecast","guidance","allocation","caveats"]
    kind: Literal["number","statement","recommendation"]
    template_id: str
    slots: dict[str, Slot]
    evidence: list[EvidenceRef]          # union of slot refs plus extra refs (e.g. citations); at least 1
    verbatim: bool                       # text is organ-authored (Library answer, Oracle narrative); not rendered from a pattern
    text: dict[Lang, str]                # rendered text per language (template output)
    final_text: str                      # after optional phrasing/translation checks
    text_source: Literal["template","phrased","translated","verbatim"]
    disputed_by: list[str]               # conflict ids
```
`ClaimDraft` is projected to the contract `Claim` at assembly: `text = final_text`, `evidence` de-duplicated in stable order.

### 5.2 Slot values and derivations
Slot values come from resolved evidence or from the named derivation registry in `core/derive.py`. Registry (pure, unit tested): `sum`, `count`, `max`, `min`, `argmax_item` (returns the winning pointer), `top_n_by`, `ratio`, `pct` (x100), `per_day(total, days)`, `diff`, `rel_diff`, `severity_map` (section 8). A slot with a derivation lists the refs of all its inputs. `recompute(slot, store)` re-resolves the refs and re-runs the derivation. The critic uses this to verify the slot value (check C2).

Formatting (`numbers.format_number(value, fmt, decimals, lang)`): `Decimal.quantize` with `ROUND_HALF_UP`. `int`: thousands separator `,`. `dec`: fixed decimals. `pct`: value x 100, `%` suffix. Urdu text uses ASCII digits (setting `ur_digits = ascii|extended`, default `ascii`); the extractor accepts both (section 6). Dates are ISO `YYYY-MM-DD` in both languages.

### 5.3 Claim templates per section
Renderers in `core/templates/` read evidence by `pointer_for` paths and return `ClaimDraft`s. Text patterns live in `config/i18n/{en,ur}.yaml`, rendered by `textfmt` (only `{name}` fields from the slot dict, no attribute or index access). Every template id has an `en` and a `ur` pattern (a test fails if one is missing). Patterns contain no digits (a test enforces it), so every digit in claim text comes from a slot.

| Claim id | Kind | Source (pointers in the stored ToolResult) | English pattern (abridged) |
|---|---|---|---|
| `extent.flood_area` | number | eyes.compare `/data/new_flood_km2`, `/data/total_water_km2`, `/data/permanent_water_km2`; eyes.segment `/data/source_scene/acquired` | "New flood water covers {new} km2 ({total} km2 total water, {perm} km2 permanent) in the scene acquired {date}." |
| `extent.top_districts` | number | eyes.compare `/data/by_district/i/{flooded_km2,flooded_fraction,name}`; top 3 by `flooded_km2`, ties by `district_id` | "Largest flooded areas: {name1} {km1} km2 ({pct1}% of the district), ..." |
| `extent.confidence` | number | eyes.segment `/data/confidence` | "Mean segmentation confidence over flood pixels: {conf}." |
| `extent.scene` | statement | eyes.segment `/data/source_scene/{sensor,scene_id,acquired}` | "Scene: {sensor}, {scene_id}, acquired {date}." |
| `forecast.peak` | number | oracle.forecast `/data/forecast/i/discharge/{p10,p50,p90}`, `/data/forecast/i/date`, `/data/station_id`; i is the argmax of p50 | "Modeled river discharge (GloFAS via Open-Meteo) near {station}: peak median {p50} m3/s on {date} (p10 {p10}, p90 {p90} m3/s)." |
| `forecast.exceedance` | number | oracle.forecast `/data/exceedance_prob/i/p_exceed`, `/data/danger_threshold_m3s`; i is the argmax | "Modeled probability of exceeding {thr} m3/s peaks at {pct}% on {date}." Omitted when the threshold is null. |
| `forecast.calibration` | statement | oracle.forecast `/data/calibration/{nominal_coverage,n_calibration}` | "Intervals are {cov}% split-conformal bands from {n} calibration points." |
| `forecast.drivers` | statement, verbatim | oracle.explain `/data/narrative` (optional node) | the Oracle narrative, unchanged |
| `guidance.<qid>.<i>` | statement, verbatim | library `/data/claims/i/text` plus each `/data/citations/j` for `j` in `citation_idx` | the Library claim text, unchanged |
| `guidance.<qid>.refusal` | statement | library `/data/refusal/reason`, `/data/refusal/closest_hits/*` | "The guidance library declined to answer \"{query}\": {reason_text}. No guidance is given from memory." |
| `allocation.summary` | number | ledger `/data/status`, `/data/cost_benefit/{people_covered,cost_per_person_covered}`, `/data/total_cost` | "The plan covers {people} people at {cpp} per person ({cost} total); solver status: {status}." Null cost per person renders "not defined (no people covered)". |
| `allocation.<commodity>.<district>` | recommendation | ledger `/data/allocation/i/quantity`; unit and names from `derive.ledger_input`; top 5 districts per commodity by quantity, ties by `district_id` | "Send {qty} {unit} of {commodity} to {district}." |
| `allocation.<commodity>.others` | recommendation | derivation `sum` over the remaining rows | "Send {qty} {unit} of {commodity} across {n} other districts." |
| `allocation.unreached` | number | ledger `/data/coverage/i/{unreached_people,access_mode}`; derivations `sum`, `count` | "{people} people in {n} districts cannot be reached by road, air or boat with the given inputs." Omitted when 0. |
| `allocation.equity` | statement | ledger `/data/equity/{floor_requested,floor_applied,max_feasible_floor}`; sensitivity `/data/equity_cost` | "Equity floor requested {req}, applied {app} (highest feasible {max}); coverage given up for equity: {cost}." |
| `allocation.shadow.<commodity>` | number | sensitivity `/data/shadow_prices/i/{value,unit,binding}` for `supply:<commodity>` when binding | "One more unit of {commodity} would raise weighted coverage by {v} {unit}." |
| `caveat.disclaimer` | statement | `static.disclaimer` | "Stitch is decision support, not an operational authority. Verify with local responders." |
| `caveat.mode` | statement | each call `/provenance/mode`; `run_meta` | "Demo mode: figures come from committed demo data, not live feeds." or the live variant |
| `caveat.eyes_unvalidated` | statement | eyes.segment `/data/validation/{validated_for_region,eval_dataset,note}` | "Demo scene: Sindh, Aug 2022. The flood-mapping model was validated on {eval_dataset}, not on this region. Treat the extent as unvalidated." Emitted when `validated_for_region` is false. |
| `caveat.oracle_modeled` | statement | oracle.forecast `/data/target_kind`, `/data/target_label` | "River figures are model output ({label}), not instrument readings." |
| `caveat.recorded.<organ>` | statement | `/warnings/<i>` of the recorded entry | "{Organ} output is a recorded fixture, not a live organ call." |
| `caveat.missing.<node>` | statement | `/error/{code,message}` of the failed entry | "{Organ} did not answer ({code}). The {section} section is {status}." |
| `caveat.assumptions` | statement | `derive.ledger_input` `/data/assumptions` | the assumption list from section 8, always shown with the allocation |
| `caveat.conflict.<cid>` | statement | the conflict's evidence | "Unresolved disagreement: {description}. Neither side is treated as settled." or "Reconciled: ..." |
| `caveat.critic_failed` | statement | `critic` entry | "Automated checks found {n} unresolved issues. Treat this briefing with care." Added by the assembler when `critic.passed` is false. |

Sections are ordered `extent`, `forecast`, `guidance`, `allocation`, `caveats`. Claims inside a section follow the table order, then by id.

### 5.4 Honesty labels
Labels are carried in claim text, because contract v0.3 has no `labels` field (a structured field is proposed in section 22).
- **Modeled.** Every claim whose evidence includes an `oracle` ref begins with, or contains, "Modeled river discharge (GloFAS via Open-Meteo)" or "Modeled". The Urdu pattern carries the Urdu word for modeled plus "GloFAS". The words gauge, observed, measured, observation (and Urdu equivalents in `i18n/ur.yaml: forbidden_oracle_terms`) are forbidden in any claim citing Oracle evidence. The critic enforces both (check C7). The label comes from `target_kind = modeled_glofas` in the evidence: if the Oracle ever returned another `target_kind`, the renderer would refuse to render and the claim would be dropped.
- **Unvalidated.** If any Eyes result has `validation.validated_for_region = false`, the briefing must contain `caveat.eyes_unvalidated` (section check S1).
- **Recorded and demo.** A recorded organ produces `caveat.recorded.<organ>` (S2). `caveat.mode` is always present.
- **Refusal.** A Library refusal renders as `guidance.<qid>.refusal` with the Library `reason` mapped to fixed text: `INSUFFICIENT_EVIDENCE` "no sufficiently supported passage was found", `OUT_OF_SCOPE` "the question is outside flood-response guidance", `CONFLICTING_EVIDENCE` "sources disagree on this quantity". Closest hits are evidence refs, not paraphrased into guidance. No code path fills a refusal from LLM memory.

### 5.5 Guidance and citations
For an `answered` Library result, each `claims[i]` becomes one guidance claim (`kind = statement`, `verbatim = true`). Its evidence is `/data/claims/i/text` plus `/data/citations/j` for each `j` in `citation_idx`, all in the Library entry. The drill-down resolves `/data/citations/j` to `doc_id`, `page`, `span`, `quote`. Check C4 requires each non-refusal guidance claim to cite at least one `/data/citations/j` whose value has a non-empty `quote` and `page >= 1`. A claim whose `citation_idx` is empty or out of range is not rendered and is listed in `critic.removed_claims`. The Library `answer` string is not used separately, so no sentence appears without a citation mapping. For language differences see section 13.

### 5.6 Disputed marker
When a conflict is `flagged` or `escalated`, each claim id in the rule's `affects` list gets `disputed_by = [conflict ids]`. The renderer appends a fixed pattern (`i18n: disputed_suffix`, for example " (disputed, see conflict C1)") after any phrasing, so the LLM cannot remove it. A `reconciled` conflict adds no marker.

## 6. Numbers: extraction and checking (`core/numbers.py`)

### 6.1 Normalization
1. Map Arabic-Indic digits U+0660..0669 and Extended Arabic-Indic digits U+06F0..06F9 to ASCII. Map U+066B (decimal separator) to `.`, U+066C (thousands separator) to `,`, U+066A (percent) to `%`.
2. Mask non-numeric digit carriers before extraction: ISO dates (kept as date tokens, compared as strings), unit tokens (`m3/s`, `m³/s`, `km2`, `km²`, `m²` and the Urdu aliases from `i18n`), quantile labels `p10|p50|p90`, a configured term list (`Sentinel-1`, `Sentinel-2`, `Sen1Floods11`, `ERA5`, `GloFAS`), and identifiers matching `[A-Za-z][A-Za-z0-9_-]*\d[\w-]*` (scene and document ids). Masked spans are kept so units can still be checked.
3. Remove thousands separators only where the pattern is `\d{1,3}(,\d{3})+`.

### 6.2 Extraction
Regex over the normalized text: `(?<![\w.])[-+]?\d+(?:\.\d+)?` with an optional trailing `%`. Each token becomes `NumToken(value: Decimal, decimals: int, percent: bool, span, unit: str | None)`. `unit` is the canonical unit of the alias that immediately follows the number (optional single space). Number words are also tokens: English `one`..`twenty`, `hundred`, `thousand`, `million`, `lakh`, `crore`; Urdu `ایک`..`بیس`, `سو`, `ہزار`, `لاکھ`, `کروڑ`. An LLM therefore cannot hide a number in words. A scale word after a digit (`10 lakh`) gives a second token that fails the check unless a slot holds that value.

### 6.3 Allowed set and matching
For a claim, `allowed(claim, store)` is the union of:
1. Each slot's resolved value as `(value, decimals)`. For `pct` slots also `value x 100`.
2. Numbers extracted from every string leaf, and numeric leaves, of each referenced evidence value (this covers verbatim Library and Oracle text).
3. Dates from date slots (string comparison).

Template patterns contribute nothing because they contain no digits.

Token `n` matches allowed value `a` when `a` quantized to `n`'s decimals (`ROUND_HALF_UP` or `ROUND_HALF_EVEN`) equals `n`. A token with more decimals than the slot's `decimals` must equal the unrounded value exactly, so a rewrite cannot claim more precision. Percent tokens match `a x 100` for pct slots. The check passes when every token matches an allowed value **and** every slot with `fmt` in `int|dec|pct` appears at least once in the text (a rewrite cannot silently drop a number).

### 6.4 Units
The unit table in `i18n` maps canonical keys to accepted aliases per language (`km2`: `km2`, `km²`, `square kilometres`, and the Urdu phrase; `m3/s`: `m3/s`, `m³/s`, `cubic metres per second`, and so on). For each token matched to a slot with unit `u`, the unit found after the token must have canonical key `u`. A slot with a unit and no adjacent alias fails. A token followed by a unit different from its slot's unit fails (swapped `km2` and `m3/s`). A count slot (no unit) must not be followed by a unit alias.

### 6.5 Language match
`lang = en`: at least 90% of letters outside masked spans and verbatim quotes are Latin. `lang = ur`: at least 60% of such letters are Arabic-script (U+0600..06FF, U+0750..077F, U+FB50..FDFF, U+FE70..FEFF). Claims marked `verbatim_foreign` (organ text that could not be translated, section 13) are exempt and covered by a caveat.

## 7. Plan and executor

### 7.1 Default task graph (scenario `demo-sindh-2022`)
```
 eyes.segment ──────────────────────────────┐
 eyes.compare ──┐                           │
 oracle.forecast ─┬─ oracle.explain (opt) ──┤
 ledger.districts ┤                         │
                  ▼                         │
        derive.ledger_input ──► ledger.optimize ──► ledger.sensitivity (opt)
 library.water ─────────────────────────────┤        │
 library.food ──────────────────────────────┤        │
 library.shelter ───────────────────────────┤        ▼
                                            └──► conflicts ──(R2 fired)──► ledger.rerun (dynamic, at most once)
                                                    ▼
                                         synth ─► phrase/translate ─► critic ─► assemble
```

| Node | Kind | Call | Depends on (H hard, S soft) | Timeout | Optional |
|---|---|---|---|---|---|
| `eyes.segment` | organ | `segment_flood {region_id, date}` | none | 30 s | no |
| `eyes.compare` | organ | `compare_with_permanent_water {region_id, date}` | none | 30 s | no |
| `oracle.forecast` | organ | `forecast_river {station_id, horizon_days: 7, as_of}` | none | 8 s | no |
| `oracle.explain` | organ | `explain_forecast {run_id}` | H `oracle.forecast` | 8 s | yes |
| `library.<qid>` (one per guidance question) | organ | `answer_with_citations {query, lang}` | none | 20 s | no |
| `ledger.districts` | resource | read `ledger://scenario/{id}/districts` | none | 5 s | no |
| `derive.ledger_input` | derive | `build_ledger_input` (section 8) | S `eyes.compare`, S `oracle.forecast`, S `ledger.districts` | 2 s | no |
| `ledger.optimize` | organ | `optimize_allocation {scenario_id, districts?, commodities, supply, budget?, equity_floor?, integer}` | S `derive.ledger_input` | 15 s | no |
| `ledger.sensitivity` | organ | `sensitivity_report {run_id}` | H `ledger.optimize` | 15 s | yes |
| `conflicts` | analysis | evaluate rules (section 9) | S all organ nodes | 2 s | no |
| `ledger.rerun` | organ (dynamic) | `optimize_allocation` with Eyes-only input | added by `conflicts` | 15 s | yes |
| `synth` | synthesis | render claims | S all above | 5 s | no |
| `phrase`, `translate` | llm | section 12 | H `synth` | 20 s | yes |
| `critic` | analysis | section 10 | H `synth` (S `phrase`, `translate`) | 20 s | no |
| `assemble` | analysis | build Briefing, confidence, caveats | H `critic` | 2 s | no |

Hard dependency: the node is skipped (`SKIPPED`, reason `DEP_FAILED`) if the dependency did not end `ok`. Soft dependency: the node starts once the dependency reached any terminal state, and receives the outcome (possibly a failure) as input.

Ledger inputs when upstream organs are missing:
- `derive.ledger_input` with Eyes `compare` available: full mapping (section 8).
- Eyes `compare` unavailable: no override is built. `ledger.optimize` is called with only `scenario_id`, so the Ledger uses its dataset defaults (`default_severity`, full population). The allocation section is `partial` and `caveat.assumptions` says the plan is not informed by satellite data.
- Oracle unavailable: the Oracle risk term is 0, and the same caveat style applies to the forecast term.
- `ledger.districts` unavailable but the Ledger is up: `derive.ledger_input` cannot build the override (it needs population and road access), so the Ledger runs on dataset defaults as above.
- Ledger unavailable: `allocation` is `unavailable`.

Which Library questions run, the commodities, supply and budget are scenario configuration (`config/scenarios.yaml`), not LLM output. The scenario also names the Oracle station, the districts exposed to that station's river (`basin_districts`), the Eyes scene date, and `period_days` (the length of the relief period a Ledger `per_person_need` covers).

### 7.2 Plan model and validation (BRN-R2, P5)
```python
class Node(BaseModel):
    id: str                               # unique, [a-z0-9_.]+
    kind: Literal["organ", "resource", "derive", "analysis", "synthesis", "llm"]
    organ: str | None; tool: str | None   # for organ and resource nodes
    builder: str                          # name of a registered argument builder, never an expression
    deps: list[Dep]                       # Dep = {id, need: "hard" | "soft"}
    optional: bool; timeout_s: float; max_attempts: int
class Plan(BaseModel):
    plan_id: str; scenario: str; revision: int; planner: Literal["default", "llm"]; nodes: list[Node]
```
`validate_plan` rejects: duplicate ids, a dependency on an unknown id, self-dependency, a cycle (Kahn), more than 24 nodes, an unregistered `builder`, an `organ/tool` pair not discovered (or not recorded) in the registry, and depth over 8. `topological_levels(plan)` returns the levels. Argument builders are pure functions `(scenario_config, outcomes) -> dict` registered by name, so a plan is data and cannot carry code.

`Planner.plan(request)`: builds the default plan with `plans.default_plan(scenario)`. If `STITCH_BRAIN_PLANNER=llm` and the provider is not `fake`, the LLM may propose a variation (section 12), parsed as JSON against the `Plan` schema, restricted to adding or dropping *optional* nodes from a whitelist (`oracle.explain`, `ledger.sensitivity`, extra `library.*` questions from `scenarios.yaml`). Anything invalid, or any exception, yields the default plan (BRN-R2.3). With `fake` the default plan is always used (BRN-R2.4).

The `plan` event is emitted before execution. Reconciliation adds a node, so a second `plan` event (`revision = 2`, `added: ["ledger.rerun"]`) is emitted when it is added. This extends BRN-R2.2, which asks for the plan before execution; the first `plan` event still precedes all calls.

### 7.3 Executor semantics (`runtime/executor.py`)
Event loop: `asyncio`, one `TaskGroup` per run. Time comes from an injected `Clock` (real or virtual) so tests control time.

- **Scheduling.** A node becomes *ready* when all hard deps ended `ok` and all soft deps reached a terminal state. Ready nodes start immediately (maximum parallelism). Terminal states: `ok | failed | skipped | timed_out | cancelled`. Each node ends in exactly one of them (BRN-P10).
- **Concurrency limits.** At most 6 nodes in flight per run, at most 2 in flight per organ (the Library and Ledger are CPU-bound on a 2 vCPU host), and at most 4 concurrent runs per process (new runs get `429 BUSY`).
- **Per-call timeout.** `asyncio.timeout(node.timeout_s)` around each attempt. On timeout the attempt is `TIMEOUT`, `retryable = true`.
- **Retries.** Retry only when `error.retryable` is true or the failure is a transport error. At most 3 attempts per node (2 retries), backoff 0.25 s, 0.5 s with a deterministic jitter derived from `hash(node_id, attempt)`. A `retryable = false` error is never retried. Each attempt emits its own `organ_call` event (`payload.attempt`).
- **Deadlines.** `organ_phase_deadline_s = 45` and `run_deadline_s = 60` (live mode 70 and 90). At the organ-phase deadline all in-flight organ nodes are cancelled and marked `timed_out` (`DEADLINE`), unstarted dependents are `skipped`, and synthesis proceeds with what exists. `synth`, `phrase`, `translate`, `critic` and `assemble` run in the remaining budget. If the run deadline passes during phrasing or translation, those steps are skipped and the template text is used. The critic and assembler always complete (they do no I/O except the optional judge, which is bounded by its own timeout and falls back).
- **Cancellation.** `DELETE /briefings/{id}` sets a cancel flag and cancels the run's task group. In-flight MCP calls are cancelled (the SDK sends `notifications/cancelled` where supported; if not, the server finishes and the result is discarded). The run ends with a fatal `error` event `CANCELLED`, status `cancelled`, no briefing. Client disconnect from the SSE stream does not cancel the run.
- **Partial results.** Each node produces `NodeOutcome(status, entry_id | None, error | None, attempts)`. The evidence entry is stored before the status is set (BRN-R3.5). A failed node never raises into the group: the node wrapper catches all exceptions except `CancelledError` and converts them to `failed (INTERNAL)`. `synth` reads outcomes and marks sections (7.4).
- **Dynamic nodes.** Only `conflicts` may add nodes (`ledger.rerun`), subject to the run's reconcile budget (section 9.4). The graph is re-validated after the addition.

### 7.4 Section status
| Section | Required nodes | `unavailable` | `partial` | `ok` |
|---|---|---|---|---|
| extent | `eyes.segment`, `eyes.compare` | neither ended ok | one failed or skipped | both ok |
| forecast | `oracle.forecast` | it did not end ok | it is ok but `exceedance` could not render (no threshold) | ok |
| guidance | every `library.*` | none ended ok | any call failed, or any refusal | all answered |
| allocation | `ledger.optimize` | it did not end ok, or `status = infeasible` | ok but Eyes `compare` or Oracle did not end ok (plan not informed by them), or `status = feasible` with a gap | otherwise |
| caveats | none | never | never | always `ok` |

A refusal is an honest outcome and produces a claim, but it makes guidance `partial` because some questions went unanswered. The critic can lower a status when it removes claims (all removed: `unavailable`; some: `partial`).

## 8. Severity mapping (`core/derive.py::build_ledger_input`)

Eyes gives per-district `flooded_fraction`. Oracle gives exceedance probabilities per day for one station. The Ledger needs per district `population_affected`, `severity`, `road_access`. The mapping is an explicit pure function. **All parameters are assumptions** (set in `scenarios.yaml`, listed in `caveat.assumptions`, to be confirmed by the owner).

Parameters: `f_noise = 0.01` (flooded fraction below this is segmentation noise), `f_sat = 0.30` (a district with 30% of its area flooded counts as fully affected), `lambda = 0.25` (maximum severity uplift from forecast risk), `pi = 0.10` (share of a dry, exposed district's population treated as at risk), `kappa = 0.5` (road access lost in a fully affected district).

For district `d` with base population `pop_d`, road access `ra_d`, air/boat fraction `alt_d` from `ledger://scenario/{id}/districts`, and Eyes `ff_d` (0 if the district is missing from Eyes, with a note counting such districts):

```
a_d   = 0                          if ff_d < f_noise
        min(1, ff_d / f_sat)       otherwise                       # observed affected share
O     = max over forecast days of p_exceed                         # 0 if Oracle is unavailable or has no threshold
O_eff = O                          in mode "full"
        0                          in mode "eyes_only" (reconciliation re-run)
b_d   = 1 if d in basin_districts else 0
population_affected_d = round(pop_d * max(a_d, pi * O_eff * b_d))
severity_d            = min(1, a_d + lambda * O_eff * b_d * (1 - a_d))        (rounded to 4 decimals)
road_access_d         = ra_d * (1 - kappa * a_d)                              (rounded to 4 decimals)
alt_delivery_fraction_d = alt_d
```
The road adjustment is a proxy: Eyes returns no road data, so flooded area stands in for flooded roads. If a better signal becomes available (flooded road km per district), replace `kappa * a_d`. A district whose adjusted road access drops under the Ledger's `min_road_access` becomes road-denied inside the Ledger, which then uses its air/boat capacity or flags it unreachable.

Worked example (`O = 0.8`, both districts in the basin):

| | pop | `ra` | `alt` | `ff` | `a` | pop affected | severity | road access |
|---|---|---|---|---|---|---|---|---|
| D (flooded) | 1,200,000 | 0.70 | 0.05 | 0.18 | 0.18/0.30 = 0.60 | 1,200,000 x max(0.60, 0.10x0.8 = 0.08) = 720,000 | 0.60 + 0.25x0.8x1x0.40 = 0.68 | 0.70 x (1 - 0.5x0.60) = 0.49 |
| E (dry) | 500,000 | 0.90 | 0.00 | 0.004 | 0 (below `f_noise`) | 500,000 x max(0, 0.08) = 40,000 | 0 + 0.25x0.8x1x1 = 0.20 | 0.90 |

In `eyes_only` mode E gets population affected 0, so the Ledger sends it nothing. In `full` mode E gets a small forecast-driven allocation, and rule R2 (section 9) flags it.

Properties (BRN-P17): all outputs within bounds; `population_affected_d <= pop_d`; `severity` and `population_affected` are non-decreasing in `ff_d` and in `O` for fixed other inputs; `road_access_d <= ra_d`; `ff_d = 0` and `O = 0` give `severity = 0` and `population_affected = 0`; the result is invariant to district order.

The `derive.ledger_input` entry stores the inputs, outputs, parameters, assumption strings and `lineage` refs. Commodities come from the scenario: `{id, name, unit, unit_cost, per_person_need_per_day}`; the Brain sends `per_person_need = per_person_need_per_day x period_days`.

## 9. Conflict detection (`core/facts.py`, `core/rules.py`, `config/conflict_rules.yaml`)

### 9.1 Facts and rules
Rules are data. They reference **facts**, which are small pure functions in `core/facts.py` that read the evidence store and return `Fact(value, refs)` (scalar facts) or `dict[key, Fact]` (keyed facts). Facts are the only code a rule can invoke, and they are whitelisted in a registry:

| Fact | Kind | Meaning |
|---|---|---|
| `oracle.max_exceedance` | scalar | max `p_exceed` over the forecast; ref = the argmax item |
| `eyes.basin_flooded_fraction` | scalar | sum of `flooded_km2` over `basin_districts` divided by the sum of district areas, where area = `flooded_km2 / flooded_fraction` for districts with a positive fraction |
| `eyes.district_flooded_fraction` | by `district_id` | `flooded_fraction` |
| `ledger.allocated_units_by_district` | by `district_id` | sum of `quantity` over commodities in the final Ledger run (rows with quantity above 0 only) |
| `library.guidance_per_person_per_day` | by `commodity_id` | the single quantity extracted by code from answered Library claim text using the unit aliases in `scenarios.yaml` (`guidance_questions[].quantity`). Ambiguous (more than one distinct value) or absent: the key is omitted and the reason is traced |
| `ledger.need_per_person_per_day` | by `commodity_id` | `per_person_need_per_day` from `derive.ledger_input` |

A fact whose inputs are missing is `Unavailable(reason)`. A rule with an unavailable fact is `skipped` with the reason in the trace (and shown in the plan summary), not an error.

### 9.2 Rule schema (YAML, validated by Pydantic; a JSON Schema is generated)
```yaml
version: 1
params:                      # all thresholds in one place
  oracle_low_p: 0.20
  eyes_flooded_frac: 0.10
  eyes_dry_frac: 0.01        # must equal severity f_noise (test)
  need_rel_tol: 0.10
rules:
  - id: R1_oracle_low_eyes_flooded
    severity: high
    organs: [oracle, eyes]
    facts: { p: oracle.max_exceedance, fl: eyes.basin_flooded_fraction }
    when: { all: [ { lt: [p, {param: oracle_low_p}] }, { gte: [fl, {param: eyes_flooded_frac}] } ] }
    affects: [forecast.peak, forecast.exceedance, extent.flood_area]
    describe: r1                           # key into i18n conflict descriptions (en and ur)
    reconcile: null
  - id: R2_ledger_to_dry_district
    severity: medium
    organs: [ledger, eyes]
    foreach: district_id                   # join keyed facts on this key; keys missing from any fact are skipped
    facts: { alloc: ledger.allocated_units_by_district, ff: eyes.district_flooded_fraction }
    when: { all: [ { gt: [alloc, 0] }, { lt: [ff, {param: eyes_dry_frac}] } ] }
    affects: [allocation.summary]
    describe: r2
    reconcile: { action: rerun_ledger, severity_source: eyes_only, max_times: 1 }
  - id: R3_library_vs_ledger_need
    severity: medium
    organs: [library, ledger]
    foreach: commodity_id
    facts: { lib: library.guidance_per_person_per_day, led: ledger.need_per_person_per_day }
    when: { rel_diff_gt: [lib, led, {param: need_rel_tol}] }     # |lib - led| / max(lib, led) > tol
    affects: [allocation.summary]
    describe: r3
    reconcile: null
```
Grammar: `when := all[when] | any[when] | not when | cmp`; `cmp := {lt|lte|gt|gte|eq|ne: [operand, operand]} | {rel_diff_gt: [operand, operand, operand]}`; `operand := fact_name | {param: name} | {const: number}`. The evaluator is a recursive function over the parsed Pydantic AST. There is no `eval`, `exec`, `getattr` on user strings, or expression parsing; a test scans `core/rules.py` and `core/facts.py` for those names. Loading fails (`RuleConfigError`) on an unknown fact, an undefined param, an operand type mismatch, or `max_times > 1`.

Result per firing: `RuleOutcome(rule_id, fired, subjects: list[key], values, refs)`. One `Conflict` per fired rule (all subject keys listed in the description, one evidence ref per side per subject, de-duplicated). Conflict ids are `C1`, `C2`, ... in rule order, deterministic.

### 9.3 Thresholds (judgement values, not measured)
- `oracle_low_p = 0.20`: "low" means the modeled chance of exceeding the danger threshold stays below one in five on every lead day.
- `eyes_flooded_frac = 0.10`: at least a tenth of the basin districts' area is mapped as new flood water, well above the 0.01 noise floor.
- `eyes_dry_frac = 0.01`: below the segmentation noise floor the district counts as unflooded.
- `need_rel_tol = 0.10`: guidance quantities are usually quoted to two significant figures, so 10% absorbs rounding but flags a factor-of-two disagreement.

These have no empirical calibration. They are set so seeded scenarios separate cleanly (recall 1.0, no false positives on controls), and the eval reports both. R1 is a disagreement between a forecast and an observation that may legitimately differ (a receding flood, local rain). The text says "cannot both be the full picture", and the Brain does not decide which is right.

### 9.4 Reconciliation (R2 only) and why it cannot loop
1. After all organ nodes finish, `conflicts` evaluates all rules (pass 1).
2. If a fired rule has `reconcile` and the run's `reconcile_budget` is 1, the Brain consumes the budget, emits the `conflict` event with `resolution = "flagged"` and `status = "reconciling"` in the payload, adds `ledger.rerun` with arguments from `build_ledger_input(mode="eyes_only")`, and runs it.
3. The Ledger result is stored as a new evidence entry. The alias `ledger.final` now points to it, and the original stays in the store.
4. Rules are re-evaluated once (pass 2) with `reconcile_enabled = false`. If R2 no longer fires: resolution `reconciled`, evidence = both Ledger runs and the Eyes ref. If it still fires, or the rerun failed: resolution `escalated` (needs a human), the original allocation stays the final one when the rerun failed, and the disputed marker applies.
5. Rules without `reconcile` (R1, R3) end as `flagged`.

The budget is per run, not per rule: at most one extra Ledger call in any run (BRN-P20). Pass 2 cannot schedule nodes. Reconciliation never changes Library, Oracle or Eyes results.

### 9.5 Seeded scenarios for evals and BRN-P6
`evals/brain/scenarios.py` builds mutations of the base fixture set, seeded:
- `oracle_low`: set every `p_exceed` below 0.1 while Eyes stays flooded (expects R1).
- `dry_district`: set one basin district's `flooded_fraction` to 0 while Oracle risk stays high (expects R2, and `reconciled` on rerun).
- `need_mismatch`: change the Library fixture quantity by a factor of 0.5 to 2 (expects R3).
- Combinations of the three, and **negative controls**: Oracle high and Eyes flooded; all districts flooded; Library quantity within tolerance (expect no conflict).

The default eval set is 30 scenarios: 9 per rule family (single), 3 combined, 9 controls. Property BRN-P6 uses the same mutators with Hypothesis-drawn magnitudes within the firing region.

## 10. Critic (`core/critic.py`)

The critic is a pure function `critic(briefing_draft, store, judge_cache) -> (briefing_draft, CriticReport)`. The only I/O is the optional judge, which is injected and cached.

### 10.1 Checks
Claim checks (run for every claim):

| ID | Check | Failure means |
|---|---|---|
| C1 | provenance: at least one `EvidenceRef`, every ref resolves (`store.resolve`) | claim has no resolvable evidence |
| C2 | numeric consistency: slots re-resolved and re-derived equal the stored slot values; numbers extracted from `final_text` all match the allowed set; every numeric slot appears in the text (section 6.3) | wrong, new, or dropped number |
| C3 | units: each number carries the unit of its slot (section 6.4) | unit missing or swapped |
| C4 | citation presence for non-refusal guidance claims (section 5.5) | uncited guidance |
| C5 | language match (section 6.5) | wrong language |
| C6 | statement entailment, only for claims with `text_source` of `phrased` or `translated`: the judge says whether `final_text` is entailed by the resolved evidence strings | rewrite adds or changes meaning |
| C7 | labels: Oracle-citing claims contain the modeled label and no forbidden terms; disputed claims carry the marker | missing label |

Section and briefing checks (verification only; the critic cannot add claims):

| ID | Check |
|---|---|
| S1 | if any Eyes evidence has `validated_for_region = false`, `caveat.eyes_unvalidated` exists |
| S2 | every recorded organ used has `caveat.recorded.<organ>` |
| S3 | every conflict has a `caveat.conflict.<id>` claim |
| S4 | every failed organ node has a `caveat.missing.<node>` claim and the dependent section status matches section 7.4 |
| S5 | every Library refusal appears as a `guidance.<qid>.refusal` claim |
| S6 | `caveat.disclaimer` and `caveat.mode` exist |
| S7 | claim ids are unique |

Section checks are normally satisfied by construction (the assembler adds caveats from facts before the critic runs). They exist so a regression, or a removal by the critic itself, is caught.

### 10.2 Repair loop
`N = 3` passes. Pass `k`: run all checks; if there are no failures, stop with `passed = true`. Otherwise apply repairs:
1. A claim failing C2, C3, C5, C6 or C7 whose `text_source` is `phrased` or `translated` is **reverted** to the template text (`text_source = "template"`).
2. A claim that still fails (or fails C1, C4, or any check while already template or verbatim) is **removed**. The id is added to `removed_claims` and a note `"<id>: <check> <detail>"` is added to `notes`.
3. After removals, section statuses are recomputed.

With deterministic repairs the loop needs at most two repair passes and a third to verify, hence `N = 3`. After pass `N` the result is `passed = (no failures remain)`. Section-check failures cannot be repaired, so they leave `passed = false`. Judge verdicts are cached per `(sha256(final_text), sha256(evidence strings))` so repeated passes cannot flip.

### 10.3 Properties
- **No additions.** Claim ids after are a subset of the ids before. Each claim's evidence list after is a subset of the one before. A repair only replaces `final_text` with `text[lang]` (template rendering) or removes a claim.
- **Idempotent (BRN-P7).** The critic merges the existing `removed_claims` and `notes` (de-duplicated, stable order) with new ones. Running it on its own output changes nothing: sections, claims, texts, `passed`, `removed_claims` and `notes` are equal.
- **Failure caveat (BRN-R6.3).** The assembler (not the critic) runs after the critic. If `passed = false`, it adds `caveat.critic_failed` to the caveats section. The briefing is never emitted with `passed = false` without it. The critic is not re-run on that claim; its own check (C1) is satisfied by the `critic` entry in the store.

### 10.4 What "removed claims" means
`critic.removed_claims` lists ids of claims that were produced by the renderers and deleted because they could not be made to pass. They are not shown as claims. The notes say why, and the confidence formula penalizes removals (section 11).

## 11. Confidence (`core/confidence.py`, `config/confidence.yaml`)

`confidence` is a heuristic "strength of the evidence" score in [0, 1]. It is not a probability, and the UI must not present it as one.

Per-organ confidence `c_o` in [0, 1] (0 when the organ produced no ok result):

| Organ | `c_o` | Notes |
|---|---|---|
| eyes | `confidence` from `segment_flood`, times `0.7` when `validated_for_region = false` | the validity factor is a judgement value |
| oracle | `clamp(1 - mean_t((p90 - p10) / max(p50, 1)), 0, 1)` over the forecast days | relative interval width; wider interval, lower value |
| library | answered questions / total questions | a refusal counts as no coverage, not as an error |
| ledger | `1.0` if `optimal`, `1 - clamp(optimality_gap, 0, 1)` if `feasible`, `0` if `infeasible` | |

Formula, with weights `w = {eyes: 0.30, oracle: 0.25, library: 0.20, ledger: 0.25}` (sum 1):
```
C0 = sum_o  w_o * c_o
C1 = C0 * product over conflicts (1 - p_i)          p_i = 0.15 if flagged or escalated, 0.05 if reconciled
C2 = C1 * (0.6 if critic.passed is false else 1)
C3 = C2 * (1 - 0.05 * min(len(removed_claims), 4))
confidence = round(C3, 2)
```
Missing organs contribute 0 and the weights are not renormalized, so a missing organ can only lower the score.

Worked examples:
- A, all four organs, no conflict, critic passed: Eyes `0.82 x 0.7 = 0.574` gives `0.1722`; Oracle `c = 0.65` gives `0.1625`; Library 3 of 3 gives `0.20`; Ledger optimal gives `0.25`. `C0 = 0.7847`, `confidence = 0.78`.
- B, as A with Oracle down: `0.1722 + 0 + 0.20 + 0.25 = 0.6222`, `confidence = 0.62`.
- C, as A with R2 reconciled and R3 flagged: `0.7847 x 0.95 x 0.85 = 0.6336`, `confidence = 0.63`.

Properties (BRN-P16): bounded in [0, 1]; non-decreasing in each `c_o`; setting any `c_o` to 0 never raises it; adding a conflict, a removed claim, or a critic failure never raises it; weights sum to 1 (load check).

## 12. LLM usage (`runtime/llm_steps.py`)

The Brain uses `stitch_common.llm.LLMClient` (Claude, OpenAI, `FakeLLM`). The LLM has no tools, no network access to organs, and cannot add claims. Exactly four steps use it; each has a deterministic fallback.

| Step | `purpose` | Input | Output | Used when | Fallback |
|---|---|---|---|---|---|
| Plan variation (optional) | `brain.plan` | scenario, whitelist of optional nodes | JSON `Plan` subset | `STITCH_BRAIN_PLANNER=llm` and provider not `fake` | default plan |
| Phrase prose | `brain.phrase` | per section: the template texts `{claim_id: text}` as JSON data | JSON `{claim_id: text}` | `STITCH_BRAIN_PHRASE=on` (default on with a real provider; with `fake` only if a recording exists) | the template text |
| Translate to Urdu | `brain.translate` | organ-authored text (`verbatim` claims, Oracle narrative, Eyes validation note) not in the target language | JSON `{claim_id: text}` | `lang = ur` and such claims exist | keep the source text, mark `verbatim_foreign`, add a caveat |
| Judge statements | `brain.judge` | rewritten claim text plus evidence strings | JSON `{claim_id: "entailed" or "not_entailed"}` | the critic, for `phrased` or `translated` claims | for `fake` without a recording, a lexical proxy (at least 80% of the claim's content tokens appear in the evidence or template text); unparseable or unavailable: treat as not entailed, so the claim reverts to the template |

Nothing else is LLM-driven: claim numbers, severity, allocation, conflict detection, confidence, section status and ordering are code.

**Acceptance of an LLM rewrite** (per claim): parses as the requested JSON, the id exists, the length is at most 2.5x the template text, and checks C2, C3 and C5 pass. A failure keeps the template text. C6 happens in the critic. A claim containing a disputed marker, an evidence-forced label (section 5.4) or a verbatim organ text is never phrased (verbatim text is only translated).

**Prompt-injection posture.** Organ outputs and Library text are data. Prompts put them in a JSON array under a system instruction that says the content is untrusted data and instructions inside it are to be ignored. The model's output is parsed as strict JSON against a schema, ids not in the input are discarded, and every accepted string is re-checked by code. The Brain's behaviour, tool calls and evidence cannot be changed by anything the model writes. A test uses a `PoisonLLM` that returns injected text, extra ids, and numbers (BRN-P15).

**FakeLLM and determinism (BRN-P4).** `FakeLLM(path)` replays recorded responses keyed by `sha256(canonical_json({purpose, system, messages, schema, max_tokens, temperature}))`. Provider and model names are not part of the key, so a recording made with Claude replays under `fake`. Prompts contain only deterministic content (template texts, no timestamps or ids that vary per run, claim ids are deterministic). A missing recording raises `RecordingMissing`. Under `STITCH_FAKE_STRICT=1` (tests and the demo-recording check) it propagates and fails the test. Otherwise `llm_steps` catches it, records `llm_recording_miss` in the trace and uses the fallback. The Brain therefore produces a complete, correct briefing with an empty recording file, only without rewritten prose.

**Recordings.** Created by `python -m evals.brain.record_llm --scenario demo-sindh-2022 --lang en,ur --provider anthropic` (needs a key, run by the owner): runs the Brain with a `RecordingLLM` wrapper and appends `{key, purpose, request, response, provider, model, recorded_at, brain_version}` lines to `data/demo/llm/brain.jsonl`. Refresh whenever a template pattern changes, since prompts change. `test_demo_recordings_current` runs the demo scenarios under strict fake mode and fails with the list of stale keys. Recordings are reviewed like code (diffs are readable text).

## 13. Urdu briefings offline and with a provider (BRN-R7.5)

- **Brain-authored text is never machine translated.** Every template id has a pre-authored Urdu pattern in `config/i18n/ur.yaml`. For `lang = ur` the renderer fills the Urdu pattern with the same slots, so the numbers, units and citations are identical to English by construction (BRN-P14). With `fake` or no provider this is the whole Urdu briefing. The Urdu patterns need a native-speaker proofread (owner task).
- **Organ-authored text** (Library claims, Oracle narrative, Eyes notes, organ error messages) is handled by language:
  1. For the Library, the Brain sends the query in the target language (`lang` parameter and the Urdu query string from `scenarios.yaml`). If the Library answers in Urdu, the text is used as is.
  2. If a verbatim claim is still English and `lang = ur`, the `translate` step runs. The translation is accepted only if C2, C3 and C5 pass (same numbers and units, Urdu script), and `text_source = translated` makes the judge check it.
  3. With `fake` and no recording, or on any failure, the English text stays, `verbatim_foreign` is set, and a caveat says that part is shown in English.
- **Digits.** Urdu text defaults to ASCII digits (`ur_digits = ascii`). The extractor treats U+0660..0669 and U+06F0..06F9 as the same numbers, so setting `extended` is safe. Scale words (`لاکھ`, `کروڑ`) are rejected by the number check, so translations keep `1,000,000` as digits.
- Direction and fonts are the frontend's concern. The Brain returns plain text with no markup, and the identifiers, units and citations stay as separate tokens the UI can isolate.

## 14. API and events (`api/`)

FastAPI, Pydantic v2 models with `extra = "forbid"`. Errors use one model:
```json
{ "error": { "code": "INVALID_INPUT|NOT_FOUND|RATE_LIMITED|BUSY|CANCELLED|UPSTREAM_UNAVAILABLE|INTERNAL", "message": "...", "details": null } }
```
HTTP status: 400/422 `INVALID_INPUT`, 404 `NOT_FOUND`, 429 `RATE_LIMITED` or `BUSY` (with `Retry-After`), 503 `UPSTREAM_UNAVAILABLE`, 500 `INTERNAL`. The Brain never returns secrets, raw prompts, stack traces, or file paths.

| Method and path | Request | Response |
|---|---|---|
| `POST /briefings` | `BriefingRequest {region: str (slug, max 64), scenario: str (in scenarios.yaml), lang: "en"\|"ur" = "en", mode: "demo"\|"live" = "demo"}` | `202 {briefing_id, status: "running", events_url, result_url}` |
| `GET /briefings/{id}/events` | header `Last-Event-ID` (or `?last_event_id=`) | `text/event-stream`, see below |
| `GET /briefings/{id}` | | `200 {briefing_id, status: "running"\|"done"\|"failed"\|"cancelled", request, created_at, finished_at, briefing: Briefing\|null, error}` |
| `DELETE /briefings/{id}` | | `202`, idempotent cancel |
| `GET /organs` | | `{organs: [OrganInfo], brain_version, contract_version, llm_provider, default_mode}`; `OrganInfo {organ, status, compat, reason, served_by, stub, tools: [str], last_check, last_error, version}` |
| `GET /evidence/{run_id}?pointer=<RFC 6901>` | `run_id` is the call-level id | `200 {ref: EvidenceRef, value, organ, tool, served_by, mode, generated_at, node_id}`. Without `pointer`: `{ok, error, provenance, warnings, data_keys}` (no data). 404 `NOT_FOUND` with `reason` for unknown run id, mismatch, or unresolved pointer. Responses over 10 MB return 413. gzip enabled. |
| `POST /ask` | `{question: str (1..500 chars, control characters stripped), lang: "auto"\|"en"\|"ur" = "auto"}` | `200 AskResponse {ask_id, status: "answered"\|"refused", claims: [Claim], refusal_claim: Claim\|null, mode, library_run_id}`; 503 if the Library is unwell |
| `POST /voice/transcribe` | `{audio_b64, format, lang_hint?}` (body cap 14 MB) | the Voice `data` plus `{served_by}`; 503 `UPSTREAM_UNAVAILABLE` if Voice is disabled or unwell |
| `POST /voice/speak` | `{text (max 4000), lang, voice?, format?}` | the Voice `data` plus `{served_by}`; same 503 behaviour |
| `GET /evals/latest` | | the contents of `evals/results/latest.json`, or `{generated_at: null, organs: {}}` when none exists |
| `GET /healthz` | | `{status, organs_ready, db_ok}` |

Voice calls are proxied only; the Brain never logs audio, transcript, or speak text. Voice is not part of any briefing task graph.

**`POST /ask`.** Calls only `library.answer_with_citations` with the question and `lang`. The response claims are built by the same renderer as guidance claims (verbatim Library text, citation refs, refusal rendering), with no phrasing, translation, or added text, and the same provenance check (C1, C4). No other organ is called (BRN-P21). The evidence entry is stored under the generated `ask_id` so `/evidence/{run_id}` resolves its refs. Rate limit and size limits as below.

**Rate limiting.** In-memory token buckets keyed by client address (the `X-Forwarded-For` first hop only when `STITCH_TRUSTED_PROXY=1`, as behind Caddy): `POST /briefings` 6 per minute, burst 3; `/ask` 20 per minute; voice 10 per minute; other routes 120 per minute. The clock is injected. Global cap of 4 concurrent runs (`BUSY`).

**CORS.** `STITCH_CORS_ORIGINS` allowlist (default `http://localhost:3000,https://stitch.aashirnoman.dev`), methods `GET, POST, DELETE, OPTIONS`, no wildcard, no credentials.

**Validation.** All bodies and query parameters are Pydantic models. `region` and `scenario` must exist in `scenarios.yaml` and be compatible. Unknown fields are rejected. The Brain trusts nothing from the browser except the validated fields above.

### 14.1 SSE protocol
```
retry: 2000

id: 1
event: plan
data: {"event":"plan","ts":"2026-11-20T10:00:00Z","task_id":"plan","payload":{...}}

id: 2
event: organ_call
data: {"event":"organ_call","ts":"...","task_id":"eyes.compare","organ":"eyes","tool":"compare_with_permanent_water","payload":{...}}
```
- `id` is a per-run integer `seq`, starting at 1 and contiguous. `data` is the contract `TaskEvent` (`event`, `ts`, `task_id`, `organ?`, `tool?`, `payload`). `task_id` is the plan node id (`plan`, `critic`, `briefing` for run-level events).
- A comment line `: ping` every 15 s keeps proxies open.
- **Order.** `plan` is first. For each node, every `organ_call` (one per attempt) precedes its single `organ_result`. All `conflict` events come after the evidence they cite exists. `critic` events (one per pass) precede `briefing`. The last event is `briefing` (success) or an `error` with `fatal: true` (failure or cancellation). The stream closes after the last event.
- **Resume.** The run keeps an append-only `EventLog`. `Last-Event-ID: n` replays events with `seq > n` and then continues live, without gaps or duplicates: the subscriber registers and reads the replay under the same lock that `append` uses. A non-integer id is `400`. An id above the last known `seq` replays nothing and waits. Finished runs replay from DuckDB (section 15). A run that was running when the process stopped is marked `failed` (`RESTART`) at startup, and its stream ends with a fatal `error`.
- **Payloads (the Brain side of the frontend contract).**

| Event | `task_id` | Payload fields |
|---|---|---|
| `plan` | `plan` | `plan_id, revision, planner, scenario, lang, mode_requested, nodes: [{id, kind, organ, tool, deps, optional}], stub_organs: [str], added?: [str]` |
| `organ_call` | node id | `attempt, max_attempts, timeout_s, served_by, started_at` |
| `organ_result` | node id | `ok, attempt, duration_ms, served_by, run_id` (call-level, usable with `/evidence/{run_id}`), `mode`, `warnings: [str]`, `error?: {code, message, retryable}`, `summary: {scalar fields of data, at most 10}` for the organ drawer |
| `conflict` | `conflicts` | the contract `Conflict` plus `rule_id`, `status: "detected"\|"reconciling"\|"final"`, `subjects: [str]` |
| `critic` | `critic` | `pass, passed, issues: [{claim_id, check, detail}], removed: [str], reverted: [str]` |
| `briefing` | `briefing` | the full `Briefing` |
| `error` | node id or `run` | `code, message, fatal: bool, retryable`; non-fatal errors report a fallback such as `MODE_FALLBACK` (live to demo) |

The UI twitch/glow uses `organ_call` (start) and `organ_result` (end) timestamps and `duration_ms`. Evidence drill-down uses `GET /evidence/{run_id}?pointer=` with a claim's `EvidenceRef`. Map layers (`extent_geojson`, allocation) are fetched the same way, using the `run_id` from the `organ_result` event and the pointers `/data/extent_geojson` and `/data/allocation`.

## 15. Run store, traces, replay

**RunStore** (`runtime/store.py`): DuckDB file in a volume (`STITCH_BRAIN_DB`, in-memory fallback). Tables: `runs(briefing_id, created_at, finished_at, status, request_json, plan_json, briefing_json, error_json)`, `events(briefing_id, seq, ts, type, json)`, `evidence(call_run_id, briefing_id, node_id, organ, tool, served_by, result_json, original_sha256)`, `llm_calls(briefing_id, seq, purpose, key, response, provider)`. Writes go through one writer lock. Retention: the newest 50 runs and at most 48 h, whichever is fewer. Running runs live in memory first and are flushed per event (batched every 100 ms) so a crash loses at most a fraction of a second.

**Trace.** A trace is the minimum needed to replay a run: `request`, `scenario_config_hash`, `plan` (all revisions), organ outcomes in order (`node_id, attempt, entry`), `llm_calls`, `clock` (start time, virtual deltas), and the `events`. Traces are not served over HTTP. They are exported by `python -m stitch_brain.cli export-trace <id>` to `evals/brain/traces/<id>.json.gz`.

**Replay.** `replay(trace)` runs the normal pipeline with `RecordedOrgan(TraceFixtureSource)`, `FakeLLM(recordings from the trace)`, and a virtual clock. Replay yields the same briefing and the same event types and order as the original (compared after id normalization). Evals and BRN-P4 use it.

**Id normalization** (`core/briefing.py::normalize_ids`): replaces `briefing_id`, call-level run ids and timestamps by ordinals in first-appearance order. Briefings are compared after normalization (BRN-P4 needs this because organ run ids are uuids and `generated_at` is wall time; the real run ids for recorded entries are `uuid5(briefing_id, node_id, attempt)`).

**Logging.** Structured JSON through `stitch_common.logging` with `briefing_id`, `task_id` (the plan node id), `organ`, `attempt`, `duration_ms`. Info level logs prompt hashes and lengths only. Prompts are logged at debug level when `STITCH_LOG_PROMPTS=1`, never keys. Audio, transcripts and speak text are never logged.

## 16. Live mode (BRN-R9)

Live mode is a bonus. Contract v0.3 has no `mode` input on organ tools, so organs choose their own mode from their environment (`STITCH_MODE`). The Brain therefore:
1. Records `mode_requested` and, per organ result, `provenance.mode`.
2. Sets `briefing.mode = "live"` only if the request was `live` and every Eyes and Oracle result in the run has `provenance.mode = "live"`. Library and Ledger are local organs and do not count.
3. Otherwise sets `briefing.mode = "demo"`, emits a non-fatal `error` event `MODE_FALLBACK` with the reason, and `caveat.mode` says live data was unavailable (UI offline banner).
4. When an organ call fails in live mode with `UPSTREAM_UNAVAILABLE`, the Brain does not retry the same run in demo. It re-runs the failed nodes **once** against the demo-mode organ endpoint if `organs.yaml` configures a `demo_url` for that organ. Otherwise the section is `partial` or `unavailable`. (This avoids hidden mixing: any mix of live and demo results gives `mode = demo`.)
Proposed contract change C1 (optional `mode` input) would simplify this. Until then it is a configuration concern.

## 17. Evals (BRN-R11) (`evals/brain/`)

`python -m evals.run --organ brain --seed 0 [--fast] [--live-llm]` writes `MetricResult`s to `evals/results/brain.json` (bootstrap schema: id, label, value, target, unit, direction, dataset, mode, timestamp, git SHA, seed, notes) and merges them into `latest.json`. Default setup: recorded organs, `fake` LLM, virtual clock for scenario runs, real clock for the timing metric.

| Metric id | Definition | Target |
|---|---|---|
| `brain.faithfulness` | claims passing the independent verifier divided by all claims. The verifier (`evals/brain/verify.py`) is a separate implementation: it re-resolves every ref from the raw trace, re-extracts numbers with its own small regex, compares with `Decimal`, and for statements uses the judge. A claim passes if provenance resolves, all numbers match, units match, and (for rewritten statements) the judge says entailed. | 1.00 |
| `brain.faithfulness_numeric` | the same, restricted to `kind = number` and `recommendation` claims | 1.00 |
| `brain.faithfulness_statement` | the fraction of `kind = statement` claims entailed. With `fake`: verbatim and template claims are trusted, rewritten ones use the lexical proxy, and the note says `judge=lexical_proxy`. With `--live-llm`: a real judge. | 0.95 |
| `brain.provenance_coverage` | claims with at least one resolvable ref / all claims | 1.00 |
| `brain.conflict_recall` | seeded conflicts flagged / seeded conflicts (section 9.5) | 1.00 |
| `brain.conflict_false_positive_rate` | controls that raised a conflict / controls | 0.00 |
| `brain.degradation_success_rate` | single-organ-down runs that produced a briefing with correct section statuses / runs | 1.00 |
| `brain.time_to_briefing_s` | mean and p95 wall time over 10 runs of the default scenario (recorded organs, `fake`); a second figure with real Library and Ledger when the Compose smoke runs | report only (target under 5 s recorded, under 45 s Compose) |

Eval runs are deterministic with a seed (scenario mutations, backoff jitter) and never use the network.

## 18. Settings

| Variable | Purpose | Default |
|---|---|---|
| `STITCH_MODE`, `STITCH_LLM_PROVIDER` | as in `tech.md` | `demo`, `fake` |
| `STITCH_RECORDED_ORGANS` | organs served from fixtures | empty (dev sets `eyes,oracle,voice`) |
| `STITCH_ORGANS_DISABLED` | organs marked `disabled` | empty |
| `STITCH_BRAIN_PLANNER`, `STITCH_BRAIN_PHRASE` | `default\|llm`, `on\|off` | `default`, `on` |
| `STITCH_FAKE_STRICT` | missing LLM recording raises | `0` (tests set `1`) |
| `STITCH_RUN_DEADLINE_S`, `STITCH_ORGAN_DEADLINE_S` | deadlines | 60, 45 |
| `STITCH_BRAIN_DB` | DuckDB path | `/data/brain.duckdb` |
| `STITCH_CORS_ORIGINS`, `STITCH_TRUSTED_PROXY` | CORS and proxy trust | see section 14 |
| `STITCH_UR_DIGITS` | `ascii\|extended` | `ascii` |
| `STITCH_LOG_PROMPTS` | debug prompt logging | `0` |

Organ endpoints are in `config/organs.yaml` with env overrides (`STITCH_ORGAN_EYES_URL`).

## 19. Correctness properties and how they are tested

BRN-P1..P7 come from the requirements. BRN-P8..P24 are added by this design and are to be logged in `testing.md` by the owner. Hypothesis profile `ci`: 200 examples, deadline off. Shared strategies live in `tests/strategies.py`. `evidence_worlds()` builds a dict of valid `ToolResult` documents (from the `stitch_common` strategies) for Eyes, Oracle, Library, Ledger, including edge cases: zero values, empty arrays, refusals, null threshold, unicode district names, many districts, ids containing `/` and `~`. Every test runs under `no_network`.

| ID | Property | Test approach |
|---|---|---|
| BRN-P1 | every emitted claim has at least one ref and every ref resolves | draw a world, a random subset of organs failing, and `lang`; run synth + critic + assemble; assert claims have refs and `store.resolve` succeeds for each; `derive.ledger_input` lineage walks to organ entries |
| BRN-P2 | every number in claim text appears in, or is derived by a named function from, its evidence | independent test-local formatter computes expected numbers from raw floats; extracted numbers must be a subset; adversarial `MutatingLLM` (inject a number, scale a number, drop a unit, swap units, Arabic-Indic digits, number words, `lakh`) must leave the final text equal to the template text or equal to a text that passes the check |
| BRN-P3 | a briefing is produced with any single organ down | exhaustive matrix: every non-empty subset of {eyes, oracle, library, ledger} (15) times failure modes {error result, timeout, transport exception, hang until deadline, schema-invalid result}; assert a briefing is returned, no exception, the missing organ's sections are `partial` or `unavailable`, a `caveat.missing` claim cites the failed entry, confidence is not above the all-up value. The all-organs-down case yields all sections `unavailable` except caveats |
| BRN-P4 | same request with `fake` LLM gives the same briefing | run twice, compare after `normalize_ids`; run once, replay its trace, compare; Hypothesis draws per-node virtual delays (0 to 10 s) so completion order varies, and output must not change |
| BRN-P5 | the task graph is acyclic and dependencies exist | Hypothesis generates random graphs (valid DAGs, cycles, self-loops, missing deps, duplicate ids, unregistered builders): `validate_plan` accepts exactly the valid ones. For every shipped scenario the default plan validates. An executor test records start and end times and asserts no node starts before its hard dependencies end. Invalid LLM plan output falls back to the default plan |
| BRN-P6 | seeded conflicts are always flagged | seeded mutators with Hypothesis-drawn magnitudes inside the firing region; the conflict appears in `briefing.conflicts` and in a `conflict` event, and its claims carry the disputed marker or a reconciled caveat. Negative controls do not fire (BRN-P18) |
| BRN-P7 | the critic is idempotent | generate briefings with injected failures (corrupt a number, drop a ref, wrong unit, wrong language, missing caveat); `critic(critic(b)) == critic(b)` including `removed_claims`, `notes` and `passed` |
| BRN-P8 | evidence refs resolve after a JSON round-trip of the store | `store == loads(dumps(store))` on every ref in P1 worlds |
| BRN-P9 | claim ids are unique and deterministic | no duplicates within a briefing; same inputs, same ids |
| BRN-P10 | executor invariants | every node reaches exactly one terminal state; hard-dependency failure implies `skipped`; the organ phase never runs past its deadline in virtual time; concurrency limits (6 total, 2 per organ) are never exceeded; retries only for retryable errors, at most 3 attempts |
| BRN-P11 | SSE resume has no gaps or duplicates | drive the `EventLog` and the SSE generator with random disconnect points and concurrent appends; the concatenated received ids are exactly `1..n` in order; `Last-Event-ID` beyond the end waits; non-integer is 400 |
| BRN-P12 | the critic never adds claims, evidence, or text other than template text | compare before and after: ids subset, refs subset, changed texts equal the template rendering |
| BRN-P13 | number extraction and formatting round-trip | for a Decimal and decimals `k`, `extract(format(v, k))` equals `round(v, k)`, in `en`, in `ur`/`ascii`, and in `ur`/`extended`; digit-system variants of a text extract identical values; separator handling for `,`, U+066C, U+066B |
| BRN-P14 | the English and Urdu renderings of a claim have the same multiset of numbers and units | draw a world, render both languages, compare |
| BRN-P15 | a poisoned or malformed LLM response never alters a briefing | `PoisonLLM` returns injected instructions, extra ids, a fake claim, invalid JSON, giant text: the briefing equals the template-only briefing |
| BRN-P16 | confidence is bounded and monotone | the properties in section 11 over drawn organ confidences, conflicts, removals |
| BRN-P17 | the severity mapping is bounded and monotone | the properties in section 8; order invariance |
| BRN-P18 | the rule engine is safe, deterministic, and has no false positives on controls | fuzz YAML: it loads to an AST or raises `RuleConfigError`; a static scan forbids `eval`, `exec`, `compile`, `getattr`, `__import__` in the rules modules; complementary worlds (Oracle high, or districts all flooded, or Library quantity within tolerance) never fire |
| BRN-P19 | a recorded organ is always labelled | for any run where an organ is `served_by = "recorded"`, `/organs` flags it, a `caveat.recorded.<organ>` exists and resolves, the evidence entry carries the warning; the fixture content is mutated (including removing its own warnings) without changing the result |
| BRN-P20 | reconciliation runs at most once and terminates | in every run, `ledger.rerun` count is at most 1; with rules forced to fire on every pass, the run still ends; the second evaluation pass schedules no node |
| BRN-P21 | `/ask` calls only the Library and adds no text | a spy registry asserts no other organ is touched; the response claim texts equal the Library claim texts; a refusal renders as a refusal |
| BRN-P22 | the rate limiter never admits more than its budget | token bucket with an injected clock: requests admitted in any window do not exceed rate x window + burst |
| BRN-P23 | the pointer resolver follows RFC 6901 | arbitrary JSON with keys containing `/`, `~`, empty string, unicode: `resolve(doc, pointer_for(path))` returns the value at `path`; bad forms (`01`, `-`, missing leading `/`) return `Unresolved`, never raise |
| BRN-P24 | no forbidden vocabulary on Oracle claims | all Oracle-citing claims across drawn worlds contain the modeled label and none of the forbidden terms, in both languages |

Contract tests: the Brain's `Briefing`, `TaskEvent` and `EvidenceRef` outputs validate against the `stitch_common` schemas, and the tool arguments it sends validate against each tool's input schema (also from `stitch_common`). Integration tests (marked `integration`, run in CI with Compose or local stdio): Brain drives the real Ledger over stdio under `no_network` (pipes only); Brain with real Library runs in the Compose smoke test only, since the Library needs Postgres.

## 20. Decisions and assumptions (confirm with the owner)

1. `EvidenceRef.run_id` is the call-level run id. `/evidence/{run_id}` takes that id. (Requirements say "keyed by `run_id`" without saying which.)
2. A recorded organ is chosen by configuration, never by silent failover.
3. Disclaimer and mode caveats are claims that cite brain-origin entries (`static.disclaimer`, `run_meta`), so BRN-P1 holds without exempting them.
4. Brain-authored Urdu text uses pre-authored templates. LLM translation applies only to organ-authored text.
5. The severity mapping, its five parameters, and the road-access proxy are assumptions, flagged in every allocation caveat.
6. Conflict thresholds are judgement values (section 9.3).
7. R1 and R3 conflicts are flagged, not auto-reconciled. R3 could re-run the Ledger with the Library quantity, but that would let extracted free text drive an allocation.
8. The headline demo (`demo-sindh-2022`) should be clean. A second scenario `demo-sindh-2022-conflicts` ships seeded fixtures (dry district, quantity mismatch) so the conflict and reconciliation feature can be shown on purpose. Owner to confirm.
9. Station id, scene date, basin districts and guidance questions in `scenarios.yaml` are placeholders until the Eyes, Oracle and Library designs fix them.
10. `confidence` is a heuristic with judgement weights, not a calibrated probability.

## 21. Risks

| Risk | Mitigation |
|---|---|
| Recordings and Urdu patterns drift when templates change | `test_demo_recordings_current`; Urdu pattern completeness test; owner proofreads Urdu once |
| The number checker produces false failures on legitimate text and removes claims | rewrites fall back to the template first; only template claims that truly fail are removed; the eval counts reverts and removals |
| Library text is free-form, so extracting a quantity for R3 is brittle | explicit unit aliases per question, ambiguous means skipped (never a false conflict), recall measured on seeded fixtures; proposed structured `quantities` output (section 22) |
| MCP SDK cancellation semantics and Windows stdio pipes under `pytest-socket` | test the stdio path early (task 8); fall back to discarding results of cancelled calls |
| Timeline: Brain core with Library and Ledger in about 3 days | the vertical slice (tasks 1 to 10) is usable alone; conflicts, critic, SSE, Urdu and live mode are layered on top |
| FakeLLM keying is shared with the Library spec | agree on the key function in `stitch_common.llm` before either spec records responses (task 2) |
| DuckDB single-writer under concurrent runs | one writer lock, batched flush, in-memory fallback |
| Recorded fixtures drift from real organ output | fixtures validate against `stitch_common`; the capture script regenerates them; the integration test compares fixture and real-organ shapes |

## 22. Proposed contract changes (do not apply without the owner)

The Brain works with v0.3 as written. These would improve it. Logged here, not edited into the steering files.

| # | Change | Reason |
|---|---|---|
| C1 | optional `mode: "demo"\|"live"` input on Eyes, Oracle and Ledger tools | BRN-R9.1 needs to pass the mode to the organs; v0.3 tools have no such input |
| C2 | `Claim.labels: [str]` (values `modeled`, `unvalidated`, `recorded`, `demo`, `refusal`, `disputed`) | labels are in claim text today; the UI should not parse text (FRN-P6) |
| C3 | `Briefing.organs: [{organ, status, served_by}]`, `Briefing.disclaimer`, `Section.missing: [str]` | self-describing briefing; R3.3 says "naming what is missing" |
| C4 | `TaskEvent` types add `notice`; `payload.fatal` on `error` | the Brain emits non-fatal fallbacks as `error` today |
| C5 | clarify that `EvidenceRef.run_id` is the call-level `provenance.run_id`, and that `/evidence/{run_id}` uses it | currently ambiguous |
| C6 | `Conflict.rule_id`, `Conflict.status`, `Conflict.subjects` | UI shows the rule and affected districts |
| C7 | Library `answer_with_citations` optional `quantities: [{value, unit, per, claim_idx}]` | removes regex extraction for conflict rule R3 |
| C8 | Eyes `compare_with_permanent_water` optional `flooded_roads_km` per district | replaces the road-access proxy in section 8 |
