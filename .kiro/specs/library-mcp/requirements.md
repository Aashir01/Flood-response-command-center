# library-mcp: Requirements

Organ: LLM + RAG over disaster-management guidance. Prefix `LIB`. Contract: `mcp-contracts.md` §5.

## Introduction
The Library answers response-guidance questions (e.g. "What is the minimum water ration per person per day in a flood shelter?") using only retrieved documents, with page-level citations. When evidence is missing, it refuses.

## Glossary
- **Corpus**: the indexed NDMA, PDMA, ReliefWeb, and Sphere documents, English and Urdu.
- **Chunk**: a passage of a page with `doc_id`, `page`, and char span.
- **Valid citation**: a citation whose `quote` appears verbatim at `doc_id`/`page`/`span` in the corpus.

## Requirements

### LIB-R1 Ingestion
1. WHEN a document is added to the corpus, THE Library SHALL extract text per page, detect language per page (`en` or `ur`), chunk it, embed it, and store chunk, page number, and metadata in Postgres with pgvector.
2. THE Library SHALL preserve page numbers and char offsets for every chunk.
3. IF a PDF page yields no extractable text, THEN THE Library SHALL record the page as `unreadable` and exclude it from the index instead of indexing empty text.
4. THE Library SHALL record license, source URL, and a `redistributable` flag per document in a manifest, and ingestion SHALL fail for documents missing any of them.
5. WHEN ingestion is re-run on unchanged input, THE Library SHALL produce the same chunk IDs (idempotent).

### LIB-R2 Hybrid retrieval
1. WHEN `search_guidance` is called, THE Library SHALL run BM25 and dense retrieval, fuse the results (reciprocal rank fusion), and rerank the top candidates with a cross-encoder reranker.
2. THE Library SHALL return `bm25`, `dense`, and `rerank` scores per hit.
3. WHERE `lang` is `auto`, THE Library SHALL detect the query language and search both languages, with cross-lingual dense retrieval.
4. WHERE `filters` are given, THE Library SHALL restrict results to matching documents.
5. THE Library SHALL return at most `top_k` hits, ordered by final score, with no duplicate chunks.

### LIB-R3 Cited answers
1. WHEN `answer_with_citations` is called and sufficient evidence exists, THE Library SHALL return `status = answered` with an answer composed only of statements supported by retrieved chunks.
2. THE Library SHALL map every answer sentence to at least one citation (`claims[].citation_idx`).
3. THE Library SHALL return citations with `doc_id`, `page`, `span`, and a verbatim `quote`.
4. THE Library SHALL answer in the language of the query unless the caller requests otherwise.

### LIB-R4 Refusal path
1. IF the best reranked evidence score is below the calibrated threshold, THEN THE Library SHALL return `status = refused` with `reason = INSUFFICIENT_EVIDENCE` and `closest_hits`.
2. IF the query is unrelated to disaster response, THEN THE Library SHALL refuse with `OUT_OF_SCOPE`.
3. IF retrieved sources contradict each other on the asked quantity, THEN THE Library SHALL refuse with `CONFLICTING_EVIDENCE` or state both with citations. The choice is defined in design.
4. THE Library SHALL NOT return an `answered` result with an empty citation list under any condition.
5. THE refusal threshold SHALL be set on a held-out split of the 50-question set, not on the evaluation split.

### LIB-R5 Citation verification
1. BEFORE returning an answer, THE Library SHALL verify each citation's `quote` against the stored page text.
2. IF any citation fails verification, THEN THE Library SHALL drop the claims relying on it. IF no supported claims remain, THEN THE Library SHALL refuse.

### LIB-R6 Prompt-injection posture
1. THE Library SHALL treat document text as data. Instructions inside retrieved chunks SHALL NOT alter the system prompt, tool behavior, or output schema.
2. THE Library SHALL strip or escape control markup in chunks before placing them in the LLM context.

### LIB-R7 LLM and offline operation
1. THE Library SHALL use the provider-agnostic `LLMClient` (Claude, OpenAI, or `fake`).
2. WHERE `STITCH_LLM_PROVIDER = fake`, THE Library SHALL answer demo questions from recorded responses so the demo runs offline and keyless.
3. IF the LLM provider is unavailable, THEN THE Library SHALL return `search_guidance`-style extractive answers (top chunk quotes with citations) flagged with a warning, or `UPSTREAM_UNAVAILABLE`.
4. The embedding and reranker models SHALL run locally on CPU (no external embedding API required). Model choice SHALL be set by env (`STITCH_EMBED_MODEL`, `STITCH_RERANK_MODEL`). The default is a small multilingual embedding model sized for a 2 vCPU / 4 GB host. Larger models are opt-in.

### LIB-R8 Operations
1. THE Library SHALL expose `GET /healthz` reporting DB connectivity, index size, and model load status.
2. THE Library SHALL return a `Provenance` block listing each document used with `as_of` and license.
3. THE Library SHALL complete `search_guidance` in under 1.5 s p95 and `answer_with_citations` in under 8 s p95 (with a real LLM) on the demo corpus on a 2 vCPU host.

### LIB-R9 Eval
1. THE Library SHALL ship a 50-question evaluation set (English and Urdu, including at least 10 unanswerable questions) with gold document/page labels.
2. THE eval SHALL report citation accuracy (cited page contains supporting evidence), citation validity (quote verbatim), answer-rate on answerable questions, refusal rate on unanswerable questions, and retrieval recall@k.

### LIB-R10 Corpus tiers and licensing
1. THE repo SHALL commit only documents whose license permits redistribution (`redistributable = true`).
2. THE repo SHALL provide `scripts/fetch_corpus.py` to download the remaining documents and ingest them into a local index, and these documents SHALL NOT be committed.
3. THE license, source URL, and redistribution status of every document (committed or fetched) SHALL be recorded in `data/demo/MANIFEST.md` and summarized in `THIRD_PARTY.md`.
4. THE committed subset SHALL be sufficient to answer every answerable question in the demo scenario and in a stated minimum share of the 50-question set. The eval SHALL report results separately for the committed subset and for the full corpus.

### LIB-R11 Demo-first
1. THE Library SHALL index and query the committed corpus subset with no network calls (embedding and reranker models are bundled in the image or cached at build time).
2. THE test suite SHALL enforce this with sockets disabled, using `FakeLLM`.

## Correctness properties (formalized in design)
- LIB-P1: every `answer_with_citations` result is either answered with at least one valid citation per claim, or refused with a `refusal` object.
- LIB-P2: every returned citation quote is a verbatim substring of the cited page text.
- LIB-P3: `search_guidance` returns at most `top_k` hits, with no duplicates, sorted by score.
- LIB-P4: adding an irrelevant document to the corpus does not change the top-1 hit for a query with a clear match (stability).
- LIB-P5: instructions injected into a chunk never change the output schema validity.

- LIB-P6: no file under the committed tree belongs to a document whose manifest entry has `redistributable = false` (checked by a CI script).

## Out of scope
OCR of scanned Urdu documents beyond what the chosen PDF extractor handles (unreadable pages are logged). Fine-tuning the LLM. Web search.

## Decisions (resolved)
1. Commit only redistributable documents. Fetch the rest with a script. License of each document is in THIRD_PARTY.md and the manifest. The demo works offline from the committed subset.
2. Embedding model: a small multilingual model by default, configurable by env. The specific model is chosen in design based on Urdu retrieval quality and license.