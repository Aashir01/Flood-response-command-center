# library-mcp: Tasks

Tags: `core` (must ship), `stretch`. Each task lists the requirements and properties it satisfies and the tests that prove it. Ordered by dependency. Commit after each task (`feat(library): ...`). Design references are `design.md` sections (§).

Blocked by the **bootstrap** spec: `stitch_common` models and envelope, the `no_network` fixture, Hypothesis profiles, hooks, and the `surgeon` agent. The organ is scaffolded by `surgeon`, not by hand.

## Minimal path (marked `[M]`)

Goal: the Library works offline, end to end, on the committed subset in about 2.5 days (estimate 26 to 30 hours): in-memory store, BM25, small embedder, `FakeLLM`, extractive answers, provisional refusal thresholds. Tasks 1 to 12 are the minimal path. Task 12 is the checkpoint. Everything after it improves quality or deployability and can slip without breaking the demo. If time runs out, cut in this order: 22, 19, 16, 14.

Owner actions that block or shape the schedule (do them on day 1, in parallel with coding):
- Confirm the committed document list and license evidence (task 4, design §3.2).
- Optionally request written permission from NDMA, PDMA Sindh, and Sphere (§3.1).
- Find a native Urdu reviewer for the translated documents and for the Urdu questions.

- [x] **1. Scaffold the organ with `surgeon`** `core` `[M]` (about 1 h)
  - Generate `organs/library/` from the surgeon template: pyproject, `src/stitch_library`, `tests/{unit,property,contract,perf}`, README. Create the module tree from design §1 as empty modules with docstrings.
  - Add dependencies: `numpy`, `onnxruntime`, `tokenizers`, `pypdfium2`, `pdfminer.six`, `pyarrow`, `pyyaml`, `psycopg[binary]` (extra `pg`), `snowballstemmer` (optional extra). Each gets a `THIRD_PARTY.md` line in the same commit. **Verify the license of `pypdfium2` and `pdfminer.six` and record it** (design §4.1). If either is not permissive, stop and pick another extractor.
  - Confirm `no_network` is on by default, Hypothesis profiles `dev` and `ci` apply, ruff and mypy config applies.
  - Add pytest markers: `models` (needs the model cache), `pg` (needs `STITCH_TEST_PG_DSN`, uses `allow_loopback`), `perf`, `live`.
  - Done when: `uv run pytest` passes on the skeleton and `uv sync --package stitch-library` works on Windows.

- [x] **2. `stitch_common.llm`: interface and `FakeLLM`** `core` `[M]` (about 2 h)
  - `LLMRequest`, `LLMResponse`, `LLMClient`, `LLMUnavailable`, and `get_client(provider)` per design §7.1. `FakeLLM` replays `data/demo/library/llm_recordings.jsonl` by key, raises `LLMUnavailable` on a missing key, and has `adversarial`, `garbage`, and `echo_injection` test modes. Adapters come in task 22.
  - Tests: replay hit and miss, key stability (prompt version, normalized query, sorted chunk ids), mode behavior. Refs: LIB-R7.1, R7.2.
  - Coordinate with the brain spec so it reuses this module and does not write its own.
  - Done when: `FakeLLM` is importable from `stitch_common.llm` with `mypy --strict` clean.

- [x] **3. Normalization, language detection, sentences, chunks** `core` `[M]` (about 3 h)
  - `core/normalize.py`, `core/lang.py`, `core/sentences.py`, `core/chunk.py` per design §4.2 to §4.4, with `CHUNKER_VERSION`.
  - `tests/strategies.py`: `page_texts()` (English, Urdu, mixed, Urdu digits, ZWNJ, diacritics, letter variants, bullets, hyphenated line breaks).
  - Property tests: P9 (idempotence, quote verbatim after normalization), P13 (sentence spans), chunk spans equal `text[start:end]`, chunks never cross pages. Unit tests: hand-built English and Urdu splitting cases (`1.5 litres`, `No. 5`, `۔`, `؟`, bullets, long sentence), language detection on pure, mixed, and Arabic-only samples. Refs: LIB-R1.1, R1.2.
  - Done when: P9 and P13 pass under `ci` and the Urdu fixtures split as written in the docstrings.

