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
