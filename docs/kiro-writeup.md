# Kiro write-up

Running log of how Stitch uses each Kiro feature. Only facts that were checked are stated as facts. Anything not yet shown says so.

## Verified facts so far

- Hooks use format `v1`: `.kiro/hooks/<kebab-name>.json` holding `{"version": "v1", "hooks": [...]}`. Each hook has `name`, `description`, `trigger`, `matcher`, `timeout`, `enabled` and an `action` of type `command` or `agent`. A test (`tests/test_hooks.py`) validates every file against this shape.
- File-save triggers (`PostFileSave`, `PostFileCreate`, `PostFileDelete`) fire for edits made by the agent, not for manual editor saves. This comes from the Kiro docs; it is not yet observed here.
- A `PreToolUse` command hook that exits with code 2 blocks the tool call. An agent-type hook cannot block.
- The stdin key that carries the saved path is undocumented. `scripts/hooks/hook_io.py` scans the payload for path-like strings and writes the raw payload to `.stitch-hook-debug/` (git-ignored). The first real event should be read there and the real key hard-coded.
- `kiro-cli` is not installed on the dev laptop. Nothing in this repo has been run through the CLI.
- `.kiro/` is tracked in git and must never be listed in `.gitignore`. CI fails if `git check-ignore .kiro` succeeds or if no `.kiro` file is tracked.
- Writes to `.kiro/settings/` are denied to the implementing agent by a Kiro permission rule in this environment, so `.kiro/settings/mcp.json` has to be created by the owner or from the IDE (see MCP below).
- MCP Python SDK 2.3.0 is used (`mcp.Client`). From Python, a bare `npx` command starts the filesystem server on Windows without `cmd /c`; the Kiro IDE launcher was not tested.

## Steering

Six files in `.kiro/steering/` (`product`, `tech`, `structure`, `testing`, `ui-style`, `mcp-contracts`). The contract file is human documentation. The machine contract is the Pydantic models in `stitch_common` and `packages/stitch_common/contracts.lock.json`; `scripts/check_contracts.py` checks only the version and the change log of the markdown file. Not yet demonstrated: measured effect of steering on agent output.

## Specs

One spec per component under `.kiro/specs/<name>/` (requirements, design, tasks). Bootstrap tasks 1 to 9 and 11 to 13 are done; task 10 (`mcp.json`) is blocked on the permission rule noted above; tasks are ticked in `tasks.md` as they finish. The `on-spec-change-tasks` agent hook is meant to regenerate `tasks.md` when requirements or design change. It has not fired yet.

## Property tests

