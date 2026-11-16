# brain: Tasks

Tags: `core` (must ship), `stretch`, `slice` (part of the minimal vertical slice). Each task lists the requirements and properties it satisfies and the tests that prove it. Ordered by dependency. Commit after each task (`feat(brain): ...`).

Blocked by the **bootstrap** spec: `stitch_common` models and envelope, `no_network` fixture, Hypothesis profiles, hooks, eval runner skeleton. Library and Ledger organs are needed from task 8 on for the real-organ integration tests only. Everything else runs on recorded fixtures.

Schedule target: tasks 1 to 10 (the vertical slice) end of day 1. Tasks 11 to 19 (all four organs on fixtures, conflicts, critic, confidence, degradation) end of day 2. Tasks 20 to 25 (LLM steps, Urdu, store, SSE API, `/ask`) end of day 3. The remaining tasks follow. The three-day target is tight, so if time runs out, defer in this order: 27, 26, 21 (translation part), 28 (faithfulness with `--live-llm`), 20 (phrasing; the templates already give a complete briefing).

## Day 1: minimal vertical slice (executor, evidence, ledger-only briefing)

- [ ] **1. Scaffold the package** `core` `slice`
  - Create `brain/` (`pyproject.toml`, `src/stitch_brain/{core,runtime,api}`, `tests/{unit,property,contract,integration}`, `config/`, README). Add to the uv workspace, `mypy --strict` and `ruff` config for `brain/`. Add `data/demo/recorded/`, `data/demo/llm/`, `evals/brain/` placeholders.
  - Confirm `no_network` is on by default and the Hypothesis profiles work. Add a THIRD_PARTY.md line for new dependencies (`mcp`, `fastapi`, `uvicorn`, `duckdb`, `pyyaml`, `sse` helper if used).
  - Done when: `uv run pytest` passes on the skeleton.
- [ ] **2. Shared models, LLM client interface, clock** `core` `slice`
  - Check `stitch_common` has `ToolResult`, `Provenance`, `EvidenceRef`, `Briefing`, `Claim`, `Conflict`, `TaskEvent`. Add `Slot`, `ClaimDraft` internals in `stitch_brain` only (not in the contract).
  - Check `stitch_common.llm`: `LLMClient.complete(...)` with `purpose`, `FakeLLM` keyed by `sha256(canonical_json({purpose, system, messages, schema, max_tokens, temperature}))`, `RecordingMissing`, `STITCH_FAKE_STRICT`. If the Library spec has not built it yet, build the minimal version here and agree the key function with that spec. Add `Clock` (real, virtual) in `runtime/clock.py`.
  - Tests: key stability (same request same key; provider and model not in key); virtual clock ordering; FakeLLM replay and miss. Refs: BRN-R2.4, BRN-R12.
  - Done when: FakeLLM replays a recorded response by key and raises on a miss in strict mode.
- [ ] **3. RFC 6901 resolver and evidence store** `core` `slice`
  - `core/pointer.py` (`parse`, `escape`, `pointer_for`, `resolve`), `core/evidence.py` (`EvidenceEntry`, `EvidenceStore.put/get/by_node/resolve`, NaN rejection, brain-origin entries, JSON dump and load).
  - Tests: unit cases from RFC 6901 section 5; BRN-P23 (arbitrary JSON, keys with `/`, `~`, empty, unicode; bad forms never raise); BRN-P8 (round-trip of the store); a ref to a failed entry resolves only into `/error`, `/provenance`, `/warnings`. Refs: BRN-R5.1, R5.4, R3.5.
  - Done when: P23 and P8 pass under `ci`.
- [ ] **4. Numbers: normalization, extraction, matching, units, formatting** `core` `slice`
  - `core/numbers.py` and `core/textfmt.py` per design section 6: digit systems, separators, masks, number words, allowed-set matching with rounding, unit table and aliases, language-match check, formatter with `ROUND_HALF_UP`. Pattern linter: patterns contain no digits.
  - Tests: BRN-P13 (round-trip across `en`, `ur` ascii, `ur` extended); unit tests for scale words, `p10/p50/p90` masking, `m3/s` vs `m³/s`, swapped units, extra decimals, dropped slot; table tests from the worked examples. Refs: BRN-R5.2, R6.1.
  - Done when: P13 passes and each rejection class has a named test.
