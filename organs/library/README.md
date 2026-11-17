# library-mcp

The Library organ of Stitch: grounded flood-response guidance with page-level, verbatim
citations, or an explicit refusal when the committed corpus has no evidence.

Tools (contract v0.5, see `.kiro/steering/mcp-contracts.md`):

- `search_guidance`: hybrid BM25 + dense (e5-small int8) retrieval, mMARCO rerank for English.
- `answer_with_citations`: scope, evidence, quantity and conflict gates, then an LLM answer
  (`STITCH_LLM_PROVIDER`, `fake` replay by default) or an extractive answer. Every claim is
  verified against the stored page text before it is returned; claims that fail are dropped,
  and an answer with no verified claim becomes a refusal.

## Layout

```
src/stitch_library/
  core/            pure logic (normalize, chunk, bm25, fusion, decide, citations, answer, ...)
  ingest/          manifest model, PDF/text ingestion
  ml/              ONNX embedder and reranker, fake test models
  store/           MemoryStore, PgVectorStore, schema.sql, idempotent seeding
  service.py       wires store, models, calibration and LLM to the two tools
  server.py        thin MCP layer from stitch_common.mcp_app
  calibration.json refusal thresholds from evals/library/calibrate.py
tests/
  unit/ property/ contract/   fast tests (fake models, no network)
  integration/                real models (@models) and pgvector (@pg, Docker), skipped when absent
  test_smoke_stdio.py         starts the server over stdio, calls both tools
```

## Run

```
uv sync --all-packages
uv run python -m stitch_library.server --stdio                 # stdio (Kiro, Brain)
uv run python -m stitch_library.server --http --port 8000      # streamable HTTP, GET /healthz
uv run pytest organs/library
uv run python scripts/check_contracts.py
```

`STITCH_MODE=demo` (default) works offline from `data/demo/library/`. `STITCH_LIBRARY_STORE`
is `memory` (loads the committed pack) or `pgvector` (`STITCH_LIBRARY_DSN`).

## Corpus: add a document, rebuild, recalibrate, evaluate

1. Check the license on the source and write the evidence into a new row of
   `data/demo/library/manifest.yaml` (`license_evidence`, `redistributable`, `sha256` of the
   LF file). Only redistributable sources are committed (`tier: committed`); others are
   `tier: fetch` and are never committed (LIB-P6).
2. Put the text rendition under `data/demo/library/corpus/` (pages separated by
   `<<<page-break>>>` lines).
3. `uv run python scripts/check_corpus_licenses.py --write-docs` (regenerates
   `data/demo/MANIFEST.md` and the THIRD_PARTY.md document table).
4. `uv run python scripts/build_library_pack.py` (pages, chunks, vectors; `--check` in CI).
5. `uv run python -m evals.library.calibrate --seed 0` (dev split only).
6. `uv run python scripts/record_llm_demo.py --check --eval`; re-record missing prompts with
   `--provider nebius --eval --missing-only` (needs `NEBIUS_API_KEY` in the process env or
   `--env-file .env`). Recordings replay offline through `FakeLLM`.
7. `uv run python -m evals.run --organ library --seed 0 --fast`.

The committed corpus: FEMA Ready.gov pages (water, food, shelter, floods, kit), US EPA emergency
disinfection, an excerpt of the USAID/OFDA *Field Operations Guide for Disaster Assessment and
Response* v4.0 (food rations, shelter, camps, plastic sheeting), and AI-assisted Urdu
translations that a native speaker has not reviewed yet. WHO, Sphere and NDMA documents are
fetch-tier only.

## Eval results (2026-11-17)

`python -m evals.run --organ library --seed 0 --fast`: committed corpus, test split
(31 questions: 20 answerable, 11 expected refusals: 3 unanswerable plus 5 fetch-tier questions
whose evidence is not committed (INSUFFICIENT_EVIDENCE), 2 OUT_OF_SCOPE, 1 CONFLICTING_EVIDENCE),
reranker on, `FakeLLM` replaying the Nebius recordings. 95 % bootstrap intervals in brackets.

| Metric | Replay (deterministic) | `--live-llm` (Nebius Qwen3-235B, once) |
|---|---|---|
| Citation accuracy (cited page is a gold or alt page) | 0.976 [0.93, 1.00] | 0.980 [0.94, 1.00] |
| Citation validity (quote is verbatim on the page) | 1.000 | 1.000 |
| Answer rate (answerable questions answered) | 0.700 [0.50, 0.90] | 0.750 [0.55, 0.94] |
| Refusal rate (expected refusals refused) | 0.909 [0.69, 1.00] | 0.909 [0.69, 1.00] |
| False-answer rate | 0.091 | 0.091 |
| Refusal reason accuracy | 1.000 | 1.000 |
| Invariant P1 (answered with valid citations, or refused) | 1.000 | 1.000 |
| Recall@1 / @3 / @5 / @8 | 0.85 / 0.85 / 0.85 / 0.90 | same (retrieval has no LLM) |
| MRR | 0.858 | 0.858 |

By language (replay): English answer rate 0.80, Urdu 0.60; Urdu recall@3 0.70 against 1.00 for
English. The only false answer is q023 (container counts, a fetch-tier question) answered with
the one-gallon storage sentence. The replay and live runs differ on q012: the recorded reply
cited sentence ids that did not resolve, verification dropped every claim and the question was
refused; the live reply verified. Latency on the dev laptop (not the 2 vCPU container):
search p95 0.92 s, answer p95 0.93 s with the replay (1.17 s and 1.24 s on an earlier run).

All six Brain demo questions (water, food, shelter; English and Urdu) are answered from the
Nebius recordings with verbatim citations (`tests/integration/test_demo_questions.py`).