- [ ] **4. Manifest, license checker, committed document list** `core` `[M]` (about 2 h of code, plus owner time)
  - `ingest/manifest.py` (Pydantic model per design §3.3, required fields, slug rule). `scripts/check_corpus_licenses.py` (rules 1 to 5 of §3.3, `--write-docs` to generate `data/demo/MANIFEST.md` and the `THIRD_PARTY.md` document table).
  - Owner-assisted: assemble `data/demo/library/manifest.yaml` and the committed PDFs for the proposed rows in §3.2. For each, read the license on the source page, fill `license_evidence`, and set `owner_confirmed`. Rows the owner cannot confirm become `tier: fetch`. Author or commission the Urdu translations and the field cards as text-first sources.
  - Tests: Hypothesis test that builds random manifests and file trees in a temp directory and compares the checker's verdict to an oracle (P6). Unit tests for each failure rule. Run the checker on the real repo in CI. Refs: LIB-R1.4, R10.1, R10.3. P6.
  - Done when: the checker passes on the repo, fails on each negative fixture, and every committed file has an `owner_confirmed` entry.

- [x] **5. Ingestion pipeline and pack builder** `core` `[M]` (about 4 h)
  - `ingest/pdf.py` (pypdfium2, pdfminer fallback, `classify_page` with the six rules of §4.1, child-process isolation with timeout), `ingest/pipeline.py` (pages, chunks, ids, report), `scripts/build_library_pack.py` (writes `pages.parquet`, `chunks.parquet`, `pack.json`; vectors are added in task 8). Ingestion fails on a manifest entry with a missing field and on documents under 60 % readable pages unless `--allow-low-yield`.
  - Fixtures: small generated PDFs (clean English, clean Urdu text-first, an empty page, a page with garbled private-use characters, a page with reversed Urdu words).
  - Tests: unit tests for each unreadable reason and the reorder detector. Property tests P7 (ids and Store contents identical on re-run) and P16 (unreadable pages never produce chunks). Refs: LIB-R1.1 to R1.5.
  - Done when: the pack builds from the committed PDFs and the ingest report lists readable-page ratios per document.

- [x] **6. `Store` protocol, `MemoryStore`, contract suite** `core` `[M]` (about 2 h)
  - `store/base.py`, `store/memory.py` per design §5.1 and §5.2. Load a pack into a `MemoryStore`.
  - `tests/contract/test_store_contract.py`: one parametrized suite (memory now, pgvector in task 13) covering idempotent upsert, delete cascade, filters, tie-break order, unreadable pages excluded.
  - Done when: the contract suite passes for `MemoryStore`.

- [x] **7. BM25 and tokenizers** `core` `[M]` (about 2 h)
  - `core/tokenize.py` (English stopwords, Urdu stopword list with a provenance note, optional stemmer behind a flag), `core/bm25.py` per design §6.2.
  - Tests: hand-computed BM25 scores on a 3-document example, Urdu fold equivalence (variant letters match), language routing, rebuild fingerprint. Refs: LIB-R2.1.
  - Done when: hand-computed scores match to 1e-9.

- [ ] **8. Embedder: model fetch, export, `OnnxEmbedder`, `FakeEmbedder`** `core` `[M]` (about 3 h)
  - `scripts/fetch_models.py` (pinned revisions and sha256, writes to `STITCH_MODEL_DIR`, build-time only, never imported by the server), `scripts/export_models.py` (dynamic int8 quantization, parity check: mean cosine at least 0.99 on 200 chunks, falls back to fp32 with a log line), `models/embedder.py` (`onnxruntime` with `tokenizers`, `query:` and `passage:` prefixes, L2 normalization, batching), `FakeEmbedder` (hashed bag-of-tokens, deterministic).
  - Extend `build_library_pack.py` to write `vectors.<model_id>.npy`.
  - Tests: `FakeEmbedder` determinism and overlap monotonicity (unit). `@models` tests: embedding shape and norm, English and Urdu paraphrase ranks above an unrelated sentence, int8 versus fp32 parity. Refs: LIB-R1.1, R7.4, R11.1.
  - Done when: a pack with real vectors builds on the laptop and the `@models` tests pass with the cache present.

- [x] **9. Hybrid retrieval and `search_guidance` core** `core` `[M]` (about 3 h)
  - `core/fusion.py` (RRF, k = 60), `core/retrieve.py` (§6.1 steps 1 to 8, reranker as `NullReranker` for now, exact score fill-in, `text_sha` dedupe, filters), `models/reranker.py` with `NullReranker` and `FakeReranker`.
  - Property tests: P3, P8, P17, P4 (constrained generator, as written in design §11). Unit tests: hand-built fusion example, cross-lingual query finds an Urdu chunk with `FakeEmbedder`, filters. Refs: LIB-R2.1 to R2.5.
  - Done when: P3, P8, P17, and P4 pass under `ci`.

