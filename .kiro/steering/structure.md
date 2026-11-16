---
inclusion: always
---

# Repository structure

```
.kiro/
  steering/            product, tech, structure, mcp-contracts, ui-style, testing
  specs/<name>/        requirements.md, design.md, tasks.md  (bootstrap, eyes-mcp, oracle-mcp,
                       library-mcp, ledger-mcp, voice-mcp, brain, frontend, deployment)
  hooks/               automation hooks (see testing.md)
  agents/              custom agents (surgeon)
  settings/mcp.json    MCP registrations
organs/<organ>/
  pyproject.toml
  src/stitch_<organ>/
    core/              pure logic, no I/O
    server.py          MCP tool definitions (thin)
    models.py          imports from stitch_common where shared
  tests/               unit/, property/, contract/
  models/              committed demo weights (ONNX etc.), no checkpoints
  training/            (eyes, oracle) Colab/Modal notebooks, configs, fetch scripts
  README.md
packages/stitch_common/  contract models, provenance, LLM client, logging
brain/                   planner, task graph, conflict detector, critic, provenance, FastAPI + SSE
frontend/                Next.js app
evals/                   harness, datasets (50-question set, reference maps), results/*.parquet|json
data/demo/               committed offline dataset, with a MANIFEST.md listing source and license
deploy/                  compose.yaml, Caddyfile, Dockerfiles, env templates
docs/                    kiro-writeup.md, architecture.md
scripts/                 data fetchers, training entry points, dev helpers
```

## Naming
- Organs: package `stitch_eyes`, `stitch_oracle`, `stitch_library`, `stitch_ledger`, `stitch_voice`. MCP server names: `eyes-mcp`, etc.
- Spec directory names match MCP server names. Brain and frontend use `brain`, `frontend`.
- Requirement IDs: `<SPEC>-R<n>` (e.g. `LIB-R4`). Properties: `<SPEC>-P<n>` (e.g. `LED-P2`). Tasks reference the IDs they satisfy. Tests carry the ID in their name or a marker.
- ID prefixes: BOOT, EYE, ORA, LIB, LED, VOX, BRN, FRN, DEP.

## Rules
- Do not edit another spec's files when working on one spec, except to log a contract change in `mcp-contracts.md`.
- A contract change requires updating `mcp-contracts.md`, `stitch_common`, and every consumer in the same change.
- Every new dependency adds a THIRD_PARTY.md line in the same commit.
- Commit style: Conventional Commits (`feat(ledger): ...`). Commit small and often.