- [ ] **5. Plan model, validation, default plan** `core` `slice`
  - `core/graph.py`, `core/plans.py`: `Node`, `Dep`, `Plan`, `validate_plan`, `topological_levels`, argument builder registry, default plan for `demo-sindh-2022` (design 7.1). `config/scenarios.yaml` with placeholders listed in design section 20.
  - Tests: BRN-P5 (random graphs: valid DAGs accepted, cycles, self-loops, missing deps, duplicates, unregistered builder, too many nodes rejected); default plans validate. Refs: BRN-R2.1, R2.3.
  - Done when: P5 passes.
- [ ] **6. Executor** `core` `slice`
  - `runtime/executor.py`: scheduling with hard and soft deps, concurrency limits, per-call timeout, retry policy with deterministic jitter, organ-phase and run deadlines, cancellation, outcomes, event emission hooks, dynamic node addition, injected `Clock`.
  - Tests: BRN-P10 (invariants with random virtual delays and failures); retry only on retryable; deadline marks `timed_out` and skips dependents; cancellation; node exception becomes `failed`; no node starts before hard deps. Refs: BRN-R3.1 to R3.4.
  - Done when: P10 passes and a three-organ fake graph runs in virtual time with the expected order.
- [ ] **7. OrganClient, RecordedOrgan, fixtures** `core` `slice`
  - `runtime/organs.py` protocol, `runtime/recorded.py` with `DirectoryFixtureSource`, deep-subset matching, most-specific-wins, `NOT_FOUND` on no match, provenance run id rewrite (`uuid5`), appended `RECORDED_FIXTURE` warning with `original_sha256`.
  - Hand-author Ledger fixtures first (`optimize_allocation`, `sensitivity_report`, resource `districts`) in `data/demo/recorded/ledger/...`, validated against `stitch_common`. Add the `STITCH_RECORDED_ORGANS` setting.
  - Tests: matching rules; fixtures validate; label in the entry; BRN-P19 first half (fixture content cannot remove the label). Refs: BRN-R1, R12.1.
  - Done when: the executor runs `ledger.optimize` from a fixture and the evidence entry carries `served_by = recorded`.
- [ ] **8. MCP client, registry, compatibility, health** `core` `slice`
  - `McpOrganClient` over stdio and streamable HTTP; supervisor with backoff; `tools/list` and `resources/list`; schema compatibility check against `stitch_common`; health states and `/healthz` polling; circuit breaker; per-organ config in `config/organs.yaml`.
  - Tests: fake in-process MCP server (an incompatible one, a slow one, a flapping one); health state table tests; backoff with a virtual clock; startup with every organ unreachable succeeds. Integration (marked): real Ledger over stdio under `no_network`, list tools and call both tools. Check the cancellation behaviour of the SDK and write the finding in the README. Refs: BRN-R1.1 to R1.4.
  - Done when: the real Ledger answers through the registry, and an unreachable organ is retried without blocking startup.
- [ ] **9. Claim model, allocation and caveat templates (English)** `core` `slice`
  - `core/claims.py`, `core/derive.py` derivation registry (`sum`, `count`, `top_n_by`, `argmax_item`, `pct`, `ratio`, `per_day`), `core/templates/allocation.py` and `caveats.py` (`allocation.summary`, per-district recommendations, `allocation.unreached`, `caveat.disclaimer`, `caveat.mode`, `caveat.missing.*`, `caveat.recorded.*`), `config/i18n/en.yaml`, brain-origin entries (`static.disclaimer`, `run_meta`).
  - Tests: each template renders from a fixture and every slot ref resolves; claim ids deterministic (BRN-P9); numeric slots re-derive. Refs: BRN-R5.1, R5.2, R7.1, R7.3.
  - Done when: the Ledger fixture renders a full allocation section whose every number matches `numbers` allowed-set checks.
- [ ] **10. Runner, assembler, CLI: ledger-only briefing** `core` `slice`
  - `runtime/runner.py` (plan, execute, synth, assemble), `core/briefing.py` (sections, statuses per design 7.4, ordering, `normalize_ids`, projection to contract `Briefing`), a first `confidence.py` placeholder, CLI `python -m stitch_brain.cli run --scenario demo-sindh-2022 --lang en --organs recorded`.
  - Tests: a briefing is produced with only the Ledger fixture (other sections `unavailable`, `caveat.missing.*` present); BRN-P1 on this slice; contract test that the output validates as `Briefing`; the run uses no sockets. Refs: BRN-R7, R12.1.
  - Done when: the CLI prints a valid briefing JSON from committed fixtures with sockets disabled.

## Day 2: all organs on fixtures, conflicts, critic