- [x] **10. Refusal logic with provisional thresholds, scope gate, quantity rule** `core` `[M]` (about 2 h)
  - `core/decide.py` (pure verdict function), `core/scope.py` (anchors from `data/demo/library/scope_anchors.yaml`, 30 English and 30 Urdu phrases), quantity rule (§8.1 step 4). Thresholds come from `calibration.json`. Ship a **provisional** file marked `"provisional": true`, set by hand from a few probes. The server logs a warning while it is provisional.
  - Property test P10 (monotone in the threshold). Unit tests: each gate in isolation, `closest_hits` shape, the quantity rule in English and Urdu. Refs: LIB-R4.1, R4.2, R4.4.
  - Done when: P10 passes and the three refusal reasons are reachable in tests.

- [x] **11. Citations, verification, extractive answers** `core` `[M]` (about 3 h)
  - `core/citations.py` (slice quote, truncate at 400 on a word boundary, adjust span), `core/answer.py` (verification steps 1 to 5 of §7.3, answer assembly from claims, final non-empty-citation assertion), `core/extractive.py` (§7.5). The LLM path is task 15, but the verification code is written here against a claim model so extractive answers use the same checks.
  - Property tests: P1 and P2 (extractive path, any query on `mini_corpora`), P14 (numbers), P15 (verdict versus gate). Unit tests: truncation, cross-language claim handling, URL rejection. Refs: LIB-R3.1 to R3.4, R4.4, R5.1, R5.2, R7.3.
  - Done when: P1, P2, P14, and P15 pass under `ci`.

- [x] **12. MCP server, envelope, health, offline end-to-end test** `core` `[M]` **checkpoint** (about 2 h)
  - `server.py` (`search_guidance`, `answer_with_citations`, error mapping per §9.1, provenance per §9.2, input limits per §13), `http.py` (`/healthz`, §9.3), `settings.py`. `STITCH_LIBRARY_STORE=memory` loads the committed pack directly. Write `data/demo/library/demo_questions.yaml` (5 to 6 questions answerable from committed documents; share it with the brain spec).
  - Tests: contract tests validate real tool output against the schemas generated from `stitch_common` (`additionalProperties: false`). End-to-end test under `no_network`: start the server in memory mode, call both tools for every demo question, assert answered with valid citations. P18. Refs: LIB-R8.1, R8.2, R11.1, R11.2.
  - Done when: the end-to-end test passes with sockets disabled and the contract hook is green. **Minimal path complete.**

Status (2026-11-17, implementing agent): ticked tasks meet their "Done when". Open items in ticked tasks: no `tests/perf` directory (task 1), `record_llm_demo.py --check` is not yet a CI step (task 15). Not ticked: 4 (no row is `owner_confirmed`), 8 (no `@models` embedder tests besides the demo replay test), 13 (no string-built-SQL grep test, no pgvector service in CI; the pg contract suite, P11 and `tests/integration/test_pgvector_pack.py` pass locally against Docker), 14 (no failing-reranker fallback test), 17 (set is now 51 questions after the 2026-11-17 corpus change; no `evals/library/README.md`), 19 (`docs/library-models.md` missing), 20, 21, 22 (no manual live run of the Claude/OpenAI adapters), 23.

## After the checkpoint

- [ ] **13. `PgVectorStore`, schema, idempotent seeding, Compose fragment** `core` (about 4 h)
  - `store/pgvector.py` (psycopg 3, bound parameters only), `store/schema.sql` and migrator, `store/seed.py` per design §5.4, Postgres init script (`CREATE EXTENSION vector`, non-superuser role), a Compose service snippet and Library container health check to hand to the deployment spec.
  - Tests: the contract suite from task 6 now runs on both stores (`pg` marker, `allow_loopback`). P11 on random data. Seeding twice performs no writes (assert row counts and `meta.seed_key`). A crash mid-seed (simulated) leaves the previous state. A grep test fails on string-built SQL. CI adds a `pgvector/pgvector:pg16` service container and requires the `pg` tests. Refs: LIB-R1.1, R1.5, R8.1. P11, P7.
  - Done when: a second `docker compose up` seeds nothing, and P11 passes against a real Postgres.

- [ ] **14. Reranker** `core` (about 3 h)
  - `models/reranker.py` `OnnxReranker` (mMARCO int8, `tokenizers`, truncation to 256 tokens, batch of 20, semaphore of 4), per-language gating through `STITCH_RERANK_LANGS`, `NullReranker` fallback on load or run errors with a warning. Extend `export_models.py` to the reranker.
  - Tests: `@models` test that the relevant passage ranks above an unrelated one (English), the Urdu behavior is recorded (see task 19), a failing reranker degrades to `rerank = null` without error, P3 still holds with the reranker off, on, and failing. Refs: LIB-R2.1, R2.2, R7.4.
  - Done when: reranked retrieval passes the contract and property tests and falls back cleanly.

