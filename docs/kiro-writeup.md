# How Stitch was built with Kiro

Stitch was built in the Kiro IDE between 2026-11-16 and 2026-11-18, in about 200 small Conventional Commits. This page lists each Kiro feature, what it was used for, and where the evidence is in the repository. Anything that was planned but not shown is stated as not shown.

## Steering

Six files in `.kiro/steering/` are loaded into every agent session:

| File | What it steers |
|---|---|
| `product.md` | What Stitch is, the five-part briefing, the persona (a district disaster officer), the priority order (Brain + Library + Ledger first, Voice last and time-boxed), and the non-negotiables: provenance on every claim, Library refusals, visible uncertainty, demo data labelled as demo, Oracle output called "modeled GloFAS" and never gauge data. |
| `tech.md` | Python 3.12, uv workspace, FastAPI, MCP SDK, Pydantic v2, `mypy --strict`, ruff; pure `core/` modules with thin MCP layers; organs never import each other; the `LLMClient` interface with the `fake` provider for offline demos; the env variable table; the demo-first rule. |
| `structure.md` | The repository layout, naming (`stitch_<organ>`, `<organ>-mcp`), requirement and property IDs (`LED-R4`, `LED-P2`), the rule that a contract change updates the markdown, `stitch_common` and every consumer in one commit, and a THIRD_PARTY row per new dependency. |
| `testing.md` | Test layers, the required properties (LED-P1, ORA-P1, EYE-P1, LIB-P1, BRN-P1 and more), Hypothesis profiles `dev` and `ci`, the eval metrics, the five hooks, and the `no_network` default for tests. |
| `ui-style.md` | The mad-scientist lab bench: organ jars, twitch-and-glow states, the lightning awakening (under 2.5 s, no flashing above 3 Hz), the dark map, color tokens with AAA body contrast, required panel states, keyboard and screen-reader rules, RTL. |
| `mcp-contracts.md` | The single source of truth for every tool's input and output (now v0.6), with a change log. `packages/stitch_common` mirrors it as Pydantic models, and `scripts/check_contracts.py` checks the version heading, the change log and 48 generated JSON Schemas. |

The steering files kept rules stable across many separate agent runs. Examples visible in the code: every Oracle value in the UI carries "Modeled (GloFAS)" (tested by FRN-P6 and a wording lint, ORA-P8), every tool returns the `ToolResult` envelope with provenance, and the organs share no imports. The effect of steering on agent output was not measured separately.

## Spec-driven development

Nine specs live in `.kiro/specs/`, each with `requirements.md`, `design.md` and `tasks.md`: `bootstrap`, `eyes-mcp`, `oracle-mcp`, `library-mcp`, `ledger-mcp`, `voice-mcp`, `brain`, `frontend`, `deployment`. Requirements are written in EARS form ("WHEN ... THE Ledger SHALL ...", "IF ... THEN ..."); the requirement files hold between 30 and 52 `SHALL` statements each. Every requirement has an ID (for example `LED-R1.6`), design sections define the properties (`LED-P1` to `P20`), and each task lists the IDs it satisfies and a "Done when" line. Tests carry the IDs in their names, so a property in a spec can be found in the test suite with a search.