- [ ] **11. Library guidance claims and refusals** `core`
  - `core/templates/guidance.py` per design 5.5, refusal rendering and reason mapping, Library question nodes from `scenarios.yaml`, Library fixtures (an answered, a refused with `INSUFFICIENT_EVIDENCE`, an answered Urdu).
  - Tests: every guidance claim has a resolving citation ref; a bad `citation_idx` is dropped and reported; refusal rendered, never filled in; BRN-P1 extended. Refs: BRN-R5.1, R7.4.
  - Done when: the three fixtures render as guidance with citations or a refusal.
- [ ] **12. Eyes and Oracle templates, labels, recorded fixtures** `core`
  - `core/templates/extent.py`, `forecast.py`; caveats `eyes_unvalidated`, `oracle_modeled`; `i18n` labels and forbidden-term lists; hand-authored Eyes and Oracle fixtures with the real field shapes (including `validated_for_region = false`, `target_kind = modeled_glofas`, null threshold variant).
  - Tests: BRN-P24 (modeled label, no forbidden terms); unvalidated caveat appears; recorded caveats; null threshold omits the exceedance claim. Refs: BRN-R5, R7.1, R7.3.
  - Done when: all five sections render from fixtures with the labels.
- [ ] **13. Severity mapping and Ledger input** `core`
  - `core/derive.py::build_ledger_input` per design section 8 (`full` and `eyes_only` modes), `ledger.districts` resource node, `derive.ledger_input` brain-origin entry with lineage and assumptions, caveat `assumptions`, fallback paths for missing Eyes or Oracle.
  - Tests: the worked example as a unit test (D and E rows); BRN-P17; the lineage walk resolves to organ entries; missing Eyes sends no override. Refs: BRN-R3.1, R3.3.
  - Done when: the worked example reproduces the design numbers and P17 passes.
- [ ] **14. Ledger sensitivity and equity claims** `core`
  - `ledger.sensitivity` optional node, `allocation.equity`, `allocation.shadow.*`; fixture for sensitivity.
  - Tests: shadow claims only for binding supply constraints; null `equity_cost` omitted. Refs: BRN-R5, R7.1.
  - Done when: the allocation section includes shadow-price and equity claims with refs.
- [ ] **15. Facts and rule engine** `core`
  - `core/facts.py` registry, `core/rules.py` AST, YAML loader and JSON Schema export, `config/conflict_rules.yaml` (R1, R2, R3) with params, i18n descriptions (en, ur), `affects` lists.
  - Tests: BRN-P18 (fuzz loads, static scan for forbidden names, controls never fire); unit tests per fact and per rule on fixtures; skipped rules recorded with a reason; `eyes_dry_frac` equals the severity `f_noise` (test). Refs: BRN-R4.1, R4.4.
  - Done when: P18 passes and each rule fires on a hand-built world.
- [ ] **16. Conflict stage, reconciliation, seeded scenarios** `core`
  - `conflicts` node, one-shot `ledger.rerun`, pass 2 evaluation, resolutions `flagged|reconciled|escalated`, disputed markers, `caveat.conflict.*`, `plan` revision event. `evals/brain/scenarios.py` mutators, 30 seeded scenarios, scenario `demo-sindh-2022-conflicts` with fixtures.
  - Tests: BRN-P6 and BRN-P20 (at most one rerun; terminates when rules always fire); a reconciled conflict still appears in the briefing with both Ledger run refs; rerun failure gives `escalated` or `flagged` with the original allocation. Refs: BRN-R4.1 to R4.4.
  - Done when: every seeded conflict is flagged and controls are clean.
- [ ] **17. Critic** `core`
  - `core/critic.py` checks C1 to C7 and S1 to S7, repair loop `N = 3`, judge interface with cache, `critic` brain-origin entry, `caveat.critic_failed` added by the assembler.
  - Tests: BRN-P7 (idempotent with injected failures), BRN-P12 (no additions), one named test per check and per repair step; critic failure produces the caveat. Refs: BRN-R5.3, R6.1 to R6.3.
  - Done when: P7 and P12 pass.
- [ ] **18. Confidence** `core`
  - `core/confidence.py` and `config/confidence.yaml` per design section 11.
  - Tests: BRN-P16; the three worked examples as unit tests; weights sum to 1. Refs: BRN-R7.2.
  - Done when: examples A, B and C reproduce 0.78, 0.62, 0.63.
- [ ] **19. Graceful degradation matrix** `core`
  - Section statuses, `caveat.missing.*`, partial allocation caveats, synthesized failed entries for timeouts and invalid results.
  - Tests: BRN-P3 (full matrix: 15 organ subsets x 5 failure modes, plus all down). Refs: BRN-R3.3, R3.4.
  - Done when: P3 passes and the all-down case returns a briefing.

