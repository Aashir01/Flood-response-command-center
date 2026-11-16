# bootstrap: Tasks

Target: about half a day. Do first. `core` unless marked.

- [x] **1. uv workspace and tooling** `core`
  - Root `pyproject.toml` (workspace members `packages/*`, `organs/*`), `.python-version` 3.12, ruff, mypy, pytest config, `uv.lock`.
  - Done when: `uv sync` works and `uv run ruff check` and `uv run pytest` run on the empty workspace. Refs: BOOT-R1.

- [x] **2. `stitch_common` core types and envelope** `core`
  - `types.py`, `envelope.py`, `provenance.py`, `version.py`, `logging.py`.
  - Tests: P1 (envelope invariant), P2 (hash canonical), P3 (Interval ordering, Hypothesis). Refs: BOOT-R2.1 to R2.3, R2.5.

- [x] **3. Organ and Brain models** `core`
  - Models for all five organs (v0.3 contracts) and Brain `Briefing`, `Claim`, `Conflict`, `TaskEvent`.
  - Tests: construct each from a valid fixture, reject unknown fields, P4 round trip through exported schema. Refs: BOOT-R2.1.

- [x] **4. Testing plugin** `core`
  - `no_network` autouse, `allow_loopback` marker, Hypothesis profiles `dev` and `ci`, registered through the `pytest11` entry point. Verify on Windows with a stdio subprocess test.
  - Done when: a test that opens an outbound socket fails, a stdio pipe test passes. Refs: BOOT-R2.4.

- [x] **5. Schema export and contract checker** `core`
  - `export_schemas.py`, `contracts.lock.json`, `check_contracts.py` with `--update`.
  - Tests: P5 (clean tree passes, deliberate schema edit fails, version mismatch fails). Refs: BOOT-R3.
  - Also: fix the change-log order in `mcp-contracts.md` (0.1, 0.2, 0.3 ascending) if the check requires it.

- [x] **6. Secret scanner and git pre-commit** `core`
  - `secret_scan.py` with ruleset and fixtures (positive and clean). `install_git_hooks.py`, `git-pre-commit`, `pre_commit_guard.py`.
  - Tests: P7. Refs: BOOT-R6.3, R6.4.

- [x] **7. Surgeon template and scaffold script** `core`
  - `.kiro/templates/organ/**`, `scaffold_organ.py` (`--dry-run`, `--force`, idempotent, flips `mcp.json`).
  - Tests: P6, scaffold a throwaway organ into a temp copy and run its generated tests and `check_contracts.py`. Refs: BOOT-R5.2 to R5.5.

- [x] **8. Surgeon agent definition** `core`
  - `.kiro/agents/surgeon.md` per the design. Verify the file loads in the IDE (agent list) and, if the CLI is installed, `kiro-cli chat --v3 --agent surgeon --no-interactive`.
  - Done when: the agent appears in Kiro and a dry run through it lists the planned files. Refs: BOOT-R5.1, R5.6.

- [x] **9. Hooks** `core`
  - Five hook JSON files, `hook_io.py` and the four helper scripts. Log the first real payload to `.kiro/hooks/.last-event.json`-style debug output (git-ignored path) to learn the shape.
  - Done when: each hook is visible in the Kiro hooks panel, and each script runs by hand. Refs: BOOT-R6.

- [ ] **10. `mcp.json`** `core`
  - Register the eight servers per the design. Verify `filesystem` and `fetch` start from the IDE MCP panel. Keep organ servers and GitHub disabled until they exist.
  - Done when: no secrets in the file and the enabled servers show as connected. Refs: BOOT-R4.

- [x] **11. Eval runner skeleton** `core`
  - `evals/run.py`, `schema.json`, `MetricResult`, merge to `latest.json`.
  - Tests: missing organ is `not_run`, output validates against the schema. Refs: BOOT-R7.

- [x] **12. Minimal CI** `core`
  - `.github/workflows/ci.yml` per the design. Refs: BOOT-R8.

- [ ] **13. Write-up skeleton and schedule** `core`
  - `docs/kiro-writeup.md` sections with the verified facts so far; `docs/schedule.md` (calendar to Dec 3). Refs: BOOT-R9.

- [ ] **14. Powers** `human-assisted`
  - Owner installs relevant Powers in the IDE Powers panel (testing, deployment, databases) and notes which. Assistant records them in the write-up. Refs: BOOT-R10.

- [ ] **15. Install Kiro CLI** `human-assisted`
  - Owner installs `kiro-cli` and a `KIRO_API_KEY` (needs a Pro or higher plan per the docs) to evidence scripted tasks. If not possible, the write-up states CLI usage as not demonstrated.

## Traceability

| Requirement | Tasks |
|---|---|
| BOOT-R1 | 1 |
| BOOT-R2 | 2, 3, 4 |
| BOOT-R3 | 5 |
| BOOT-R4 | 10 |
| BOOT-R5 | 7, 8 |
| BOOT-R6 | 6, 9 |
| BOOT-R7 | 11 |
| BOOT-R8 | 12 |
| BOOT-R9 | 13 |
| BOOT-R10 | 14 |

Properties: P1 to P3 in task 2, P4 in task 3, P5 in task 5, P6 in task 7, P7 in task 6.
