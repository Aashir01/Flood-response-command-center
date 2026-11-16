# bootstrap: Requirements

The shared foundation built before any organ. Prefix `BOOT`. Target: about half a day. Hooks and the `surgeon` agent are visible Kiro features, so they are built first.

## Introduction
Bootstrap delivers the uv workspace, `stitch_common` (contract models, envelope, provenance, test helpers), contract checking, `mcp.json`, the `surgeon` custom agent and its organ template, five hooks, a git pre-commit scan, an eval-runner skeleton with a results schema, minimal CI, and the write-up skeleton.

## Requirements

### BOOT-R1 Workspace
1. THE repo SHALL be a uv workspace with a root `pyproject.toml` listing `packages/*` and `organs/*` as members, Python pinned to 3.12 (`.python-version`), one root `uv.lock`, and shared ruff and mypy settings.
2. THE root SHALL provide `uv run` entry points or scripts for lint, type-check, and test.

### BOOT-R2 `stitch_common`
1. THE package SHALL define Pydantic v2 models for every shared type and every organ tool input and output in `mcp-contracts.md` (v0.3), plus Brain `Briefing`, `Claim`, `EvidenceRef`, and `TaskEvent`, all with `extra = "forbid"`.
2. THE package SHALL provide `ToolResult` constructors (`ok`, `fail`), a canonical-JSON `inputs_hash`, a `Provenance` builder, and a structured logger that never logs secrets.
3. THE package SHALL export `CONTRACT_VERSION` equal to the version in `mcp-contracts.md`.
4. THE package SHALL provide test helpers: the `no_network` autouse fixture (sockets disabled), shared Hypothesis profiles `dev` (30 examples) and `ci` (200 examples, deadline off), and fixtures that load schema files.
5. THE models SHALL enforce the invariants that can be expressed on a single object (e.g. `Interval` ordering `p10 <= p50 <= p90`, `Citation.page >= 1`, `ToolResult` consistency between `ok`, `data`, and `error`).

### BOOT-R3 Contract checking
1. THE repo SHALL export JSON Schemas for every tool input and output to `packages/stitch_common/schemas/` and keep a `contracts.lock.json` with a hash per schema and the `CONTRACT_VERSION`.
2. `scripts/check_contracts.py` SHALL fail when: a schema differs from the lock without an updated lock, `CONTRACT_VERSION` differs from the version heading in `mcp-contracts.md`, the change log lacks an entry for the current version, or a registered organ tool's input schema differs from the exported schema.
3. THE script SHALL offer `--update` to refresh the lock after an intentional contract change.
4. THE script SHALL exit non-zero with a readable diff, and zero when nothing is wrong.

### BOOT-R4 MCP configuration
1. `.kiro/settings/mcp.json` SHALL register the five organ servers (stdio via `uv run`), a GitHub server, a filesystem server limited to the repo, and a fetch server for data and docs lookups.
2. THE file SHALL contain no secrets and use `${VAR}` references only.
3. Organ servers whose code does not exist yet SHALL be `disabled: true`, and the `surgeon` scaffold SHALL enable an organ's entry when it creates the organ.

### BOOT-R5 `surgeon` custom agent
1. THE repo SHALL contain `.kiro/agents/surgeon.md` defining an agent that scaffolds a new organ from a template, usable from Kiro IDE and Kiro CLI.
2. THE template under `.kiro/templates/organ/` SHALL generate: package skeleton, MCP server stub with `/healthz`, models importing from `stitch_common`, tests (unit, property placeholder with the shared profiles, contract test), `README.md`, a spec skeleton (`requirements.md`, `design.md`, `tasks.md`) when none exists, a `THIRD_PARTY.md` section stub, and the `mcp.json` entry.
3. THE scaffold SHALL be performed by a deterministic script (`scripts/scaffold_organ.py`) that the agent invokes, so output is reproducible and testable.
4. THE script SHALL refuse to overwrite existing files unless `--force` is given, and SHALL support `--dry-run`.
5. THE scaffold SHALL produce a package that imports, passes its generated tests, and passes `check_contracts.py` immediately.
6. THE agent's permissions SHALL allow only the scaffold script, reads, and writes inside `organs/`, `.kiro/specs/`, and `.kiro/settings/`, and deny destructive shell commands.

