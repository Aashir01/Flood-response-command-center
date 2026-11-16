# bootstrap: Design

Implements `requirements.md` (BOOT-R1..R10).

## 1. Layout

```
pyproject.toml            uv workspace root, ruff, mypy, pytest config
.python-version           3.12
packages/stitch_common/
  pyproject.toml
  src/stitch_common/
    version.py            CONTRACT_VERSION
    envelope.py           ToolResult, ok(), fail(), ErrorInfo
    provenance.py         Provenance builder, inputs_hash (canonical JSON, sha256)
    types.py              Interval, Citation, EvidenceRef, GeoJSON aliases
    organs/{eyes,oracle,library,ledger,voice}.py   tool I/O models
    brain.py              Briefing, Claim, Conflict, TaskEvent
    logging.py            structlog-style JSON logger with secret redaction
    testing/              pytest plugin: no_network, hypothesis profiles, schema fixtures
    schemas/              exported *.json (committed)
  contracts.lock.json
  tests/
scripts/
  check_contracts.py
  export_schemas.py
  scaffold_organ.py
  secret_scan.py
  install_git_hooks.py
  hooks/run_organ_tests.py, on_save_contracts.py, on_save_eval.py, pre_commit_guard.py, hook_io.py
  hooks/git-pre-commit    (source copied to .git/hooks/pre-commit)
.kiro/
  agents/surgeon.md
  templates/organ/        template files with ${placeholders}
  hooks/*.json
  settings/mcp.json
evals/run.py, evals/results/schema.json
.github/workflows/ci.yml
docs/kiro-writeup.md
```

## 2. `stitch_common`

- Pydantic v2, `model_config = ConfigDict(extra="forbid", frozen=True)` on contract models. Field constraints use `Field(ge=, le=)`. Dates are `datetime.date` / `datetime.datetime` with UTC.
- `ToolResult[T]` is a generic model with a validator enforcing BOOT-P1. `ok(data, provenance, warnings)` and `fail(code, message, retryable, provenance)` are the only constructors tools use.
- `inputs_hash`: `sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))` over the Pydantic `model_dump(mode="json")`.
- Organ models mirror `mcp-contracts.md` literally. Where the contract uses a union or conditional invariant (`answered` vs `refused`, floor semantics), models use a `model_validator(mode="after")`.
- Schemas exported with `TypeAdapter(...).json_schema()` using stable ordering, one file per tool I/O: `ledger.optimize_allocation.in.json`, `.out.json`, and so on.
- Testing plugin registered through the `pytest11` entry point so every package gets `no_network` (via `pytest-socket`, `disable_socket(allow_unix_socket=True)` so stdio MCP tests that use pipes still work) and the Hypothesis profiles without per-package conftest code. Tests that need loopback sockets (HTTP smoke) use `@pytest.mark.allow_loopback`, which allows `127.0.0.1` only.

## 3. Contract checking

`check_contracts.py` steps:
1. Import `stitch_common`, regenerate schemas in memory.
2. Compare each to `contracts.lock.json` (hash per schema, version). Report added, removed, changed.
3. Parse the heading `# MCP contracts (vX.Y)` and the change log lines in `.kiro/steering/mcp-contracts.md`. Require `CONTRACT_VERSION` equality and a log entry starting `- X.Y`.
4. Import each organ package that exists and exposes `TOOL_SCHEMAS` (a dict from tool name to input schema, generated from the same `stitch_common` model). Require equality with the exported input schema.
5. Exit 1 with a unified diff on any failure. `--update` rewrites the lock and schema files after steps 3 and 4 pass.

The markdown file is human documentation, not machine-parsed beyond version and change log. This is stated plainly in the README so nobody assumes the prose is validated field by field. The Pydantic models and the lock are the machine contract.

## 4. Surgeon agent and template

`.kiro/agents/surgeon.md` (front matter in the current v1 agent schema):

```
---
name: surgeon
description: Scaffolds a new Stitch organ (MCP server, tests, spec skeleton) from the template.
tools: [read, write, shell]
includeMcpJson: false
resources: ["file://.kiro/steering/*.md", "file://.kiro/templates/organ/**"]
permissions:
  rules:
    - { capability: shell, match: ["uv run python scripts/scaffold_organ.py *", "uv run python scripts/check_contracts.py*", "uv run pytest*"], effect: allow }
    - { capability: fs_write, match: ["organs/**", ".kiro/specs/**", ".kiro/settings/mcp.json", "docs/**"], effect: allow }
    - { capability: shell, match: ["rm *", "del *", "git push*", "git reset*"], effect: deny }
---
```
The markdown body is the system prompt: read steering, ask for organ name and tool names, run `scaffold_organ.py --dry-run`, show the file list, run it for real, run the generated tests and `check_contracts.py`, report. The agent never hand-writes organ code that the script can generate.