- [x] **15. LLM answer path and prompt-injection defenses** `core` (about 4 h)
  - `core/context.py` (sanitize, number sentences, build prompt, `PROMPT_VERSION`), the claim schema and parser, the LLM branch in `core/answer.py` (resolve ids, set `insufficient` and `conflict` handling, extractive fallback on `LLMUnavailable`, invalid or oversized output, `STITCH_LIB_REQUIRE_LLM`). `scripts/record_llm_demo.py` (`live` marker, needs a key) writes `llm_recordings.jsonl` for the demo questions after human review. `--check` lists stale keys and runs in CI.
  - Tests: P5 (injection payloads and `FakeLLM` adversarial modes), P1, P2, P14, P15 with fuzzed `llm_outputs()`. Unit tests: unknown ids, extra keys, oversize, non-JSON, forged `<doc>` tags, injected URL, `insufficient: true`. Replay test: demo questions answer from recordings under `no_network`. Refs: LIB-R3.1, R5, R6, R7.1 to R7.3. P5, P14, P15.
  - Done when: P5 passes and every demo question answers from a recording through the full verification path.

- [x] **16. Conflict detector** `core` (about 2 h)
  - `core/conflict.py` per design §8.6 (unit table, canonical units, relative difference above 20 %, two documents, shared query terms). Wire it into the decision order. Support `STITCH_LIB_CONFLICT_POLICY=refuse` only.
  - Tests: fixed sentences (litres versus US gallons, same-document repeats, different dimensions, Urdu digits), `closest_hits` holds both passages, LLM `conflict: true` tightens. Refs: LIB-R4.3.
  - Done when: both passages of a conflicting pair appear in `closest_hits` with reason `CONFLICTING_EVIDENCE`, and non-conflicts are not refused.

- [ ] **17. Author the 50-question set** `core` (about 6 h of human work, start once the corpus is frozen, can run in parallel with tasks 13 to 16)
  - Follow design §10.2: freeze corpus hashes, write 30 English and 20 Urdu questions (Urdu written natively), 38 answerable and 12 unanswerable (6 insufficient evidence, 4 out of scope, 2 conflicting), gold `(doc_id, page)` with copied `evidence_quote`, `required_facts`, `alt_pages`, `tier`. Assign the split once by the committed rule (20 dev, 30 test). Write `dev_extra.jsonl` (at least 40 items, about 25 negatives). Write `evals/library/README.md` with the process and the committed-share count.
  - `evals/library/validate_questions.py`: quote is verbatim in stored page text, gold documents exist, tier is consistent, counts and split rule hold, at least 10 unanswerable, at least 70 % of answerable questions are `committed`.
  - Tests: unit tests of the validator on good and broken fixtures. P12 split-hash check as a CI script. Refs: LIB-R9.1, R10.4. P12.
  - Done when: the validator passes and counts match design §10.1.

- [x] **18. Calibration and eval harness** `core` (about 4 h)
  - `evals/library/calibrate.py` (design §8.4, seed 0, writes `calibration.json`), `evals/library/run.py` (metrics of design §10.4, committed and full corpus reported separately, bootstrap intervals, per-language, reranker on and off, extractive versus LLM). Wire into `python -m evals.run --organ library [--fast]` and the dashboard schema. Stale-calibration and split-overlap checks refuse to run.
  - Tests: threshold selection on synthetic scores (known optimum), cost weights, pooled-threshold fallback with warning, metric functions on hand-built result sets, stale calibration blocks the run. Refs: LIB-R4.5, R9.2, R10.4. P10, P12.
  - Done when: `python -m evals.run --organ library --fast --seed 0` is reproducible, replaces the provisional thresholds, and the report separates dev, test, committed, and full.

- [ ] **19. Model and tokenizer decisions on the dev set** `core` (about 3 h, needs task 17)
  - Compare on dev: e5-small versus paraphrase-multilingual-MiniLM (and bge-m3 once, as opt-in evidence) by recall@8 and MRR per language. Check the mMARCO reranker on Urdu (with versus without) and set `STITCH_RERANK_LANGS`. Check English stemming on versus off and Urdu trigram expansion on versus off. Record numbers in `docs/library-models.md`. Switch a default only by the margins stated in design §6.6.
  - Tests: the comparison script is deterministic and its output is committed as a small JSON. Refs: LIB-R7.4, R2.1.
  - Done when: defaults are justified by committed numbers, and `calibration.json` is regenerated if any model changed.