Requirements were revised during review, and the revisions are in git:
- **Ledger equity floor** (commit `0e44998`, contract v0.3): the first draft had a `min_coverage_fraction`. Review found it could make a plan infeasible with no useful answer, so it was replaced by `equity_floor`, a fraction of each district's proportional share, with `on_infeasible_floor = "relax"` (solve at the highest feasible floor and report `floor_requested`, `floor_applied` and `max_feasible_floor`). Road access and air or boat delivery came in with the same revision.
- **Ledger P18** (commit `f925cc9`): a property found that integer rounding can send one unit more than a road-denied district's air or boat capacity. The owner chose to amend LED-R1.6 and P18 rather than weaken the solver.
- **Voice revision R-DG** (commit `fa4bd42`): the owner switched the hosted voice vendor from Azure to Deepgram. The spec gained VOX-R10.1 to R10.5 (Nova-3 STT, Aura-2 English TTS, a budget guard, `mip_opt_out=true`, and no committed generated audio because Deepgram's terms do not clearly allow redistribution) instead of a silent rewrite. Contract v0.5 added `deepgram` as a provider.
- **Eyes precision** (contract v0.6): the export check (EYE-P5) decides which ONNX precision ships, so `model_variant` gained fp16 and fp32 values.
- Approved decisions from the first review (demo-first, modeled labelling, TTS provider, equity trade-off curve) were folded into all specs in commit `9905972`.

Tasks are ticked only when code and tests exist. Each `tasks.md` ends with a "Status (final audit)" note listing the open tasks and why they are open (stretch, cut, or owner action).

## Property-based testing

Hypothesis runs 132 `@given` properties across 41 property-test files in Python, and fast-check runs the frontend properties (FRN-P1 to P7). Each property carries its spec ID. A pytest plugin in `stitch_common.testing` blocks outbound network for all tests (a Windows-safe guard, because `pytest-socket` breaks asyncio's `socketpair` on Windows) and registers the profiles `dev` (30 examples) and `ci` (200). Failing examples were turned into named regression tests. The bootstrap properties (BOOT-P1 to P7) cover the envelope invariant, the canonical `inputs_hash`, `Interval` ordering, schema round trips, the contract check, scaffold idempotence and the secret scanner.

Bugs that properties caught, with the commit that fixed each:
- `e29afaf` fix(ledger): LED-P15 found a tiny overspend accepted as feasible; the LP budget row is now scaled by reachable cost.
- `54f8886` fix(brain): BRN-P4 (same request, same briefing) failed because caveat references followed the order in which concurrent organ calls finished.
- `93e2dc8` fix(brain): BRN-P6 showed a test mutator was wrong, not the conflict rule.
- `322ab40` fix(voice): VOX-P2 (normalization is idempotent) found that a second pass deleted spoken words joined by a slash.
- `944e343` fix(eyes): EYE-P5 (mask agreement of reduced-precision exports) decides the shipped precision.
- `075b7e3` fix(ledger): found by the seeded eval, not the properties (see below).

The sections below give the details per organ.

### Ledger: what the properties caught, and what they missed

The ledger spec lists properties LED-P1 to P19 in `design.md` section 7; task 16 added P20 (shadow prices are exact on their allowable range). They live in `organs/ledger/tests/property/` (32 `@given` tests) on shared strategies in `tests/strategies.py` (1 to 12 districts, 1 to 4 commodities, edge cases such as zero population, access just below the threshold, zero supply, tiny budgets). The full Ledger suite runs about 180 tests in about 2 minutes under `ci`.

Found by the properties and kept as named tests in `organs/ledger/tests/unit/test_regressions.py`:
- P15: a floor of about 1e-9 written as a row was satisfied by GLOP within tolerance with nothing allocated. Fix: the floor became an exact variable bound in a scale-free form (`x = R f`).
- P15 and P12: subnormal severities and a need of 1e-38 made GLOP return `ABNORMAL`. Fix: objective and rows are scaled by their largest coefficient and negligible coefficients dropped.
- P3: the budget repair removed free goods to fix a 1e-83 overshoot. Fix: only paid items are scaled.
- P13: GLOP presolve returned `ABNORMAL` on a budget row with right-hand side 1e-9. Fix: retry without presolve.
- P10 and P13 (found while finishing task 12): with budgets near 1e-3, GLOP returns coverage 0 where the baseline has 2e-5. That is 1e-9 of the objective scale, inside the solver's tolerance. This was a test tolerance problem, not a solver bug: the tolerance is now relative to `sum_d w_d`, and both cases are regression tests that say so.
- P18 surfaced a spec conflict (integer rounding can send up to one unit more than a road-denied district's air/boat capacity). The owner resolved it by amending LED-R1.6 and P18.

Missed by the properties and found by the seeded eval (`evals/ledger`, 200 instances up to 200 districts): SCIP reported an all-zero plan as optimal on a 100-district problem with needs around 1.9e7 (varbound upgrade numerics), and the integer budget repair broke the equity floor by one unit. The property strategies stop at 12 districts and small populations, so neither shape was generated. Both are fixed (a rounded-LP guard with a safer retry, and floor-aware batched repairs) with regression tests. The lesson: the properties are strong on small instances and numerically extreme inputs, but they did not cover realistic sizes, so the eval is a necessary second check.

### Oracle: properties, the eval, and what they did not prove

The oracle spec lists ORA-P1 to P8 and extras X1 to X10 (`.kiro/specs/oracle-mcp/design.md` section 11). Each maps to a test in `organs/oracle/tests/` (17 `@given` tests on shared strategies in `tests/strategies.py`, plus unit tests; about 160 tests in under a minute with sockets blocked). P1 to P3 run on random quantile triples and score arrays through the repair and the conformal step; P4 and P5 run the whole forecast pipeline on a fast stub model, with shuffled input rows and with every row after `as_of` perturbed or deleted; P6 checks the exceedance CDF on random knots including zero-width ones; P8 is a contract test plus a wording lint over the sources, tool descriptions and docs.

What the work showed:
- The design's small-sample fallback multiplies the conformal score quantile by `1 + 1/sqrt(n)`. For coverage below 0.8 that quantile is negative, so multiplying would narrow the interval. The code adds `|Q|/sqrt(n)` instead, and a property test checks that the fallback widens and keeps nesting (P3). This was caught while writing the property, before any run, so it is a design fix rather than a found failure.
- The eval's lead-widening check (ORA-R5.1) failed on the mean of the relative interval width, while the mean width in m³/s grows at every lead. Dry-season rows at Kotri, with medians near 0 m³/s, dominate a mean of ratios. The check now uses the mean width and the median relative width, and the report keeps the failing measure visible.
- The properties prove the interval is ordered, nested and leak-free. They say nothing about coverage on real floods. The eval does: test coverage of the 0.8 interval is 0.790, but on the 2022 flood season it is 0.706, and at lead 14 in that season the model is worse than climatology. Both numbers are in the model card and `docs/oracle-model.md`, and nothing was tuned on them.
- The data build found that the Open-Meteo Flood API returns no values before 1997 at these cells although its docs say 1984. The splits were moved and the decision logged in `docs/decisions.md`.
- No observed (gauge) validation exists. The target is modeled GloFAS discharge, and the eval reports `observed_validation: "not performed"`.

### Voice: a time-boxed, cuttable organ

The voice spec was written as the first thing to cut: a capped budget, a go/no-go checkpoint and three cut paths (prerendered only, speak only, disabled) decided by configuration rather than code. Midway the owner switched the hosted vendor from Azure to Deepgram, which the spec took as revision R-DG. Deepgram Aura-2 has no Urdu voice and Urdu is never read by an English voice, so Stitch provides English speech only; Urdu text is experimental.

What the work showed:
- Of the five properties, two found real bugs. VOX-P2 (normalization is idempotent) failed on `m3/s/data/forecast/3/p50` in Urdu: the second pass read the spelled-out words joined by `/` as a JSON pointer and deleted them. The spoken form now never contains a slash, and the example is a regression test. The VOX-P3 test failed on Windows because the budget store's `with sqlite3.connect(...)` never closed the connection, which kept the cache directory locked. VOX-P1, P4 and P5 passed on the first run.
- The tests never touch the network. Deepgram and Azure run against httpx mock transports. Separate tests marked `live` call the real Deepgram API by hand. The live round trip turned "Indus at Kotri" into "Indusic co tree" on 2026-11-17 and into "The indecent cotries" on 2026-11-18, so that test can fail on place names while the rest of the sentence is right.
- The eval's English round trip (Aura-2 then Nova-3, sentences of the demo script, seed 0) gave a WER of 0.087 on the 3-sentence fast set and 0.132 on 12 sentences, against a target of 0.15. It is an internal intelligibility check, not a vendor benchmark (Deepgram terms 2.4(i)). Urdu WER is `not_run`.
- Generated audio is not committed. Deepgram's terms (re-read 2026-11-17) give no clear right to redistribute it, so `scripts/prerender_voice.py` renders the demo script into a git-ignored cache at deploy time.
- In production the full read-aloud ran to 6 minutes and over 32 MiB of audio, which broke the MCP event size limit (`e58510b`). The spoken briefing is now a summary of about 1,500 characters (`6f0c8d9`), and Deepgram chunks are synthesized four at a time (`dfb0197`).
- Not done: the Whisper real-time-factor measurement and the go/no-go checkpoint document (voice tasks 6 and 11).

### Library: verify before return, and a corpus that decides what can be answered

The Library returns an answer only after every claim has been checked against the stored page text: each claim must resolve to numbered sentences that were in the prompt, its quote must be a verbatim span of the page, and its numbers must appear in the cited sentence. Claims that fail are dropped, and an answer with no surviving claim becomes a refusal. The same check runs on LLM replies (live or replayed) and on the extractive fallback, so the deterministic demo and a hosted model go through one gate. Refusal thresholds are calibrated on a dev split and the headline numbers come from a separate test split; the split is locked by a hash (LIB-P12).

What the work showed:
- The demo briefing's guidance section was `partial` in production because four of the six questions the Brain asks (food and shelter, English and Urdu) were refused. The cause was the corpus, not the code: the committed FEMA and EPA pages are household advice and contain no ration or shelter standard for displaced people. The fix was a new public-domain source, an excerpt of the USAID/OFDA *Field Operations Guide* v4.0 (2,100 kcal per person per day, 3.5 m² covered space per person), with license evidence in the manifest and an AI-assisted Urdu translation that is not native-reviewed. All six demo questions now answer with verbatim citations from Nebius (Qwen3-235B) recordings that replay offline.
- The source that would have been easiest to add, the FOG's inside cover, also says 15 litres per person per day. Next to FEMA's one gallon (3.8 litres) that would have turned the water answer into a CONFLICTING_EVIDENCE refusal. It was left out on purpose and the reason is logged. The disagreement still shows in the briefing, where the Brain's R3 rule flags it against the Ledger's 10-litre planning assumption.
- One recorded Urdu reply refused the food question because the translator's note was the first sentence of the page and was all the model saw. Moving the note to the end of the page fixed it. Small layout choices in a text rendition change what the model reads.
- Relabelling three eval questions as answerable after the corpus grew would have moved two questions between dev and test under the split rule. Each relabelled question now keeps its frozen labels for the split, and one new unanswerable test question keeps the count at 10.
- Numbers on the committed corpus, test split of 31 questions: citation validity 1.00, citation accuracy 0.976, answer rate 0.70 with the replay (0.75 with one live Nebius run), refusal rate 0.91, recall@8 0.90. Urdu is weaker (answer rate 0.60, recall@3 0.70), and the one false answer is a fetch-tier question about container counts answered with the one-gallon storage sentence.
- Not done: no native Urdu review (Urdu is experimental), no owner confirmation of the license rows (`owner_confirmed: false` everywhere), and no measurement in the 2 vCPU container (laptop latency only).

### Brain: properties as the spec of an orchestrator

The brain spec lists BRN-P1 to P7 in `requirements.md`; the design added P8 to P24 (`.kiro/specs/brain/design.md` section 19, summarized in `docs/brain-design.md` section 15). They run against the pure `core/` modules and against whole runs on recorded organs with a virtual clock, so the 339-test suite takes about two minutes with sockets blocked. The executor, critic and degradation matrix are all exercised in virtual time; a run where an organ hangs until the 45 s deadline costs milliseconds.

What the work showed:
- BRN-P4 (same request, same briefing) failed under random per-node delays: caveat refs followed the order in which concurrent calls finished. Rendering now reads evidence in a canonical order, and the two shrunk cases are named regression tests.
- BRN-P6 (seeded conflicts are always flagged) failed on a combined scenario. The mutator had dried a district that carried most of the basin's flood area, so R1 correctly stopped firing: the expectation was wrong, not the rule. The mutator now keeps the basin fraction above the R1 threshold, and the reasoning is in `docs/decisions.md`.
- BRN-P2 (an adversarial `MutatingLLM`) found three rewrites the number check accepted before any real model was used: a slot rounded to zero (0.20 written as 0), one of two equal numbers dropped, and Sentinel-1 swapped for Sentinel-2 behind the term mask. Slots now need distinct tokens, fewer decimals are accepted only without loss, and masked terms and identifiers must survive a rewrite.
- The properties did not catch everything. Contract tests over HTTP found that `/ask` stripped `null` fields the Library contract requires, and that a malformed evidence pointer gave a 500. The first Nebius recording run found that the shared adapter sent a bare schema, which Nebius rejects with 422 (`fa28021`), so every structured call had been falling back to template text without failing a test. The recording check (`test_demo_recordings_current`) now makes a silent fallback a test failure for the demo prompts.
- The number guard rejects a correct Urdu translation: `ایک` is both the article "a" and the word "one". The briefing shows that Library sentence in English with a caveat. The check stays strict because a false acceptance could change a ration quantity.
- The eval's verifier (`evals/brain/verify.py`) is a second implementation that shares no code with the Brain. Faithfulness 1.00 over 472 claims means the two agree; a test feeds it corrupted claims to show it can disagree.

## Hooks

Five hooks in `.kiro/hooks/` (format `v1`, validated by `tests/test_hooks.py`):

| Hook | Trigger | Action |
|---|---|---|
| `on-save-organ-tests` | `PostFileSave` on any `organs/<x>/**.py` | `scripts/hooks/run_organ_tests.py`: that organ's unit and property tests, `dev` profile |
| `on-save-contract-validate` | `PostFileSave` on an organ's `server.py` or `models.py`, any `packages/stitch_common` file, or `mcp-contracts.md` | `scripts/hooks/on_save_contracts.py`: the contract check |
| `on-save-eval-dashboard` | `PostFileSave` on `organs/**.py` or `evals/**.py` | `scripts/hooks/on_save_eval.py`: the fast eval subset, refreshes `evals/results/latest.json` |
| `on-spec-change-tasks` | `PostFileSave` on a spec's `requirements.md` or `design.md` | agent action: regenerate that spec's `tasks.md`, keeping completed checkboxes |
| `pre-commit-lint-secrets` | `PreToolUse` on the shell tool | `scripts/hooks/pre_commit_guard.py`: for `git commit` only, ruff on staged files and the secret scan; exit code 2 blocks the commit |

The command hooks fire in the IDE. `scripts/hooks/hook_io.py` writes the last payload of each to the git-ignored `.stitch-hook-debug/`; those files show `PostFileSave` events with a `file_path` key (on-save-eval and run-organ-tests on 2026-11-18, on-save-contracts on 2026-11-17) and `PreToolUse` events with `tool_name` and `tool_input` for every shell call. A git `pre-commit` hook (`scripts/install_git_hooks.py`) runs the same guard for commits made outside the agent. The agent hook `on-spec-change-tasks` left no trace that it fired.

## The `surgeon` custom agent

`.kiro/agents/surgeon.md` defines an agent that scaffolds a new organ. Its tools are limited to read, write and shell; shell is allowed only for `scripts/scaffold_organ.py`, the contract check, pytest and `uv sync`, and writes only under `organs/**`, `.kiro/specs/**` and `.kiro/settings/mcp.json`. It renders `.kiro/templates/organ/` through `scripts/scaffold_organ.py`: `pyproject.toml`, `src/stitch_<organ>/` with `core/`, `server.py` and `models.py`, contract, property, unit and stdio smoke tests, a README and a THIRD_PARTY section. `tests/test_scaffold.py` scaffolds a throwaway organ and runs its generated tests.

All five organs have the generated layout (for example each has `tests/test_smoke_stdio.py`). The commits for Ledger (`942acaf`), Oracle (`3477274`), Library (`cc60041`) and Voice (`5ccc03d`) name the template; for Ledger and Library the script was run directly rather than through the agent. The agent appears in the IDE's agent list.

## MCP

`.kiro/settings/mcp.json` registers eight servers: the five organs over stdio (`uv run --package stitch-<organ> python -m stitch_<organ>.server --stdio`, demo mode), `filesystem` (`@modelcontextprotocol/server-filesystem`), `fetch` (`mcp-server-fetch`) and `github` (the GitHub MCP endpoint with `${GITHUB_TOKEN}`, no literal secret). `oracle-mcp`, `library-mcp`, `ledger-mcp` and `voice-mcp` are enabled, and their tools (`forecast_river`, `answer_with_citations`, `optimize_allocation`, `speak` and the rest) are available to the agent in the IDE, so the agent could call the organs it was building. `eyes-mcp` and `github` are disabled in the file. `scripts/mcp_probe.py` starts a server from a config and sends `initialize` over stdio; `deploy/bin/check_repo_hygiene.py` fails if the file contains a credential.

In Docker Compose the same organ servers run over streamable HTTP, and the Brain is their MCP client.

## Powers

Not used. No Power was installed (the user-level Powers directory holds only the registry list), and nothing in the repository depends on one.

## Kiro IDE and Kiro CLI

All work was done in the Kiro IDE, by the main agent and by agent sub-tasks for separate parts (for example organs and frontend work running in parallel). `kiro-cli` was not installed on the dev laptop, so headless or scripted Kiro runs are not demonstrated. CI runs the same checks the hooks run (`.github/workflows/ci.yml`), without Kiro.

## Evals and CI

`python -m evals.run --organ <name|all> [--fast] [--seed N]` writes `evals/results/<organ>.json` and `latest.json`, which the frontend's Heartbeat page reads. Evals are deterministic with fixed seeds and the fake LLM unless `--live-llm` is passed. `.github/workflows/ci.yml` has jobs for hygiene, Python (lint, types, tests, contracts), eval smoke, frontend (types drift, lint, Vitest, build budget, Playwright), images and an offline stack smoke; a test parses the workflow and checks it.

## What worked and what didn't

What worked:
- **Specs before code.** Writing EARS requirements and properties first made review concrete. The Ledger equity-floor rework and the Deepgram revision were changes to requirement text, reviewed before code changed.
- **Properties with IDs.** A property name in a spec maps to one test, so a failing test points to a requirement. Shrunk failures became named regression tests.
- **Small commits.** Committing after each step meant an interrupted run lost little work, and `fix(...)` commits name the property or incident behind them.
- **Demo-first with recorded LLM replies.** The fake LLM replays recorded Nebius replies, so the offline demo and CI are deterministic and the same verification gate runs on live and replayed text.
- **The organs as MCP tools inside the IDE.** The agent could call the Ledger or Library while writing the Brain.

What didn't:
- **Long parallel agent runs were cancelled.** Several large runs stopped partway; the repository has eleven `wip(...)` commits from interrupted runs (Eyes, Oracle, Library, Voice, Brain, frontend, deployment). Each was finished in a later, smaller run. Shorter tasks with a commit at the end of each worked better.
- **Properties stopped at small sizes.** The Ledger strategies generated at most 12 districts, so two solver bugs at realistic sizes were found by the seeded eval instead.
- **Some failures were invisible to tests.** The Nebius 422 was hidden by the template fallback until a recording check made fallbacks fail the test, and the production speech size limit only showed up on the live site.
- **A stale test.** `tests/test_check_contracts.py` assumed contract version 0.5 had no change-log entry, which stopped being true when the contract reached v0.5; it was fixed in the final audit (`6734b4a`).
- **Not demonstrated:** Powers, Kiro CLI, and a recorded firing of the agent-type hook.