## Day 3: LLM steps, Urdu, store, API

- [ ] **20. LLM steps: phrase, judge, plan variation** `core`
  - `runtime/llm_steps.py`: `brain.phrase`, `brain.judge`, optional `brain.plan`; strict JSON parsing, acceptance checks, fallbacks, `RecordingMissing` handling, trace of every LLM call. Test doubles `MutatingLLM` and `PoisonLLM`.
  - Tests: BRN-P2 adversarial (all mutation classes rejected), BRN-P15, judge fallback (unavailable means revert), plan variation validates or falls back, recording miss yields the template briefing. Refs: BRN-R2.3, R2.4, R5.2, R6.1.
  - Done when: P2 and P15 pass and the template-only briefing is identical with the LLM disabled.
- [ ] **21. Urdu** `core`
  - `config/i18n/ur.yaml` for every template id, conflict description, caveat and the unit table; `translate` step for organ-authored text with `verbatim_foreign` fallback and caveat; Library queries in Urdu from `scenarios.yaml`.
  - Tests: BRN-P14 (same numbers and units in en and ur); every template id has both languages; language check on Urdu output; translation that changes a number or uses `لاکھ` is rejected. Refs: BRN-R7.5.
  - Done when: `--lang ur` produces a briefing offline with `fake` and P14 passes. Owner proofreads the Urdu patterns.
- [ ] **22. RunStore, event log, trace, replay** `core`
  - `runtime/store.py` (DuckDB tables, writer lock, retention 50 runs or 48 h, restart marks running runs `failed`), `EventLog`, trace export and `replay`, structured logging with `briefing_id` and `task_id`.
  - Tests: BRN-P4 (twice equal, replay equal, random virtual delays); retention and restart; log lines contain no prompt text at info. Refs: BRN-R10.1, R12.1.
  - Done when: P4 passes under `ci` and a replayed trace equals its original after id normalization.
- [ ] **23. FastAPI app, SSE, cancel** `core`
  - `POST /briefings`, `GET /briefings/{id}`, `GET /briefings/{id}/events` with `Last-Event-ID` resume and `: ping`, `DELETE /briefings/{id}`, error model, run concurrency limit, event payloads per design 14.1.
  - Tests: BRN-P11 (resume has no gaps or duplicates under random disconnects and concurrent appends); event order invariants; non-integer `Last-Event-ID` is 400; cancel yields a fatal `CANCELLED`; contract tests on `TaskEvent` and `Briefing`. Refs: BRN-R8.1, R8.2, R8.4.
  - Done when: a client can start a demo run, resume mid-stream, and read the same briefing from `GET`.
- [ ] **24. Evidence endpoint, `/organs`, `/evals/latest`, CORS, rate limits** `core`
  - `GET /evidence/{run_id}`, `GET /organs`, `GET /evals/latest`, `GET /healthz`, CORS allowlist, token-bucket limiter with injected clock, size limits, gzip.
  - Tests: BRN-P22; evidence endpoint round trip for every ref in a briefing (including recorded and brain-origin entries); 404 reasons; CORS preflight allowed and denied origins; no secrets or prompts in any response (scan). Refs: BRN-R5.4, R8.1 to R8.3, R1.3.
  - Done when: every claim ref in a demo briefing resolves through HTTP.
- [ ] **25. `POST /ask`** `core`
  - Library-only route, 500-character limit, control-character stripping, rate limit, response claims built by the guidance renderer, refusal rendering.
  - Tests: BRN-P21 (spy registry: only the Library is called; texts equal Library texts); length and empty input rejected; Library unwell gives 503. Refs: BRN-R14.
  - Done when: an answered and a refused question render correctly from fixtures.

## After day 3

- [ ] **26. Voice proxies** `core`
  - `POST /voice/transcribe` and `/voice/speak` as thin proxies, body caps, rate limit, 503 when Voice is disabled, recorded Voice fixtures, no logging of audio or text.
  - Tests: size caps; disabled Voice gives 503 and no other test changes; nothing sensitive logged. Refs: BRN-R8.1.
  - Done when: the frontend can detect Voice as unavailable without errors elsewhere.
- [ ] **27. Live mode and fallback** `core`
  - Mode resolution from `provenance.mode`, `MODE_FALLBACK` event, `caveat.mode` live variant, optional `demo_url` re-run once, tests with recorded live-shaped fixtures and a mixed live and demo case.
  - Tests: a mix of live and demo results yields `mode = demo`; upstream failure falls back and the banner event is emitted; live paths use fixtures only. Refs: BRN-R9.
  - Done when: the fallback tests pass without network.
