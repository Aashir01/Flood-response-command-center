# Stitch

A flood-response command center built for Kiroween 2026 (category: Frankenstein). Stitch fuses five AI organs (Eyes, Oracle, Library, Ledger, Voice) into one creature, steered by a Brain agent, that turns a flood threat into a cited, optimized, spoken response briefing.

**Status:** spec phase. No application code yet. See `.kiro/specs/` and `.kiro/steering/`.

Live demo (planned): https://stitch.aashirnoman.dev

## Layout

```
.kiro/            steering, specs, hooks, agents, MCP settings (committed, never ignored)
organs/           eyes, oracle, library, ledger, voice  (one MCP server each)
brain/            orchestrator (not an MCP server)
packages/         stitch_common: shared Pydantic models for contracts
frontend/         Next.js lab-bench UI
evals/            eval harness and results
data/demo/        small committed offline dataset
deploy/           Docker Compose, Caddy
docs/             write-up, architecture
```

## Run (planned)

```
docker compose up
```

License: MIT. Third-party code, data, and models: see THIRD_PARTY.md.
