---
inclusion: always
---

# Testing strategy

## Layers
| Layer | Tool | Scope |
|---|---|---|
| Unit | pytest | pure core modules |
| Property | Hypothesis | invariants listed per spec and below |
| Contract | pytest + JSON Schema | every tool's input and output validates against `mcp-contracts.md` schemas |
| Integration | pytest + docker compose (CI) | Brain driving real organ servers on demo data |
| UI smoke | Playwright | boot animation, run demo briefing, error state, RTL toggle, keyboard path |
| Evals | `evals/` harness | quality metrics, see below |

## Required properties (each lives in a spec and a test)
- LED-P1 allocation never exceeds supply (per commodity and total).
- LED-P2 allocation is non-negative.
- LED-P3 more supply never reduces total coverage (monotonicity).
- ORA-P1 intervals are monotone: p10 <= p50 <= p90 at every horizon.
- EYE-P1 segmentation output is invariant to tile processing order.
- LIB-P1 every answer has at least one valid citation or an explicit refusal.
- BRN-P1 every claim in a briefing has provenance resolving to an organ output.
Specs add more (see each requirements.md).

Hypothesis settings: profile `ci` (200 examples, deadline off for solver tests), profile `dev` (30 examples). Failing examples are kept in `.hypothesis/` locally and distilled into explicit regression tests.

## Evals (the "heartbeat")
Metrics: Eyes IoU and F1 vs reference maps; Oracle CRPS and interval coverage; Library citation accuracy and refusal rate on the 50-question set; Ledger feasibility rate and optimality gap; Brain end-to-end faithfulness. Results are written to `evals/results/` as JSON and Parquet, and read by the frontend dashboard. Eval runs are deterministic with fixed seeds and the `fake` LLM unless `--live-llm` is passed.

## Hooks (in `.kiro/hooks/`)
- `on-save-organ-tests`: on save under `organs/<x>/`, run that organ's unit and property tests (dev profile).
- `on-save-contract-validate`: on save of any `server.py`, `models.py`, or `mcp-contracts.md`, validate tool schemas against the contracts.
- `pre-commit-lint-secrets`: ruff, mypy, eslint, and a secret scan (gitleaks) before commit.
- `on-spec-change-tasks`: on save of a `requirements.md` or `design.md`, regenerate that spec's `tasks.md`.
- `on-save-eval-dashboard`: on save in an organ or `evals/`, run the fast eval subset and refresh `evals/results/latest.json`.

## Conventions
- Tests never hit the network. Live-mode paths are tested against recorded fixtures in `tests/fixtures/`.
- No test depends on a real LLM. Use `FakeLLM`.
- A bug fix lands with a failing test first.

## Demo-first enforcement
A pytest fixture (`no_network`) disables sockets (e.g. via `pytest-socket`) and is applied by default to all demo-mode, unit, property, and integration tests. A test needing the network is explicitly marked `@pytest.mark.live` and is excluded from CI. The Compose smoke test also runs with outbound traffic blocked.

## Additional properties (added after requirements approval)
- LED-P10 coverage is non-increasing in the equity floor. LED-P11 floor 0 equals the unconstrained optimum.
- ORA-P8 every forecast and eval carries `target_kind = modeled_glofas`.
- VOX-P5 swapping TTS providers never changes the output schema.
- LIB-P6 no non-redistributable document is committed.
- FRN-P6 every Oracle value renders with a "Modeled (GloFAS)" label.