### BOOT-R6 Hooks
1. THE repo SHALL contain Kiro hooks in `.kiro/hooks/*.json` (format `v1`) for:
   a. run the touched organ's tests (dev profile) on save;
   b. validate MCP schemas against the contracts on save;
   c. regenerate the spec's `tasks.md` when its `requirements.md` or `design.md` changes;
   d. refresh the eval dashboard results on save;
   e. lint and secret-scan before commit.
2. Hooks that run commands SHALL read the saved file path from the stdin event JSON, tolerate unknown payload shapes, and never fail the session on their own errors (warn, exit non-zero only to signal real failures).
3. THE pre-commit protection SHALL exist in two forms: a Kiro `PreToolUse` hook on shell commands that contain `git commit`, which blocks (exit 2) on lint or secret findings, and a real git `pre-commit` hook installed by `scripts/install_git_hooks.py`, so manual commits are covered.
4. THE secret scan SHALL be a local script with a documented ruleset (common key formats, private key headers, `.env` files), and CI SHALL additionally run gitleaks.
5. THE docs SHALL state the platform limit that file-save hooks fire only for agent edits, not for manual editor saves, and that the git hook is the safety net for manual work.

### BOOT-R7 Eval runner skeleton
1. THE repo SHALL provide `evals/run.py` (`python -m evals.run --organ <name> [--fast] [--seed N]`) that discovers `evals/<organ>/` modules, runs them, and writes `evals/results/<organ>.json` and `evals/results/latest.json`.
2. THE results SHALL follow a JSON Schema (`evals/results/schema.json`): metric id, label, value, target, unit, direction (higher or lower is better), dataset, `mode`, timestamp, git SHA, seed, and notes.
3. A missing organ eval SHALL be reported as `not_run`, not an error.

### BOOT-R8 Minimal CI
1. A GitHub Actions workflow SHALL run on push and PR: `uv sync`, ruff, mypy, pytest (CI profile, sockets disabled), `check_contracts.py`, and the secret scan, and SHALL fail if `.kiro/` is ignored by any `.gitignore` or not tracked.
2. THE full deployment pipeline is defined in the `deployment` spec.

### BOOT-R9 Write-up skeleton and Kiro feature log
1. THE repo SHALL contain `docs/kiro-writeup.md` with a section per Kiro feature (steering, specs, property tests, hooks, `surgeon`, MCP, powers, IDE vs CLI), filled in as features land.
2. THE doc SHALL record verified Kiro facts as they are learned (e.g. hook format `v1`, file-save hooks fire for agent edits only, CLI not installed on the dev laptop unless that changes).

### BOOT-R10 Powers (human-assisted)
1. THE owner SHALL install any available Powers relevant to testing, deployment, or databases through the IDE Powers panel, and the write-up SHALL list which were installed and how each was used.
2. IF no relevant Power exists, THEN THE write-up SHALL say so.

## Correctness properties (checked by tests and scripts)
- BOOT-P1: for every `ToolResult`, `ok = true` iff `data` is non-null and `error` is null.
- BOOT-P2: `inputs_hash` is invariant to JSON key order and differs for different inputs.
- BOOT-P3: every `Interval` that validates satisfies `p10 <= p50 <= p90` (Hypothesis).
- BOOT-P4: every exported schema validates the model's own `model_dump` output (round trip, Hypothesis where practical).
- BOOT-P5: `check_contracts.py` exits 0 on the committed tree and non-zero after a deliberate schema change without a lock update.
- BOOT-P6: scaffolding the same organ twice without `--force` changes nothing the second time.
- BOOT-P7: the secret scanner flags every sample key in its fixture set and none of the clean fixtures.

## Out of scope
Per-organ logic. Full deployment pipeline. LLM client (built in the library and brain specs).

## Decisions (resolved)
1. Build bootstrap first; target about half a day.
2. Hooks use Kiro's current `v1` format. The CLI is not installed on the dev laptop at the time of writing, so scripted-task evidence for the write-up needs the CLI installed (owner action) or is noted as IDE-only.