- [ ] **28. Eval harness** `core`
  - `evals/brain/`: independent verifier, metrics of design section 17, seeded scenarios, timing, degradation sweep, results in the bootstrap `MetricResult` schema, `python -m evals.run --organ brain --seed 0`.
  - Tests: reproducible with a seed; the verifier catches a deliberately corrupted briefing; a smoke run is part of `--fast`. Refs: BRN-R11.
  - Done when: `latest.json` contains the Brain metrics and the same seed gives the same numbers.
- [ ] **29. Offline and integration suite** `core`
  - Full demo run under `no_network` with `fake` LLM; a test that fails on any socket creation; Brain with the real Ledger over stdio; Compose smoke entry for the Brain with real Library and Ledger (CI only); contract hook coverage of the Brain models.
  - Refs: BRN-R12. Done when: the offline suite is green and the Compose smoke produces a briefing with real Library and Ledger.
- [ ] **30. Recording and capture scripts** `core`
  - `evals/brain/record_llm.py` (writes `data/demo/llm/brain.jsonl`), `scripts/record_organ_fixture.py` (captures organ results to fixtures), `test_demo_recordings_current`.
  - Done when: the stale-recording test reports a changed template, and a refresh makes it pass.
- [ ] **31. Documentation** `core`
  - `brain/README.md` and `docs/brain-design.md`: planner, executor, conflict rules, critic and provenance, with a sequence diagram of one run and the claim lifecycle (evidence, slot, template, phrase, check, critic), the "Frankenstein" framing, the severity mapping and its assumptions, the property table, and limitations. Add the property-testing story to `docs/kiro-writeup.md`.
  - Refs: BRN-R13. Done when: a reader can follow one claim from an organ field to the UI drill-down.
- [ ] **32. Contract change proposal follow-up** `core`
  - After the owner decides on design section 22, update `mcp-contracts.md`, `stitch_common` and consumers in one change, bump `contract_version`, and adapt the Brain (labels field, organs list, `mode` input).
  - Done when: `check_contracts.py` passes and the Brain emits the agreed fields. Skip if the owner declines.
- [ ] **33. LLM plan variation in live mode** `stretch`
  - Exercise `STITCH_BRAIN_PLANNER=llm` with a real provider, record the plan prompts, and report invalid-plan fallbacks in the eval.
- [ ] **34. Structured Library quantities and Eyes road data** `stretch`
  - Use contract changes C7 and C8 to replace the regex extraction in fact `library.guidance_per_person_per_day` and the road-access proxy in section 8.
- [ ] **35. Demo run cache** `stretch`
  - Cache finished demo briefings by request hash for instant repeats, labelled as cached.

## Traceability

| Requirement | Tasks |
|---|---|
| BRN-R1 | 7, 8 |
| BRN-R2 | 2, 5, 20 |
| BRN-R3 | 6, 13, 19 |
| BRN-R4 | 15, 16 |
| BRN-R5 | 3, 4, 9, 11, 12, 17, 24 |
| BRN-R6 | 17, 20 |
| BRN-R7 | 9, 10, 11, 12, 18, 21 |
| BRN-R8 | 23, 24, 26 |
| BRN-R9 | 27 |
| BRN-R10 | 22 |
| BRN-R11 | 28 |
| BRN-R12 | 2, 7, 10, 22, 29 |
| BRN-R13 | 31 |
| BRN-R14 | 25 |

| Property | Task | Property | Task |
|---|---|---|---|
| BRN-P1 | 10, 11 | BRN-P13 | 4 |
| BRN-P2 | 20 | BRN-P14 | 21 |
| BRN-P3 | 19 | BRN-P15 | 20 |
| BRN-P4 | 22 | BRN-P16 | 18 |
| BRN-P5 | 5 | BRN-P17 | 13 |
| BRN-P6 | 16 | BRN-P18 | 15 |
| BRN-P7 | 17 | BRN-P19 | 7, 19 |
| BRN-P8 | 3 | BRN-P20 | 16 |
| BRN-P9 | 9 | BRN-P21 | 25 |
| BRN-P10 | 6 | BRN-P22 | 24 |
| BRN-P11 | 23 | BRN-P23 | 3 |
| BRN-P12 | 17 | BRN-P24 | 12 |

BRN-P8 to P24 are added by the design and are not in `requirements.md`.