Hypothesis tests for BOOT-P1 to P7: envelope invariant, canonical `inputs_hash`, `Interval` ordering, schema round trip, contract check on a clean and a deliberately changed tree, scaffold idempotence, secret scanner fixtures. The pytest plugin in `stitch_common.testing` blocks outbound network (a Windows-safe guard, because `pytest-socket` breaks asyncio's `socketpair` on Windows) and registers the Hypothesis profiles `dev` (30 examples) and `ci` (200).

### Ledger: what the properties caught, and what they missed

The ledger spec lists properties LED-P1 to P19 in `design.md` section 7; task 16 added P20 (shadow prices are exact on their allowable range). They live in `organs/ledger/tests/property/` (32 `@given` tests) on shared strategies in `tests/strategies.py` (1 to 12 districts, 1 to 4 commodities, edge cases such as zero population, access just below the threshold, zero supply, tiny budgets). The full Ledger suite runs about 180 tests in about 2 minutes under `ci`.

Found by the properties and kept as named tests in `organs/ledger/tests/unit/test_regressions.py`:
- P15: a floor of about 1e-9 written as a row was satisfied by GLOP within tolerance with nothing allocated. Fix: the floor became an exact variable bound in a scale-free form (`x = R f`).
- P15 and P12: subnormal severities and a need of 1e-38 made GLOP return `ABNORMAL`. Fix: objective and rows are scaled by their largest coefficient and negligible coefficients dropped.
- P3: the budget repair removed free goods to fix a 1e-83 overshoot. Fix: only paid items are scaled.
- P13: GLOP presolve returned `ABNORMAL` on a budget row with right-hand side 1e-9. Fix: retry without presolve.
- P10 and P13 (found while finishing task 12): with budgets near 1e-3, GLOP returns coverage 0 where the baseline has 2e-5. That is 1e-9 of the objective scale, inside the solver's tolerance. This was a test tolerance problem, not a solver bug: the tolerance is now relative to `sum_d w_d`, and both cases are regression tests that say so.
- P18 surfaced a spec conflict (integer rounding can send up to one unit more than a road-denied district's air/boat capacity). The owner resolved it by amending LED-R1.6 and P18.

Missed by the properties and found by the seeded eval (`evals/ledger`, 200 instances up to 200 districts): SCIP reported an all-zero plan as optimal on a 100-district problem with needs around 1.9e7 (varbound upgrade numerics), and the integer budget repair broke the equity floor by one unit. The property strategies stop at 12 districts and small populations, so neither shape was generated. Both are fixed (a rounded-LP guard with a safer retry, and floor-aware batched repairs) with regression tests. The honest lesson: the properties are strong on small instances and numerically extreme inputs, but they did not cover realistic sizes, so the eval is a necessary second check rather than a formality.

### Oracle: properties, the eval, and what they did not prove

The oracle spec lists ORA-P1 to P8 and extras X1 to X10 (`.kiro/specs/oracle-mcp/design.md` section 11). Each maps to a test in `organs/oracle/tests/` (17 `@given` tests on shared strategies in `tests/strategies.py`, plus unit tests; about 160 tests in under a minute with sockets blocked). P1 to P3 run on random quantile triples and score arrays through the repair and the conformal step; P4 and P5 run the whole forecast pipeline on a fast stub model, with shuffled input rows and with every row after `as_of` perturbed or deleted; P6 checks the exceedance CDF on random knots including zero-width ones; P8 is a contract test plus a wording lint over the sources, tool descriptions and docs.

What the work showed:
- The design's small-sample fallback multiplies the conformal score quantile by `1 + 1/sqrt(n)`. For coverage below 0.8 that quantile is negative, so multiplying would narrow the interval. The code adds `|Q|/sqrt(n)` instead, and a property test checks that the fallback widens and keeps nesting (P3). This was caught while writing the property, before any run, so it is a design fix rather than a found failure.
- The eval's lead-widening check (ORA-R5.1) failed on the mean of the relative interval width, while the mean width in m³/s grows at every lead. Dry-season rows at Kotri, with medians near 0 m³/s, dominate a mean of ratios. The check now uses the mean width and the median relative width, and the report keeps the failing measure visible.
- The properties prove the interval is ordered, nested and leak-free. They say nothing about coverage on real floods. The eval does: test coverage of the 0.8 interval is 0.790, but on the 2022 flood season it is 0.706, and at lead 14 in that season the model is worse than climatology. Both numbers are in the model card and `docs/oracle-model.md`, and nothing was tuned on them.
- The data build found that the Open-Meteo Flood API returns no values before 1997 at these cells although its docs say 1984. The splits were moved and the decision logged in `docs/decisions.md`.
- No observed (gauge) validation exists. The target is modeled GloFAS discharge, and the eval reports `observed_validation: "not performed"`.

### Voice: a time-boxed, cuttable organ
The voice spec was written as the first thing to cut: a capped budget, a go/no-go checkpoint and three cut paths (prerendered only, speak only, disabled) decided by configuration rather than code. Midway the owner switched the hosted vendor from Azure to Deepgram. The spec took that as revision R-DG (VOX-R10.1 to R10.5) instead of a silent rewrite, and the decisions log records the consequences: Deepgram Aura-2 has no Urdu voice, so Urdu speech still needs Azure, and Urdu is never read by an English voice.
What the work showed:
- Of the five properties, two found real bugs. VOX-P2 (normalization is idempotent) failed on `m3/s/data/forecast/3/p50` in Urdu: the second pass read the spelled-out words joined by `/` as a JSON pointer and deleted them. The spoken form now never contains a slash, and the example is a regression test. The VOX-P3 test failed on Windows because the budget store's `with sqlite3.connect(...)` never closed the connection, which kept the cache directory locked. VOX-P1, P4 and P5 passed on the first run.
- The tests never touch the network. Deepgram and Azure run against httpx mock transports. Separate tests marked `live` called the real Deepgram API once (2026-11-17) and passed: English round trip, automatic language detection, and the Urdu refusal. The live round trip turned "Indus at Kotri" into "Indusic co tree". Place names are the weak spot.
- The eval's English round trip (Aura-2 then Nova-3, sentences of the demo script, seed 0) gave a WER of 0.087 on the 3-sentence fast set and 0.132 on 12 sentences, against a target of 0.15. It is an internal intelligibility check, not a vendor benchmark (Deepgram terms 2.4(i)). Urdu WER is `not_run`: the owner recordings do not exist yet, and an Urdu round trip needs Azure.
- Generated audio is not committed. Deepgram's terms (re-read 2026-11-17) give no clear right to redistribute it, so `scripts/prerender_voice.py` renders the demo script into a git-ignored cache at deploy time. The English demo script turns into 6.7 minutes of WAV (about 19 MB). Shortening it would be a Brain change.
- Not done: Azure was never called with a real key, so the Urdu speech path is tested only against mocks. The Whisper real-time-factor measurement and the go/no-go checkpoint (tasks 6 and 11) are still open.
## Hooks

Five hooks in `.kiro/hooks/`: `on-save-organ-tests`, `on-save-contract-validate`, `on-spec-change-tasks` (agent action), `on-save-eval-dashboard`, `pre-commit-lint-secrets` (PreToolUse on `shell`, runs only for `git commit`). Each script was run by hand and tested. Not verified: that the Kiro hooks panel loads the files and that the events fire. A git `pre-commit` hook (`scripts/install_git_hooks.py`) runs the same guard for manual commits.

## Surgeon

`.kiro/agents/surgeon.md` plus `.kiro/templates/organ/` and `scripts/scaffold_organ.py`. The script is covered by tests that scaffold a throwaway organ and run its generated tests. Not verified: that the agent appears in the Kiro agent list and completes a dry run in the IDE.

## MCP

Intended servers: five organ servers (disabled until built), `github` (disabled until `GITHUB_TOKEN` is set), `filesystem` and `fetch`. `scripts/mcp_probe.py` starts each server from a config and sends `initialize` over stdio. Results on this laptop (Windows, Node 24, uv): `npx -y @modelcontextprotocol/server-filesystem .` answered as `secure-filesystem-server 2.3.0` (also with `cmd /c`); `uvx mcp-server-fetch` answered as `mcp-fetch 2026.11.11`. Not verified: that the IDE MCP panel shows them as connected, and `.kiro/settings/mcp.json` itself (blocked, see above).

## Powers

Pending (task 14, owner action). The owner installs relevant Powers (testing, deployment, databases) in the IDE Powers panel. This section will list which ones and how each was used, or state that none was relevant.

## IDE vs CLI

All work so far ran through the IDE agent. The CLI is not installed (task 15, owner action; needs `KIRO_API_KEY` and a Pro or higher plan per the docs). Until then scripted or headless use of Kiro is not demonstrated, and the write-up must say so.

## Evals and CI

`python -m evals.run --organ <name> [--fast] [--seed N]` writes `evals/results/<organ>.json` and `latest.json`; organs without an `evals/<organ>/` module report `not_run`. Only `schema.json` is committed. `.github/workflows/ci.yml` is parsed and checked by a test; it has not run on GitHub.
