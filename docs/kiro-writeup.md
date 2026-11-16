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