`scaffold_organ.py --organ ledger --package stitch_ledger --tools optimize_allocation,sensitivity_report [--dry-run] [--force]`:
- Renders `.kiro/templates/organ/**` with `string.Template` (`${organ}`, `${package}`, `${tools}`, `${prefix}`), no network.
- Writes only under `organs/<organ>/` and `.kiro/specs/<spec>/` (skip existing), appends a `THIRD_PARTY.md` stub only if the section is missing, and flips `disabled` to `false` in the matching `mcp.json` entry (idempotent).
- Generated server: FastMCP app with each tool wired to a `NotImplemented` core function returning `fail(code="INTERNAL", ...)`, `/healthz`, `TOOL_SCHEMAS`, and a `main()` supporting stdio and HTTP.
- Generated tests: import test, healthz test, schema-equality test, a `hypothesis` placeholder that asserts the envelope invariant, all passing out of the box.

## 5. Hooks (Kiro `v1` format)

All are JSON files in `.kiro/hooks/`. Command hooks receive the event JSON on stdin. The exact key that carries the saved path is not documented, so `hook_io.py` extracts a path by scanning the payload for string values that look like repo paths (`file_path`, `path`, `filePath`, nested `tool_input.*`), normalizes to repo-relative, and falls back to "all organs" with a warning. This is logged so the real shape can be learned and hard-coded.

| File | Trigger | Matcher | Action |
|---|---|---|---|
| `on-save-organ-tests.json` | `PostFileSave` | `^organs/[^/]+/.*\.py$` | command: `uv run python scripts/hooks/run_organ_tests.py` (maps path to organ, runs `pytest organs/<o> -x -q` with the dev profile) |
| `on-save-contract-validate.json` | `PostFileSave` | `(^organs/[^/]+/src/.*/(server\|models)\.py$)\|(^packages/stitch_common/.*\.py$)\|(mcp-contracts\.md$)` | command: `uv run python scripts/check_contracts.py` |
| `on-spec-change-tasks.json` | `PostFileSave` | `^\.kiro/specs/[^/]+/(requirements\|design)\.md$` | agent: prompt to regenerate that spec's `tasks.md`, preserving completed checkboxes and IDs, and updating the traceability table |
| `on-save-eval-dashboard.json` | `PostFileSave` | `^(organs\|evals)/.*\.py$` | command: `uv run python scripts/hooks/on_save_eval.py` (fast eval for the touched organ, refreshes `evals/results/latest.json`) |
| `pre-commit-lint-secrets.json` | `PreToolUse` | `shell` | command: `uv run python scripts/hooks/pre_commit_guard.py`. Reads the tool input from stdin. Does nothing unless the command contains `git commit`. Runs ruff, then `secret_scan.py` on staged files. Exit 2 blocks the commit. |

Limits stated in the docs: file-save hooks fire only for agent edits (not manual editor saves). The agent-type hook cannot block. The git pre-commit hook (`scripts/hooks/git-pre-commit`, installed by `install_git_hooks.py`) runs the same guard and is the safety net for manual commits.

Timeouts: tests hook 120 s, contracts 30 s, eval 120 s, pre-commit 60 s.

## 6. `mcp.json`

```json
{
  "mcpServers": {
    "eyes-mcp":    { "command": "uv", "args": ["run", "--package", "stitch-eyes",    "python", "-m", "stitch_eyes.server",    "--stdio"], "env": {"STITCH_MODE": "demo"}, "disabled": true },
    "oracle-mcp":  { "...": "same pattern", "disabled": true },
    "library-mcp": { "...": "same pattern", "disabled": true },
    "ledger-mcp":  { "...": "same pattern", "disabled": true },
    "voice-mcp":   { "...": "same pattern", "disabled": true },
    "github":      { "url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}, "disabled": true },
    "filesystem":  { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."], "disabled": false },
    "fetch":       { "command": "uvx", "args": ["mcp-server-fetch"], "disabled": false }
  }
}
```
GitHub starts disabled until a token env var exists (the IDE needs the variable approved). On Windows, `npx` stdio servers may need `cmd /c`. The task verifies each enabled server starts, and adjusts the command if not.

## 7. Eval runner

`python -m evals.run --organ ledger --fast --seed 0`: imports `evals.ledger` if present and calls `run(fast: bool, seed: int) -> list[MetricResult]`. Each `MetricResult` is a Pydantic model that matches `evals/results/schema.json`. The runner merges per-organ files into `latest.json` (`{generated_at, git_sha, organs: {name: {status, metrics: [...]}}}`). Organs with no module report `status: "not_run"`.

## 8. CI

`.github/workflows/ci.yml`: checkout, `astral-sh/setup-uv`, `uv sync --all-packages --frozen`, ruff, mypy, `pytest -q --hypothesis-profile=ci`, `check_contracts.py`, `secret_scan.py --all`, gitleaks action, and the `.kiro` guard (`git check-ignore .kiro` must fail, `git ls-files .kiro` must be non-empty).

## 9. Risks

| Risk | Mitigation |
|---|---|
| Hook stdin payload shape unknown | tolerant extractor with logging; adjust after the first real event |
| File-save hooks do not fire on manual saves | document; git hook covers commits; scripts can also be run by hand and in CI |
| `pytest-socket` blocks stdio MCP pipes or the asyncio loop on Windows | allow unix sockets, test the plugin on Windows early; asyncio on Windows uses a socketpair, which `pytest-socket` can block, so the plugin allows localhost socketpair and blocks only external hosts if needed |
| uv workspace with many packages slows `uv sync` | install only needed packages in hooks via `--package` |
| Contract models drift from the markdown | version and change-log check, plus review discipline; stated plainly |
