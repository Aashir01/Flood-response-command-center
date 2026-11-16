# brain: Requirements

The agentic orchestrator (not an MCP server). Prefix `BRN`. Contract: `mcp-contracts.md` §8.

## Introduction
The Brain discovers organs over MCP, plans a task graph for a scenario, runs organ calls in parallel where dependencies allow, detects conflicts between organ outputs, runs a critic pass, and produces a briefing in which every claim traces to an organ output.

## Glossary
- **Task graph**: a DAG of organ calls and synthesis steps with explicit data dependencies.
- **Evidence store**: per-run store of every `ToolResult` keyed by `run_id`.
- **Claim**: an atomic statement or number in the briefing.
- **Conflict**: two organ outputs that cannot both hold under a defined rule.

## Requirements

### BRN-R1 Organ discovery
1. WHEN the Brain starts, THE Brain SHALL connect to the organ servers listed in configuration and call MCP `tools/list` on each.
2. THE Brain SHALL validate discovered tool schemas against the contracts and mark an organ `incompatible` on mismatch.
3. THE Brain SHALL track organ health (`ready`, `degraded`, `unwell`, `disabled`) via `/healthz` and call outcomes, and expose it to the frontend.
4. IF an organ is unreachable at startup, THEN THE Brain SHALL start anyway and retry with backoff.

### BRN-R2 Planning
1. WHEN a briefing is requested with `{region, scenario, lang, mode}`, THE Brain SHALL produce a task graph and execute it with a custom asyncio task-graph executor. No agent framework (e.g. LangGraph) is used.
2. THE Brain SHALL emit the plan as a `plan` event before executing it.
3. THE planner's output SHALL be validated against a schema, and an invalid plan SHALL fall back to a deterministic default plan for the scenario.
4. WHERE `STITCH_LLM_PROVIDER = fake`, THE Brain SHALL use the deterministic default plan and recorded synthesis.

### BRN-R3 Execution
1. THE Brain SHALL run independent tasks concurrently (Eyes, Oracle, and Library queries in parallel; Ledger after Eyes and Oracle supply severity).
2. THE Brain SHALL apply a per-call timeout, a bounded retry for `retryable` errors, and a global run deadline.
3. WHEN an organ call returns an error, THE Brain SHALL continue with the other organs and mark dependent sections `partial` or `unavailable`, naming what is missing.
4. THE Brain SHALL emit `organ_call` and `organ_result` events with timing, for the UI twitch/glow.
5. THE Brain SHALL store every organ `ToolResult` in the evidence store before using it.

### BRN-R4 Conflict detection
1. THE Brain SHALL apply a rule set across organ outputs, including at least: Oracle exceedance probability low while Eyes shows flooded area above a threshold in the same basin; Ledger allocating to a district Eyes shows as unflooded; Library guidance quantity differing from the quantity the Ledger used.
2. WHEN a conflict is detected, THE Brain SHALL emit a `conflict` event, include it in the briefing with both evidence refs, and avoid presenting either side as settled.
3. WHERE a rule specifies an automated reconciliation (e.g. re-run Ledger with Eyes-derived severity), THE Brain SHALL apply it once, record it, and mark the conflict `reconciled`.
4. THE conflict rules SHALL be data-driven (declared in a config file) and unit-tested with fixtures.

### BRN-R5 Provenance
1. THE Brain SHALL attach to every briefing claim at least one `EvidenceRef` that resolves to a field in the evidence store.
2. THE Brain SHALL derive numeric claims by code from organ outputs, not from LLM free text. The LLM MAY phrase claims but SHALL NOT introduce numbers absent from the evidence.
3. THE Brain SHALL remove any claim that lacks resolvable evidence and list it in `critic.removed_claims`.
4. THE Brain SHALL expose an endpoint to resolve an `EvidenceRef` to its source value for UI drill-down.

### BRN-R6 Critic
1. AFTER synthesis, THE Brain SHALL run a critic pass that checks: provenance for each claim, numeric consistency between claim text and evidence, citation presence for guidance claims, unit consistency, and language match.
2. IF the critic finds a failure, THEN THE Brain SHALL repair or remove the claim, and run the critic at most N times (N set in design), then emit the result with `critic.passed` reflecting the final state.
3. THE Brain SHALL never emit a briefing whose `critic.passed = false` without a visible caveat section.