- [ ] **20. `scripts/fetch_corpus.py`** `core` (about 3 h)
  - Allow-listed https hosts, pinned sha256, `%PDF-` and content-type check, 100 MB cap, timeout, redirect policy, quarantine on mismatch, `--repin`, `--dry-run`, ingest into the chosen store as `tier = fetched`. Prints the license note per document.
  - Tests against a local fake HTTP server on loopback (`allow_loopback`): success, hash mismatch, wrong type, oversize, redirect to a non-allowed host, bad `doc_id`. No real network in CI. Refs: LIB-R10.2. Security §13.
  - Done when: all negative cases fail closed and `git ls-files data/raw` stays empty.

- [ ] **21. Performance and offline checks** `core` (about 3 h)
  - `scripts/bench_library.py` and `tests/perf/` per design §12. Run the full suite with sockets disabled. Measure per-stage p50 and p95 and peak RSS in a container with `--cpus=2 --memory=4g`. Update design §12 estimates with measured values.
  - Refs: LIB-R8.3, R11. P18.
  - Done when: `search_guidance` p95 is under 1.5 s and Library overhead for `answer_with_citations` is under 2.5 s on the constrained container, or the shortfall is written down with the proposed fix (smaller rerank window, rerank off for a language, smaller model).

- [ ] **22. Claude and OpenAI adapters** `core` (about 2 h)
  - `ClaudeClient` and `OpenAIClient` in `stitch_common.llm`, lazy SDK imports, key from the provider's environment variable, timeout and error mapping to `LLMUnavailable`, structured-output request where supported.
  - Tests: mocked transport (no network). A `live` smoke test for each, excluded from CI. Refs: LIB-R7.1, R7.3.
  - Done when: `STITCH_LLM_PROVIDER=anthropic` and `openai` work in a manual `live` run and fail closed without a key.

- [ ] **23. Documentation and attributions** `core` (about 2 h)
  - `organs/library/README.md`, `docs/library-corpus.md` (what is committed, what is fetched, how to confirm a license, how to add a document), `docs/library-models.md`, `data/demo/MANIFEST.md` and `THIRD_PARTY.md` (documents, models, libraries, generated by task 4's script), a short section in `docs/kiro-writeup.md` on the verify-before-return citation design and the dev/test split.
  - Done when: a reader can add a document, rebuild the pack, recalibrate, and run the eval from the README alone.

- [ ] **24. Stretch items** `stretch`
  - a. Dev-time OCR (Tesseract `urd`) for unreadable pages, flagged `ocr = true` (design §4.1).
  - b. `STITCH_LIB_CONFLICT_POLICY=state_both`.
  - c. Reranker-based claim support score as verification step 6 (§7.3).
  - d. Per-model partial HNSW index above 50,000 chunks (§5.3).
  - e. Urdu character-trigram BM25 expansion if task 19 shows a gain.
  - f. Add NDMA, PDMA, or Sphere documents to the committed set if written permission arrives (manifest change plus rebuild plus recalibration only).
  - g. Evaluate bge-m3 and bge-reranker-v2-m3 as opt-in on a larger host and document the result.

## Traceability

| Requirement | Tasks |
|---|---|
| LIB-R1 | 3, 4, 5, 6, 8, 13 |
| LIB-R2 | 7, 9, 14, 19 |
| LIB-R3 | 11, 15 |
| LIB-R4 | 10, 11, 16, 18 |
| LIB-R5 | 11, 15 |
| LIB-R6 | 15 |
| LIB-R7 | 2, 8, 11, 14, 15, 19, 22 |
| LIB-R8 | 12, 13, 21 |
| LIB-R9 | 17, 18 |
| LIB-R10 | 4, 17, 18, 20, 23 |
| LIB-R11 | 8, 12, 21 |

| Property | Task | Property | Task |
|---|---|---|---|
| P1 | 11, 15 | P10 | 10, 18 |
| P2 | 11, 15 | P11 | 13 |
| P3 | 9, 14 | P12 | 17, 18 |
| P4 | 9 | P13 | 3 |
| P5 | 15 | P14 | 11, 15 |
| P6 | 4 | P15 | 11, 15 |
| P7 | 5, 13 | P16 | 5 |
| P8 | 9 | P17 | 9 |
| P9 | 3 | P18 | 12, 21 |

Properties P1 to P6 come from `requirements.md`. P7 to P18 are added by this design (§11).