### BRN-R7 Briefing
1. THE Brain SHALL produce a briefing with sections `extent`, `forecast`, `guidance`, `allocation`, and `caveats`, in `en` or `ur`.
2. THE Brain SHALL include overall `confidence` computed by a documented formula from organ confidences, conflicts, and missing organs.
3. THE Brain SHALL include the demo/live mode and a disclaimer that Stitch is decision support.
4. WHERE a Library result is a refusal, THE Brain SHALL show that refusal in the guidance section and not fill the gap from LLM memory.
5. WHERE `lang = ur`, THE Brain SHALL translate prose through the LLM, and keep numbers, units, and citations unchanged.

### BRN-R8 API
1. THE Brain SHALL expose `POST /briefings` (start run), `GET /briefings/{id}/events` (SSE), `GET /briefings/{id}` (result), `GET /organs` (health), `GET /evidence/{run_id}` (resolve refs), `POST /voice/transcribe` and `POST /voice/speak` (proxy), `GET /evals/latest`.
2. THE Brain SHALL validate all inputs with Pydantic and rate-limit `POST /briefings` per client.
3. THE Brain SHALL enforce a CORS allowlist and have no endpoint that returns secrets or raw prompts.
4. THE SSE stream SHALL support resume by `Last-Event-ID`.

### BRN-R9 Live mode
1. WHERE `mode = live`, THE Brain SHALL pass live mode to the organs and show an offline banner and fall back to demo with `mode = demo` when upstream calls fail.

### BRN-R10 Observability
1. THE Brain SHALL log structured JSON with a `task_id` per run, never log keys or full prompts at info level, and record a replayable trace per run (inputs, plan, events) for evals.

### BRN-R11 Eval
1. THE Brain eval SHALL report end-to-end faithfulness: the fraction of claims whose text is entailed by their evidence (code check for numbers; judge check, with `fake` or a real LLM, for statements), claim provenance coverage, conflict-detection recall on seeded scenarios, and mean time to briefing.

### BRN-R12 Demo-first
1. THE Brain SHALL produce a full briefing in demo mode from committed data with no network calls, using the `fake` LLM, enforced by tests that disable sockets.
2. Live mode is optional. Upstream failure SHALL fall back to demo with a visible banner.

### BRN-R13 Design write-up
1. THE repo SHALL document the planner, executor, conflict rules, critic, and provenance design in `docs/brain-design.md`, since the architecture is the demonstration of the "Frankenstein" idea.

### BRN-R14 Ask the creature
1. THE Brain SHALL expose `POST /ask` that routes a free-text question (typed, or transcribed by Voice when available) to the Library only, and returns the Library's answer with citations or its refusal.
2. THE Brain SHALL NOT call other organs for `/ask`, SHALL NOT add text to the Library answer, and SHALL apply the same provenance and refusal display rules as a briefing.
3. THE endpoint SHALL be rate-limited and validate input length (at most 500 characters).

## Correctness properties (formalized in design)
- BRN-P1: every claim in an emitted briefing has at least one `EvidenceRef`, and each resolves.
- BRN-P2: every number in claim text appears in (or is derivable by a named pure function from) its evidence.
- BRN-P3: the briefing is produced even if any single organ is down (graceful degradation), with affected sections marked.
- BRN-P4: with `fake` LLM, the same request yields the same briefing (deterministic).
- BRN-P5: the task graph is acyclic and every task's dependencies exist.
- BRN-P6: seeded conflict scenarios are always flagged (no silent resolution).
- BRN-P7: the critic is idempotent: running it on its own output changes nothing.

## Out of scope
User accounts. Persistent multi-user history beyond the last N runs. Autonomous action outside the organs.

## Decisions (resolved)
1. Planner: a plain asyncio task graph. LangGraph is not added just to name a framework.

## Decision
The "ask the creature" box is in scope, minimal, routed to the Library only (BRN-R14).