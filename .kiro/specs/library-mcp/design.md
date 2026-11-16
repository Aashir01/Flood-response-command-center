# library-mcp: Design

Implements `requirements.md` (LIB-R1..R11). Contract: `mcp-contracts.md` §5 (v0.3). Proposed contract additions are listed in §17 and are not applied.

## 1. Overview

The Library answers response-guidance questions from a corpus of disaster-management documents, in English and Urdu, with page-level citations. It refuses when the evidence is missing, contradictory, or off-topic.

Pipeline for `answer_with_citations`:

```
query -> normalize + detect lang -> scope gate
      -> hybrid retrieve (BM25 + dense -> RRF -> cross-encoder rerank)
      -> evidence gate (calibrated threshold) -> conflict gate
      -> LLM writes claims that point at numbered sentences  (or extractive fallback)
      -> verify every claim against stored page text; drop what fails
      -> assemble answer from surviving claims  | refuse if none survive
```

Two rules shape everything:
1. **The LLM never supplies quotes.** It points at sentence ids that the Library already holds. Quotes are sliced from stored page text, so they are verbatim by construction, and the verifier re-checks them anyway.
2. **The LLM can only make the result more conservative.** It may add a refusal or lose claims. It can never add evidence, a citation, or a number the evidence does not contain.

All logic lives in `core/` as pure functions behind small protocols (`Store`, `Embedder`, `Reranker`, `LLMClient`). The MCP and HTTP layers are thin. Unit and property tests run with an in-memory store, hash-based fake embedder, fake reranker, and `FakeLLM`, with no model download and no Postgres.

```
organs/library/src/stitch_library/
  core/
    normalize.py     NFC, Arabic/Persian letter folding, bidi/ZWNJ handling, digit folding, search_text
    lang.py          script-based language detection (page, chunk, query)
    sentences.py     sentence splitter (EN and Urdu punctuation), span-preserving
    chunk.py         sentence-packing chunker, chunk ids, CHUNKER_VERSION
    tokenize.py      BM25 tokenizer per language, stopwords
    bm25.py          in-process Okapi BM25 index (per language), pure
    fusion.py        reciprocal rank fusion, deterministic tie-breaks
    retrieve.py      hybrid orchestration over Store, Embedder, Reranker protocols
    scope.py         OUT_OF_SCOPE gate (anchor-phrase similarity)
    conflict.py      quantity extraction, unit normalization, conflict rule
    decide.py        pure refusal decision function (thresholds in, verdict out)
    context.py       sanitize chunks, number sentences, build the LLM prompt
    answer.py        parse LLM output, verify claims, assemble answer
    extractive.py    LLM-free answer path
    citations.py     build Citation objects, verbatim check, quote truncation
  ingest/
    pdf.py           extraction (pypdfium2, pdfminer.six fallback), unreadable-page rule
    manifest.py      manifest model and validation
    pipeline.py      pages -> chunks -> embeddings -> pack
  store/
    base.py          Store protocol and shared row types
    memory.py        MemoryStore (numpy)
    pgvector.py      PgVectorStore (psycopg 3, parameterized SQL only)
    seed.py          idempotent seeding of the committed pack
    schema.sql       versioned DDL
  models/
    embedder.py      OnnxEmbedder (onnxruntime + tokenizers), FakeEmbedder
    reranker.py      OnnxReranker, FakeReranker, NullReranker
  server.py          MCP tools, envelope, error mapping
  http.py            GET /healthz
  settings.py        env config
  calibration.json   committed thresholds (see §8.4)
tests/{unit,property,contract,perf}/    strategies.py holds shared Hypothesis strategies
packages/stitch_common/src/stitch_common/llm/   LLMClient, FakeLLM, Claude and OpenAI adapters (built by this spec, §7.1)
scripts/  fetch_corpus.py  build_library_pack.py  fetch_models.py  export_models.py
          check_corpus_licenses.py  record_llm_demo.py  bench_library.py
data/demo/library/  MANIFEST.md  manifest.yaml  corpus/  pack/  llm_recordings.jsonl  demo_questions.yaml  scope_anchors.yaml
evals/library/      questions.jsonl  dev_extra.jsonl  validate_questions.py  calibrate.py  run.py  README.md
```

The Library does not import another organ. It shares only `stitch_common`.

## 2. Key choices at a glance

| Topic | Choice | Why (short) |
|---|---|---|
| Embedding default | `intfloat/multilingual-e5-small` (MIT), int8 ONNX, 384-d | Small, lists `ur`, built for asymmetric query-passage retrieval |
| Embedding opt-in | `BAAI/bge-m3` (MIT), 1024-d | Better quality, about 568M parameters, too heavy for the default host |
| Reranker default | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (Apache-2.0), int8 ONNX | Small multilingual cross-encoder. Urdu not in its listed languages, so it is gated by a dev-set check (§6.5) |
| Reranker opt-in | `BAAI/bge-reranker-v2-m3` (Apache-2.0) | 568M parameters, opt-in only |
| Lexical search | In-process Okapi BM25, one index per language, built from the Store at startup | Same code for both stores, true BM25, Urdu-aware tokenizer, tens of MB |
| Vector store | Postgres 16 + pgvector, exact search; `MemoryStore` for tests | Meets tech.md. Exact scan is fast enough at this size |
| PDF extraction | `pypdfium2`, fallback `pdfminer.six`; no PyMuPDF | PyMuPDF is AGPL. Repo is MIT |
| Fusion | RRF, k = 60 | Standard, no score calibration needed |
| Conflicting evidence | Refuse with `CONFLICTING_EVIDENCE`, both sources in `closest_hits` | Safety, simplicity, honest about a heuristic detector (§8.6) |
| Answer construction | LLM emits claims that cite sentence ids; Library slices quotes and builds the answer | Citation validity is enforced by code, not by trust |
| Corpus | Commit only documents with recorded license evidence and owner confirmation; everything else fetched by script | Several named sources are not clearly redistributable (§3) |

## 3. Corpus and licensing

### 3.1 What I checked, and what I could not

Findings are from pages fetched while writing this spec. Where a page blocked me, I say so. None of this is legal advice, and every `redistributable = true` entry needs the owner's confirmation (field `owner_confirmed`).

| Source | Evidence | Verdict |
|---|---|---|
| ReliefWeb-hosted documents | ReliefWeb Terms and Conditions (https://reliefweb.int/terms-conditions): permission to download and copy for personal, non-commercial use, "without any right to resell or redistribute", plus per-item restrictions. | **Not redistributable.** Fetch by script. High confidence. |
| Sphere Handbook (EN, UR) | https://spherestandards.org/intellectual-property/ returned HTTP 403 to me. A search snippet of that page says the material is copyrighted, may be reproduced without fee for educational purposes with acknowledgment, and is not intended for resale. | **Treat as not redistributable.** Educational-use permission is not an open license. Fetch by script. Owner may ask Sphere for written permission. |
| NDMA Pakistan plans, guidelines, sitreps (ndma.gov.pk) | Documents found by search. I found no license statement or open-data terms. Pakistan's Copyright Ordinance 1962 has a chapter-III provision on the term of copyright in government works, so government works are not automatically public domain. I did not read the section text. | **Unclear. Safe default: fetch by script.** Owner may request written permission from NDMA. |
| PDMA Sindh sitreps and plans (pdma.gos.pk) | Documents found by search (Monsoon 2022 daily situation reports). No license statement found. | **Unclear. Fetch by script.** Same as NDMA. |
| World Bank / Open Knowledge Repository, including the 2022 Pakistan Floods PDNA | The PDNA is "a product of the Government of Pakistan" prepared with ADB, EU, UN agencies, UNDP and the World Bank (text of the document, found by search). I could not load the document's license field. Open Knowledge Repository items are often CC BY 3.0 IGO, but that is my recollection, not something I verified. | **Unverified.** Candidate only if the owner confirms the license on the document page and that third-party content is covered. |
| US CDC pages and `stacks.cdc.gov` PDFs (floodwater safety, keep food and water safe, WASH emergencies) | US federal agency publications. Works of US federal employees are not copyrighted in the US (17 U.S.C. §105). I did not fetch a CDC copyright page. | **Likely public domain. High-medium confidence.** Check each document for third-party images or a copyright notice. |
| WHO technical notes on WASH in emergencies | Page found. License not checked. | **Unknown. Fetch by script.** |
| Team-authored Urdu translations of the public-domain CDC material, labeled "unofficial translation" | We own the translation. Source is public domain. | **Redistributable** (we choose CC BY 4.0). Needs a native-speaker review. |
| Team-authored English "field card" digests | Our own words, each pointing to a primary source page. | **Redistributable, but weak as evidence.** Last-resort filler. Cited as secondary sources, never presented as official text. |

### 3.2 Proposed committed subset (owner must confirm every row)

| doc_id (proposed) | Doc | Lang | License | Confidence | Owner action |
|---|---|---|---|---|---|
| `cdc-floodwater-safety` | CDC "Safety Guidelines: Floodwater" | en | US federal, public domain | high-medium | Check footer, save the PDF print with the retrieval date |
| `cdc-keep-food-water-safe` | CDC "Keep Food and Water Safe" (stacks.cdc.gov) | en | US federal, public domain | high-medium | Same |
| `cdc-wash-emergencies` | CDC WASH-related emergencies pages | en | US federal, public domain | high-medium | Same |
| `cdc-floodwater-safety-ur` | Urdu translation of the same | ur | CC BY 4.0 (ours) | high | Native-speaker review. Label "unofficial translation" |
| `cdc-keep-food-water-safe-ur` | Urdu translation | ur | CC BY 4.0 (ours) | high | Same |
| `stitch-field-cards-en` / `-ur` | Short digests of NDMA/Sphere guidance with source page pointers | en, ur | CC BY 4.0 (ours) | high that we may publish. Evidence quality is low | Decide whether to include at all |
| `wb-pakistan-pdna-2022` | World Bank copy of the 2022 PDNA | en | CC BY 3.0 IGO? | **low until verified** | Verify on the document page |

Fetched only (not committed): NDMA National Disaster Management Plan, National Flood Response Plan, monsoon contingency plans and sitreps; PDMA Sindh Monsoon 2022 sitreps and contingency plan; ReliefWeb flood-response documents; the Sphere Handbook in English and Urdu; WHO WASH technical notes.

Consequences the owner should know:
- **The headline demo question (minimum water ration in a shelter) normally comes from Sphere, which I recommend not committing.** The committed corpus can answer water-quantity questions from CDC text, which gives different numbers with a different scope. That mismatch is a real conflict case, and it is useful for the `CONFLICTING_EVIDENCE` demo once the fetched Sphere copy is loaded. For the offline demo the questions in `demo_questions.yaml` must be answerable from committed documents only.
- Urdu coverage in the committed subset comes from our own translations. Official Urdu documents (NDMA, Sphere) are fetch-only.
- If NDMA, PDMA or Sphere grant written permission, add the document with `license_evidence` pointing to the permission letter (stored in `docs/permissions/`) and set `owner_confirmed = true`. Nothing else in the design changes.

### 3.3 Manifest

`data/demo/library/manifest.yaml` is the single source of truth. `data/demo/MANIFEST.md` and `THIRD_PARTY.md` rows are generated from it by `scripts/check_corpus_licenses.py --write-docs`.

```yaml
- doc_id: cdc-floodwater-safety          # slug ^[a-z0-9][a-z0-9_-]{2,63}$
  title: ...
  publisher: CDC                         # filter field
  doc_type: guideline                    # guideline|plan|sitrep|standard|assessment|digest
  lang: en
  source_url: https://...                # https only
  retrieved_on: 2026-..-..
  as_of: 2024-..-..                      # document date, may be null
  sha256: <hex>                          # of the PDF file
  license: US-Gov-PD                     # SPDX id or short text
  license_url: https://...
  license_evidence: "quote or note, with where it was read"
  redistributable: true
  owner_confirmed: true
  tier: committed                        # committed | fetch
  path: corpus/cdc-floodwater-safety.pdf   # committed tier only
```

Rules (checked by `scripts/check_corpus_licenses.py`, which is LIB-P6):
1. Every entry has every field above. A missing field fails ingestion (LIB-R1.4) and the CI check.
2. `tier = committed` requires `redistributable = true`, `owner_confirmed = true`, and a non-empty `license_evidence`.
3. Any tracked file under `data/demo/library/corpus/` or `data/demo/library/pack/` must belong to a manifest entry with `tier = committed`. The pack lists the doc ids it was built from, and each must be a committed entry. **Derived artifacts count.** Chunk text, page text, and embeddings of a non-redistributable document are derivatives and are never committed.
4. `tier = fetch` entries carry `source_url` and `sha256` for `fetch_corpus.py`, and no `path`.
5. `data/raw/` is git-ignored. A CI step fails if `git ls-files data/raw` is non-empty.

### 3.4 `scripts/fetch_corpus.py`

- Reads `tier = fetch` entries. Writes only to `data/raw/library/<doc_id>.pdf`, then runs the same ingestion pipeline into a local index (`--into pgvector|memory`, default from `STITCH_LIBRARY_STORE`).
- Safety: https only. Host allow-list (`ndma.gov.pk`, `www.ndma.gov.pk`, `pdma.gos.pk`, `reliefweb.int`, `spherestandards.org`, `documents1.worldbank.org`, `openknowledge.worldbank.org`, `www.who.int`, `cdn.who.int`), extendable only by editing the script. Redirects are followed only to allow-listed hosts. Response must have `%PDF-` magic bytes, content type `application/pdf`, size at most 100 MB, 60 s timeout, one request at a time with a 1 s pause. The file name comes from `doc_id` after the slug regex, never from the URL or headers.
- Integrity: sha256 is pinned in the manifest. A mismatch fails the run and moves the file to `data/raw/library/quarantine/`. `--repin <doc_id>` rewrites the hash after a human has looked at the diff. NDMA and PDMA sometimes replace files at the same URL, so expect repins.
- Prints the license note and `redistributable=false` for every fetched document. No credentials, no cookies, no secrets.
- Tests use recorded HTTP responses (a local fake server on loopback, marked `allow_loopback`). The script itself is excluded from the no-network CI path and marked `live` for real runs.

## 4. Ingestion

### 4.1 Extraction and the unreadable-page rule

Extractor: `pypdfium2` (PDFium wrapper) is the primary, `pdfminer.six` the fallback when PDFium yields an unreadable page. I chose both for license reasons (neither is AGPL) and I have **not verified their license files** in this pass. Task 4 records the verification in `THIRD_PARTY.md` and swaps the extractor if a license surprise appears. PyMuPDF is excluded because it is AGPL.

Urdu PDFs are the hard case. Typical failures:
- Nastaliq fonts with no `ToUnicode` map. Extraction returns private-use or Latin-looking garbage.
- Text stored as shaped presentation forms (U+FB50 to U+FDFF, U+FE70 to U+FEFF), sometimes in visual (reversed) order.
- Words split into letter fragments, or digits and Latin text interleaved in the wrong direction.

Page status is decided by `ingest/pdf.py::classify_page`, deterministic, with the thresholds in `settings.py`:

1. Normalize the extracted text (§4.2). Fold presentation forms to base letters (NFKC applied to the Arabic-script blocks only).
2. `unreadable:empty` if fewer than 20 letters remain.
3. `unreadable:garbled` if more than 2 % of characters are U+FFFD, private-use (U+E000 to U+F8FF), or control characters.
4. For Arabic-script pages: compute the Urdu function-word hit rate (کے کی کا میں ہے اور سے کو پر نے) on the text as extracted, on each word reversed, and on the whole string reversed. Pick the variant with the highest rate. If that rate is below 0.02 on a page with at least 100 tokens, mark `unreadable:garbled`. If a reversed variant wins, store that variant and record `reordered = true` on the page.
5. `unreadable:other_script` if the page is Arabic-script with no Urdu-specific letters (ٹ ڈ ڑ ں ے ھ ہ گ چ ک) and no Urdu function words. Arabic and Persian pages are out of scope.
6. Otherwise `ok`.

Unreadable pages are stored in `pages` with their status and reason, and no chunks are created for them (LIB-R1.3, LIB-P16). The ingest report lists them, and the manifest summary shows the readable-page ratio per document. A document with under 60 % readable pages fails ingestion with a clear message unless `--allow-low-yield` is given.

Fallbacks, in order: (1) pdfminer on the failed pages; (2) for committed documents, replace the PDF with a text-first source we control (our own translations are authored as text and rendered to PDF by us, so extraction is clean); (3) **stretch**: dev-time OCR with Tesseract `urd` (Apache-2.0 engine, trained data separately licensed) on unreadable pages, with the OCR text stored in the pack and flagged `ocr = true`. OCR never runs at query time. Extraction runs only at pack-build or fetch time, in a child process with a timeout and memory limit, because PDF parsers are an attack surface.

### 4.2 Normalization (`core/normalize.py`)

Two derived strings per page and chunk:

| String | Used for | Rules |
|---|---|---|
| `text` (canonical page text) | storage, quotes, spans, display | NFC. Remove bidi controls (U+200E, U+200F, U+202A to U+202E, U+2066 to U+2069). Remove tatweel U+0640. Fold Arabic letters to Urdu forms: ي U+064A to ی U+06CC, ك U+0643 to ک U+06A9, ه U+0647 to ہ U+06C1, ى U+0649 to ی. Keep ھ U+06BE and آ. Keep ZWNJ U+200C and ZWJ U+200D (orthographically meaningful in Urdu). Collapse runs of spaces and tabs to one space, single newlines to a space, keep blank-line paragraph breaks. Join English words broken by a trailing hyphen at a line end only when the next fragment starts lowercase. Digits are **not** changed, so quotes match the source digits. |
| `search_text` | BM25 and the embedder input | `text` plus: strip Arabic diacritics U+064B to U+065F and U+0670, remove ZWNJ and ZWJ, map Arabic-Indic and Eastern Arabic-Indic digits to ASCII, lowercase Latin, NFKC for Latin ligatures. |

`normalize` is idempotent (LIB-P9). Queries go through the same `search_text` path. The stored `text` is the corpus of record: **quotes are slices of `text`, spans are code-point offsets into `text`** (Python `str` indices, so surrogate pairs count once). Offsets are never computed on `search_text`.

RTL safety: citations carry `lang`, and the Library never inserts bidi control characters into quotes. The frontend isolates each quote with `dir="rtl"` or `<bdi>` and the `lang` field. A mixed Urdu/English quote is displayed as stored.

### 4.3 Language detection (`core/lang.py`)

No external model. Script ratio over letters: `ur` if Arabic-script letters are at least 50 % of letters and the Urdu-marker test passes (§4.1 step 5), `en` if Latin letters are at least 50 %, otherwise `other`. Applied per page (stored on `pages.lang`, the majority language) and per chunk (stored on `chunks.lang`, used for filtering and BM25 routing, which matters for bilingual pages). Roman Urdu is out of scope and detected as `en`. The queries use the same function.

### 4.4 Sentences and chunks

`core/sentences.py` splits `text` into sentences and returns `(start, end)` offsets:
- Always split after ۔ and ؟. Split after `.`, `!`, `?` only when followed by whitespace and an uppercase letter, digit, bullet, or quote, and when the preceding token is not a digit run (so `1.5 litres`), a single capital letter, or a known abbreviation (`No.`, `e.g.`, `i.e.`, `Fig.`, `approx.`, `etc.`).
- Bullet and numbered list lines are separate sentences.
- A sentence over 400 characters is split at the last `;`, `،`, `,` or space before 400.

`core/chunk.py` packs consecutive sentences of one page into chunks of 150 to 700 characters (target about 450), never crossing a page boundary, no overlap. A trailing chunk under 150 characters merges into the previous one when the total stays under 900. A chunk is the pair `(start, end)` into `text`, so every chunk is exactly `text[start:end]`.

`chunk_id = "c_" + sha256(f"{doc_sha256}:{page}:{start}:{end}:{CHUNKER_VERSION}").hexdigest()[:20]`. The same input gives the same ids (LIB-R1.5, LIB-P7). A chunker change bumps `CHUNKER_VERSION` and invalidates the pack on purpose.

### 4.5 Embedding and pack

`E5` needs prefixes: `"passage: "` on chunk `search_text`, `"query: "` on queries. Vectors are L2-normalized float32. Embedding runs in batches of 16, sorted by length.

`scripts/build_library_pack.py` builds `data/demo/library/pack/` from the committed PDFs: `pages.parquet`, `chunks.parquet`, `vectors.<model_id>.npy` (float16 on disk, converted to float32 on load), and `pack.json` (doc ids, manifest hash, chunker version, model id and revision, counts, readable-page ratios). With about 3,000 chunks the pack is a few MB. If the runtime model id differs from the pack's, the seeder re-embeds locally from the pack's chunk text and logs a warning (a few minutes on 2 vCPU). Re-embedding needs only the model cache, never the network.

## 5. Storage

### 5.1 `Store` protocol

```python
class Store(Protocol):
    def upsert_documents(self, docs: Sequence[DocRow]) -> None: ...
    def upsert_pages(self, pages: Sequence[PageRow]) -> None: ...
    def upsert_chunks(self, chunks: Sequence[ChunkRow], model_id: str, vectors: ndarray) -> None: ...
    def delete_documents(self, doc_ids: Sequence[str]) -> None: ...
    def dense_search(self, qvec: ndarray, k: int, model_id: str, flt: Filters) -> list[tuple[str, float]]: ...
    def get_vectors(self, chunk_ids: Sequence[str], model_id: str) -> ndarray: ...
    def get_chunks(self, chunk_ids: Sequence[str]) -> list[ChunkRow]: ...
    def get_page(self, doc_id: str, page: int) -> PageRow | None: ...
    def iter_search_rows(self) -> Iterator[SearchRow]: ...   # chunk_id, lang, doc_id, publisher, doc_type, search_text
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str) -> None: ...
    def stats(self) -> StoreStats: ...
```

Behavior shared by both implementations (contract-tested, LIB-P11):
- `dense_search` returns cosine similarity, descending, ties broken by `chunk_id` ascending, at most `k`, only chunks of `status = ok` pages, and only chunks matching `Filters` (publisher, doc_type, optional lang).
- Upserts are idempotent. Re-upserting identical rows changes nothing.
- `delete_documents` removes pages, chunks, and vectors of those documents.
- Parameters are always bound values. No SQL string is built from caller input; filter lists use `= ANY(%s)`.

### 5.2 `MemoryStore`

Python dicts for rows and a float32 matrix for vectors. `dense_search` is a masked matrix-vector product with `argpartition` then a stable sort. It is the store used by unit, property, and eval-smoke tests, and by `STITCH_LIBRARY_STORE=memory`, which loads the pack directly with no Postgres. That mode also serves Windows development without Docker.

### 5.3 `PgVectorStore`

Image `pgvector/pgvector:pg16`. DDL in `store/schema.sql`, versioned in `meta.schema_version`, applied by a small migrator (no ORM). `CREATE EXTENSION IF NOT EXISTS vector` runs in the Postgres init script, because it needs a superuser. The Library connects as a non-superuser role with only the rights it needs.

```sql
CREATE TABLE meta       (key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE documents  (doc_id text PRIMARY KEY, title text NOT NULL, publisher text NOT NULL,
                         doc_type text NOT NULL, lang text NOT NULL, source_url text NOT NULL,
                         license text NOT NULL, redistributable boolean NOT NULL,
                         tier text NOT NULL CHECK (tier IN ('committed','fetched')),
                         sha256 text NOT NULL, as_of date);
CREATE TABLE pages      (doc_id text REFERENCES documents ON DELETE CASCADE, page int NOT NULL,
                         lang text NOT NULL, status text NOT NULL CHECK (status IN ('ok','unreadable')),
                         reason text, text text NOT NULL, PRIMARY KEY (doc_id, page));
CREATE TABLE chunks     (chunk_id text PRIMARY KEY, doc_id text NOT NULL, page int NOT NULL,
                         start_char int NOT NULL, end_char int NOT NULL, lang text NOT NULL,
                         text text NOT NULL, search_text text NOT NULL, text_sha text NOT NULL,
                         FOREIGN KEY (doc_id, page) REFERENCES pages ON DELETE CASCADE);
CREATE TABLE chunk_vectors (model_id text NOT NULL,
                         chunk_id text REFERENCES chunks ON DELETE CASCADE,
                         embedding vector NOT NULL, PRIMARY KEY (model_id, chunk_id));
```

Dense search is an **exact scan**, `ORDER BY embedding <=> %s, chunk_id LIMIT %s`, with `model_id` in the `WHERE` clause. The column has no fixed dimension so a model swap needs no schema change, and an index is not possible without a fixed dimension. At 20,000 chunks of 384 dimensions that is a sequential scan of about 30 MB, which I estimate at tens of milliseconds on 2 vCPU (to be measured in task 18). Past about 50,000 chunks add a per-model partial HNSW index (stretch).

### 5.4 Idempotent seeding (`store/seed.py`)

Runs inside the Library container at startup, before `/healthz` reports ready. Compose runs the Library after `postgres` is healthy (`depends_on: condition: service_healthy`, owned by the deployment spec).

1. Open a connection, take `pg_advisory_lock(<constant>)` so two replicas cannot seed at once.
2. Apply migrations if `schema_version` is behind.
3. Read `pack.json`. Compute `seed_key = sha256(pack manifest hash, chunker version, model id + revision)`.
4. If `meta.seed_key == seed_key`, do nothing and log "already seeded".
5. Otherwise, in one transaction: upsert documents, pages, chunks, and vectors with `ON CONFLICT DO UPDATE`, delete committed-tier documents that are no longer in the pack, set `meta.seed_key`. Documents with `tier = fetched` are never touched by seeding.
6. Release the lock.

A second start therefore does no writes. A crash mid-way leaves the previous state (single transaction). `/healthz` includes `seeded`, `seed_key`, `docs`, `chunks`, and `readable_page_ratio`.

### 5.5 Testing the two stores

`tests/contract/test_store_contract.py` runs one parametrized suite over `MemoryStore` and `PgVectorStore`. The Postgres param needs `STITCH_TEST_PG_DSN` and the `allow_loopback` marker (loopback only; the `no_network` fixture still blocks everything else). Without the DSN it is skipped locally and **required in CI**, which runs a `pgvector/pgvector:pg16` service container. LIB-P11 compares results of both stores on generated data: same ids and order, cosines equal within 1e-5.

## 6. Retrieval

### 6.1 Pipeline

1. Validate input (§13). `search_text` the query. Detect language, `qlang`.
2. Embed the query (`"query: "` prefix). With `lang = auto`, search all languages. With `lang = en|ur`, restrict to chunks of that language (LIB-R2.3 read literally; see §18 for the ambiguity).
3. BM25 on the index of `qlang` (top 50). Dense search on the Store (top 50). Filters apply to both.
4. Reciprocal rank fusion over the two lists: `rrf(d) = Σ_r 1 / (60 + rank_r(d))`, ranks starting at 1, ties in a source list broken by `chunk_id`. Final ties broken by `chunk_id`.
5. Take the top `W = max(20, top_k)` fused candidates. Collapse candidates with the same `text_sha` (mirrored documents) keeping the lowest `chunk_id`.
6. Compute exact `bm25` and `dense` for every candidate. BM25 can score any chunk directly and the Store returns its vector, so a hit's scores are never missing just because the other channel did not list it (LIB-R2.2).
7. Rerank the `W` candidates with the cross-encoder on `(query, chunk text)`.
8. Sort by `rerank` descending, then `rrf` descending, then `chunk_id` ascending. Truncate to `top_k`.

Hit fields: `score` is the rerank logit when the reranker ran for that language, else the fused RRF score. `rerank` is `null` when the reranker was skipped (disabled, failed, or disabled for the language). All hits in one response use the same scorer, so ordering by `score` is consistent (LIB-P3).

### 6.2 BM25 (`core/bm25.py`)

Okapi BM25, `k1 = 1.2`, `b = 0.75`, `idf = ln(1 + (N - n + 0.5) / (n + 0.5))`. One index per language (`en`, `ur`), so IDF and average length are not mixed across scripts. Postings are stored as `array('I')` pairs (document index, term frequency) per term id, with token strings interned to integer ids. Built at startup from `Store.iter_search_rows()`. At 20,000 chunks of about 100 tokens I estimate under 40 MB and a build time of a few seconds. The index carries a fingerprint (hash of the sorted chunk ids) and is rebuilt after ingestion.

Tokenizer (`core/tokenize.py`): `search_text`, split on Unicode word characters, drop stopwords.
- English: lowercase, a committed stopword list, light stemming via `snowballstemmer` (English) **only if the dev-set check shows a gain** (task 7); otherwise plain tokens.
- Urdu: a committed list of about 100 stopwords (کے، کی، کا، میں، ہے، اور، سے، کو، پر، نے، …). No stemmer. Characters differing only by the folds in §4.2 already match. Character-trigram expansion for Urdu is a **stretch** option, kept off unless the dev set shows it helps.

### 6.3 Why BM25 in-process and not Postgres full-text or SQLite FTS

| Option | Urdu | Ranking | Under the 4 GB floor | Verdict |
|---|---|---|---|---|
| In-process BM25 | Our tokenizer and stopwords | True Okapi BM25, identical for both stores | Tens of MB, rebuilt at startup | **chosen** |
| Postgres `tsvector` | No Urdu dictionary ships. The `simple` config works, with no stopwords or stemming | `ts_rank` is not BM25 | Fine | Behavior would differ from `MemoryStore`, so the contract test would not prove equivalence |
| SQLite FTS5 | `unicode61` tokenizes Arabic script, BM25 built in | BM25 | A second store, a second file to seed and keep in sync | Extra moving part for no gain at this scale |

Cost of the choice: the index lives in memory per Library process, and the corpus must fit in memory. A cap of 50,000 chunks is stated and enforced with a clear startup error.

### 6.4 Determinism

Fixed tie-breaks everywhere (`chunk_id` ascending), single-threaded numpy and BM25, ONNX Runtime with fixed thread count. The same query on the same index gives the same hits and scores on one machine (LIB-P8 covers RRF and the full pipeline with fakes).

### 6.5 Reranker policy

`STITCH_RERANK_MODEL` selects the reranker. `STITCH_RERANK_LANGS` (default `en,ur`) names the query languages it applies to. The default model's card lists English, Arabic, Hindi, and others but not Urdu, so Urdu quality is unverified. Task 14 compares dev-set MRR and recall@3 for Urdu queries with and without the reranker. If it does not help Urdu, set `STITCH_RERANK_LANGS=en` and Urdu queries run on RRF scores with their own calibrated threshold (§8.4). `NullReranker` is the fallback if the model is missing or errors: the result then carries a warning and `rerank = null`.

### 6.6 Embedding and reranker candidates

Verified from the Hugging Face model API at spec time (license, parameters, languages, ONNX files). Latency figures are estimates and are marked as such.

| Model | License | Params | ONNX available | Urdu | Notes |
|---|---|---|---|---|---|
| `intfloat/multilingual-e5-small` | MIT | 117.7M (fp32 about 470 MB, int8 about 120 MB, computed) | yes, incl. qint8 variants | `ur` in the model's language list | 384-d, max 512 tokens, needs `query:`/`passage:` prefixes. **Default.** |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Apache-2.0 | 117.7M | yes, incl. qint8 | `ur` in the model's language list | 384-d, trained for paraphrase similarity with a 128-token limit. Weaker for question-to-passage retrieval. Fallback if e5 fails the dev check |
| `BAAI/bge-m3` | MIT | about 568M (XLM-R large, from the reranker twin's 567.8M) | yes (`onnx/model.onnx` with external data) | multilingual, 100+ languages | 1024-d, 8192 tokens. fp32 about 2.2 GB, int8 about 570 MB (computed). **Opt-in.** On 4 GB shared with Postgres and four other organs it is too tight |

Reranker candidates:

| Model | License | Params | Urdu | Verdict |
|---|---|---|---|---|
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | Apache-2.0 | 117.6M (mostly embeddings; small encoder) | Not in the listed languages. XLM-R-family base | **Default**, gated by the Urdu dev check |
| `BAAI/bge-reranker-v2-m3` | Apache-2.0 | 567.8M | multilingual | **Opt-in**, too large for the default host |
| `jinaai/jina-reranker-v2-base-multilingual` | CC BY-NC (my recollection, not verified here) | base-size | multilingual | Rejected on license: non-commercial |
| none (RRF only) | n/a | 0 | n/a | Built-in fallback, §6.5 |

Quantization: the repos' prebuilt `qint8_avx512_vnni` ONNX files need AVX-512 VNNI, which an i5 laptop or an unknown VPS CPU may lack. `scripts/export_models.py` instead runs ONNX Runtime dynamic int8 quantization on the fp32 ONNX file, which runs on any AVX2 x86 CPU. It then checks parity: mean cosine between fp32 and int8 embeddings on 200 chunks of at least 0.99, and recall@8 on the dev set within 2 points. Otherwise it ships fp32 for that model. Weights are fetched at image build by `scripts/fetch_models.py` using pinned revisions (e5-small `614241f6…`, mMARCO `1427fd65…`, bge-m3 `5617a9f6…`, bge-reranker-v2-m3 `953dc6f6…` as read from the API at spec time) and sha256 checks. They are not committed (over the 50 MB guideline in tech.md). Tokenization uses the `tokenizers` library, so the runtime needs no PyTorch or `transformers`.

Why e5-small over paraphrase-MiniLM: same size, retrieval-oriented training, longer input. Why not default to bge-m3: quality gain is real but memory and per-query latency on 2 vCPU break the budget in §12. Whether e5-small beats paraphrase-MiniLM on Urdu cannot be settled from model cards. There are no Urdu retrieval numbers in the cards I read. Task 7 runs both on the dev set and switches the default if e5-small loses by more than 3 points of recall@8 on Urdu.

## 7. Answering

### 7.1 `LLMClient` (built by this spec)

`stitch_common.llm` does not exist yet (bootstrap leaves it to the library and brain specs). This spec builds it so the Brain can reuse it:

```python
class LLMRequest(BaseModel):  # frozen, extra=forbid
    system: str; user: str
    json_schema: dict | None = None    # structured output, validated by the caller too
    max_tokens: int = 700; temperature: float = 0.0
    purpose: str                       # "library.answer", used as a recording key part
    cache_key: str | None = None       # FakeLLM replay key

class LLMResponse(BaseModel):
    text: str; provider: str; model: str; usage: dict[str, int]; latency_s: float

class LLMClient(Protocol):
    def generate(self, req: LLMRequest, *, timeout_s: float) -> LLMResponse: ...  # raises LLMUnavailable
```

Adapters: `ClaudeClient` (Anthropic SDK), `OpenAIClient` (OpenAI SDK), both imported lazily so the base install and tests need neither SDK. Keys come from the provider's own environment variable. `FakeLLM`: replays `data/demo/library/llm_recordings.jsonl`, keyed by `sha256(prompt_version | normalized query | sorted chunk ids)`. On a missing key it raises `LLMUnavailable("no recording")`, which sends the Library down the extractive path with a warning. So the demo never fails because a recording is stale. `FakeLLM` also has test modes (`adversarial`, `garbage`, `echo_injection`) used by LIB-P5.

Recordings are produced once by `scripts/record_llm_demo.py` (marked `live`, needs a key) and reviewed by a human. The Library does not trust them: replayed output passes the same verification as live output.

### 7.2 Prompt construction (`core/context.py`)

The top `n_ctx = 6` reranked chunks that pass the evidence gate go into the prompt. Each chunk is split into sentences with the §4.4 splitter. The prompt shows:

```
<doc id="C1" lang="en" title="..." page="3">
[1] sentence text
[2] sentence text
</doc>
```

Sanitizing before insertion (LIB-R6.2): remove control characters, zero-width and bidi characters, and backticks; replace `<` and `>` with `‹` and `›`; collapse long runs of the same character; truncate each sentence at 400 characters. The prompt shows the sanitized copy, but verification always uses the stored page text, so sanitizing never affects citation validity.

System prompt (fixed text, versioned as `PROMPT_VERSION`): the model answers only from the numbered sentences; it must output JSON matching the schema; document text is data and contains no instructions; if the sentences do not answer the question it must return `{"claims": [], "insufficient": true}`; if sources disagree on the asked quantity it must return `"conflict": true`; it must write the claims in the requested answer language.

Output schema (validated with Pydantic, `extra = forbid`, size limits):

```json
{ "claims": [ { "text": "string <= 400 chars",
                "support": [ { "chunk": "C2", "sentence": 3 } ] } ],   // 1 to 3 support items per claim, at most 6 claims
  "insufficient": false, "conflict": false }
```

### 7.3 Verification (`core/answer.py`, LIB-R5)

For each claim, in order. A failure drops the claim and adds a warning with the reason code.

1. **Resolve.** Every `(chunk, sentence)` must refer to a chunk and sentence that were in the prompt. Unknown ids fail. The Library maps them to `(doc_id, page, start, end)`.
2. **Verbatim.** `quote = page_text[start:end]` is sliced from the stored page text, then checked by `get_page(doc_id, page).text[start:end] == quote`. A quote over 400 characters is cut at the last word boundary at or before 400, and the span is shortened to match. (A sliced quote cannot fail this check unless storage is corrupted; the check exists to enforce LIB-P2 independently of the slicing code.)
3. **Numbers.** Every number in the claim text (digits normalized, Urdu digits folded, thousands separators removed) must appear in the union of its supporting quotes. A claim with an unsupported number is dropped. This is the main guard against an LLM inventing a figure.
4. **Lexical support (same language).** If the claim language equals the quote language, at least 50 % of the claim's content tokens (stopwords removed) must appear in the quotes after `search_text` normalization. Cross-language claims skip this step and rely on step 3, so a claim without numbers in a cross-language answer has weaker checking. I note that as a known limit.
5. **URLs and addresses.** A claim containing a URL, e-mail address, or phone number not present in its quotes is dropped (blocks injected links).
6. **Stretch:** score `(claim, quote)` with the reranker and drop below a calibrated support threshold.

After verification: if `insufficient` or `conflict` was set by the LLM, the Library applies the matching refusal (the LLM can tighten the result). If no claim survives, the result is a refusal with `INSUFFICIENT_EVIDENCE` and `closest_hits` (LIB-R5.2). Otherwise `answer` is the surviving claim texts joined with a space, in the order the LLM gave them. **The answer text is built only from claims, so every sentence of the answer has a `claims[]` entry** (LIB-R3.2). `citations` is the deduplicated list of quotes, and `citation_idx` indexes it. `answer_with_citations` never returns `answered` with an empty citation list: the final assembly asserts it and converts a violation to a refusal (LIB-P1).

### 7.4 Answer language

`answer_lang` is the `lang` input if it is `en` or `ur`, otherwise the detected query language. The prompt asks for claims in that language. Quotes stay in the source language. Mixed-language citations are expected and shown as stored. A question in Urdu answered from English evidence yields Urdu claims with English quotes, subject to the weaker check in §7.3 step 4.

### 7.5 Extractive fallback (`core/extractive.py`, LIB-R7.3)

Used when the LLM is unavailable (timeout, `LLMUnavailable`, no recording), when its output fails schema validation (no retry loop), or when `STITCH_LLM_PROVIDER` is unset. Deterministic:
1. Take the top 2 chunks that pass the evidence gate.
2. Score each sentence by the reranker on `(query, sentence)` if available, else by query-term overlap with the dense-weighted chunk score.
3. Keep up to 3 sentences scoring at least half of the best.
4. Each kept sentence is its own claim whose text is the sentence itself, cited to itself.

The result is `answered`, with a warning `EXTRACTIVE_FALLBACK` naming the reason. With `STITCH_LIB_REQUIRE_LLM=true` the same situation returns `UPSTREAM_UNAVAILABLE` (`retryable = true`) instead. Extractive answers pass the same verification and the same gates.

### 7.6 Prompt-injection posture (LIB-R6)

- Document text is data. It is never placed in the system prompt, and the system prompt states this.
- Structural defense, not detection: the LLM output is parsed by a strict schema. It has no tools. Document text reaches the answer only as quotes sliced by id, and claim text is constrained by §7.3 steps 3 to 5.
- Delimiters and escaping as in §7.2. `<doc>` tags cannot be forged because `<` and `>` are replaced inside content.
- Heuristic flagging (`ignore previous`, `system prompt`, `you are now`, `<|`, `assistant:`, and Urdu equivalents) marks a chunk `injection_suspect` in logs and adds a warning. The chunk stays in the corpus (it is data) and is not dropped.
- Output limits: at most 6 claims, 400 characters per claim, 700 tokens.
- An invalid or oversized LLM output triggers the extractive path, never a retry with the model's own text.
- The LLM cannot change the tool's output schema, because the Library builds the result and Pydantic validates it before return.

## 8. Refusal

### 8.1 Order of gates

1. **Scope gate.** `scope_score = max cosine(query_vec, anchor_vecs)` over the anchor phrases in `scope_anchors.yaml` (about 30 English and 30 Urdu phrases on floods, relief, shelter, water, sanitation, evacuation, health, logistics, early warning). If `scope_score < τ_scope`, refuse with `OUT_OF_SCOPE`. `closest_hits` is empty (an out-of-scope query has no relevant hits to show).
2. **Retrieval.** Run §6.
3. **Evidence gate.** `evidence_score` is the best rerank logit among hits (or the best dense cosine when the reranker is off for that language). If it is below `τ_evid[qlang, scorer]`, refuse with `INSUFFICIENT_EVIDENCE` and `closest_hits` of the top 3 hits as citations.
4. **Quantity rule.** If the query asks for a quantity (patterns: how many, how much, minimum, per person, per day, کتنا، کتنی، کتنے، کم از کم، فی کس) and none of the top 3 hits contains a number, refuse with `INSUFFICIENT_EVIDENCE`.
5. **Conflict gate** (§8.6).
6. **Generation and verification** (§7). No surviving claim gives `INSUFFICIENT_EVIDENCE`.

`core/decide.py::decide(signals, thresholds) -> Verdict` is pure and takes only numbers, so the refusal logic is property-testable without a model.

### 8.2 `closest_hits`

Built from the top reranked hits as `Citation` objects: the first sentence (up to 400 characters) of the chunk that best matches the query, with `doc_id`, `page`, and span. These are shown to the user as "closest material, not an answer". They are verbatim slices like any citation.

### 8.3 What counts as the score

Rerank logits are not probabilities and differ by model and language. The thresholds therefore belong to a `(language, scorer, model ids)` triple. Changing the embedding or reranker model invalidates `calibration.json`, and startup logs an error and the eval harness refuses to run until recalibration (task 17).

### 8.4 Calibration (LIB-R4.5)

The 50-question set is split once, at authoring time, by a fixed rule (§10.2) into a **dev split** (20 questions) and a **test split** (30). Fifty questions are too few to tune a threshold per language and also keep an untouched test set, so calibration also uses `evals/library/dev_extra.jsonl`: 40 or more extra items (about 25 negatives, 15 positives) that are written by the authors, labeled `dev_only`, and never reported.

`evals/library/calibrate.py --seed 0`:
1. For each dev and dev-extra item, run retrieval and record `evidence_score` and `scope_score`. A positive is an answerable item whose gold page is in the top 3. A negative is an unanswerable item.
2. Choose `τ_evid` per language to minimize `3 · FalseAnswers + 1 · FalseRefusals` over midpoints between sorted scores. Ties go to the larger threshold. False answers cost three times false refusals because a wrong number in a relief plan is worse than a missing one.
3. If a language has fewer than 8 negatives, use the pooled threshold and record a warning in `calibration.json`.
4. Choose `τ_scope` the same way using in-scope versus out-of-scope items, with the same 3:1 cost.
5. Write `calibration.json`: thresholds, model ids and revisions, hash of the dev ids, counts, and the dev false-answer and false-refusal rates.

The eval harness (a) refuses to run if `calibration.json` model ids differ from the current ones, and (b) fails if the dev id set intersects the test id set (LIB-P12). The headline numbers come from the test split only. Dev numbers are reported in a separate block labeled "tuned on".

### 8.5 Margin rule

Margin rules (for example, requiring the top score to exceed the second by some gap) were considered and **not** adopted. With 20 dev questions plus the extras, a second tuned parameter would overfit. The evidence gate uses one threshold per language.

### 8.6 Conflicting evidence: decision and detector

**Decision: refuse with `CONFLICTING_EVIDENCE`, and put the conflicting passages in `closest_hits`.** Alternatives considered:

| Option | For | Against |
|---|---|---|
| Refuse, show both passages in `closest_hits` | Safe. Simple. No generated "both sides" text. The user still sees both quotes. | The user gets no single recommended figure |
| Answer, stating both with citations | More useful when the difference is explained by scope (drinking water versus total domestic use) | The detector is a heuristic. A false positive would emit a confident-looking sentence. Needs a template sentence that cites two sources, and the invariant "each sentence maps to citations" gets harder to reason about |

I chose the first on correctness and simplicity. The Brain's own conflict detector can still surface the discrepancy. `STITCH_LIB_CONFLICT_POLICY=state_both` is a stretch option.

Detector (`core/conflict.py`), run on the hits that passed the evidence gate:
1. Extract `(value, unit)` pairs with a regex over a fixed unit table (litres, gallons, m³, kg, g, days, hours, cm, mm, m², persons, persons per toilet, per person per day). Fold digits and common number words. Convert to a canonical unit per dimension (US gallon to litres).
2. Keep pairs from sentences that share at least 2 content terms with the query.
3. Conflict if two different `doc_id`s each have such a sentence among the top 3 hits, with the same dimension and a relative difference above 20 %.
4. The LLM's `conflict: true` flag also triggers it (it can only tighten).

It has false negatives (unit variants, tables, spelled-out numbers) and I do not claim otherwise. The 2 `CONFLICTING_EVIDENCE` questions in the eval set measure it.

## 9. Interfaces

### 9.1 Tools

Tool I/O follows `mcp-contracts.md` §5. Inputs use `additionalProperties: false`. Results are wrapped in `ToolResult` from `stitch_common`.

| Condition | Result | retryable |
|---|---|---|
| validation failure, size limits (§13) | `INVALID_INPUT` | false |
| refusal of any kind | `ok: true`, `status = refused` (a refusal is a valid result, not an error) | n/a |
| Store or index not ready, DB down | `UPSTREAM_UNAVAILABLE` | true |
| LLM unavailable | extractive answer with warning; or `UPSTREAM_UNAVAILABLE` if `STITCH_LIB_REQUIRE_LLM=true` | true |
| `search_guidance` with zero hits after filters | `ok: true`, `hits = []` | n/a |
| unexpected exception | `INTERNAL` | false |

`NO_EVIDENCE` in the envelope's error codes is not used by this organ. Absence of evidence is a refusal, not an error.

### 9.2 Provenance

`organ = library`, `mode = demo|live` (from `STITCH_MODE`), `data_sources` = one entry per document that contributed a hit or citation (`id = doc_id`, `name = title`, `license`, `as_of`), `model` = embedder and reranker (name `e5-small+mmarco-mMiniLM`, version the pinned revisions, `sha256` of the concatenated weight hashes). The LLM provider and model are reported in `warnings` as `llm=<provider>/<model>` until the contract gains a field (§17).

### 9.3 `GET /healthz`

Reports DB connectivity (or `memory`), `seeded`, `seed_key`, document and chunk counts by tier, readable-page ratio, BM25 index fingerprint and size, embedder and reranker ids with `loaded` flags, calibration status (`ok`, `stale`, `missing`), and LLM provider name. Unhealthy (HTTP 503) if the DB is down, the index is empty, or the embedder failed to load. A missing reranker is degraded, not unhealthy.

### 9.4 Server

MCP Python SDK (`FastMCP`), stdio and streamable HTTP, plus `/healthz`. Models load at startup (warm) so the first query does not pay the load cost. A semaphore of 4 limits concurrent reranks. A per-request deadline applies.

## 10. Evaluation set and harness

### 10.1 Contents (LIB-R9.1)

50 questions: 30 English, 20 Urdu. 38 answerable, 12 unanswerable (6 `INSUFFICIENT_EVIDENCE`, 4 `OUT_OF_SCOPE`, 2 `CONFLICTING_EVIDENCE`). Categories: quantity, procedure, definition, role/responsibility, health and WASH, logistics. At least 6 of the 20 Urdu questions have English evidence (cross-lingual). A minimum of **70 % of the 38 answerable questions (27) must be answerable from the committed corpus alone**, and all questions in `demo_questions.yaml` must be (LIB-R10.4). If fewer documents end up committed than planned, the count is stated in `evals/library/README.md` and reported, not hidden.

### 10.2 Authoring process

Written by humans, not generated by the system under test, to avoid circular evaluation.
1. **Freeze the corpus.** Record the manifest hash and the pack hash. Questions are written against that frozen state. If the corpus changes, `validate_questions.py` flags questions whose gold evidence changed.
2. **Write.** The owner writes the English questions and the Urdu questions (or has the Urdu ones written natively; machine translation is not allowed for Urdu questions, because translated phrasing is not how an Urdu speaker asks). A second person, if available, reviews wording. Each answerable question is written from a page the author has read.
3. **Label gold.** For each answerable question: one or more gold `(doc_id, page)`, an `evidence_quote` copied from that page, optional `alt_pages` (other pages that also support the answer), and `required_facts` (short strings that must appear in a correct answer, usually numbers and units).
4. **Tool-assisted check.** `evals/library/validate_questions.py` verifies that each `evidence_quote` is a verbatim substring (after the §4.2 normalization) of the stored page text, that gold documents exist in the manifest, and that the `tier` field is right (`committed` only if every gold document is a committed one).
5. **Unanswerable questions.** `INSUFFICIENT_EVIDENCE` items are plausible disaster-response questions with no support in the corpus. The author documents the check: a grep and a BM25 top-5 inspection show no supporting page. `OUT_OF_SCOPE` items are unrelated to disaster response. `CONFLICTING_EVIDENCE` items have two gold passages from two documents that disagree. If either passage comes from a fetch-only document, the question is tagged `tier = full`. With the committed corpus only, such a question has one side missing, so the expected outcome there is `INSUFFICIENT_EVIDENCE` (see §10.4). If both passages are committed, the question is tagged `committed` and expects `CONFLICTING_EVIDENCE`.
6. **Split.** One rule, applied once and committed: sort questions by `sha256(id)`, then assign by stratum (language × answerable × category) so that dev has 20 questions with 7 Urdu, 15 answerable, and 5 unanswerable (so the 5 includes at least one of each refusal reason where possible), and test has the remaining 30 with 13 Urdu, 23 answerable, 7 unanswerable. The split is stored in each record and is never changed after calibration. A CI check fails if any question's `split` differs from the committed split hash.

### 10.3 File format

`evals/library/questions.jsonl`, one JSON object per line:

```json
{"id":"q017","split":"test","lang":"ur","question":"…","answerable":true,
 "expected_status":"answered","expected_reason":null,
 "category":"quantity","tier":"committed",
 "gold":[{"doc_id":"cdc-keep-food-water-safe-ur","page":2,"evidence_quote":"…"}],
 "alt_pages":[],"required_facts":["…"],"author":"…","reviewer":"…","notes":""}
```

### 10.4 Running and reporting (LIB-R9.2, LIB-R10.4)

`python -m evals.run --organ library --seed 0 [--corpus committed|full] [--split test|dev] [--fast]`. Deterministic, `FakeLLM` unless `--live-llm`.

- `--corpus committed` indexes only committed documents (CI, the default). A question whose gold documents are not all committed is **scored against the committed corpus as unanswerable**: refusing is correct, answering is a false answer unless its citations still point at valid supporting text (then it counts as answered-correct, flagged `answered_from_alt`). This keeps the committed numbers honest instead of silently dropping questions.
- `--corpus full` needs `scripts/fetch_corpus.py` to have run. It is run locally and its results are reported separately in the same JSON (`corpus: committed|full`), never mixed.
- Metrics per corpus and split, with bootstrap 95 % confidence intervals (n is small, so intervals are wide and the report says so):
  - citation accuracy: share of citations whose `(doc_id, page)` is a gold or alt page
  - citation validity: share of citations whose quote is verbatim in stored page text (must be 100 %)
  - answer rate on answerable questions
  - refusal rate on unanswerable questions, and reason accuracy
  - false-answer rate (answered where a refusal was expected)
  - fact recall: share of `required_facts` present in the answer
  - retrieval recall@k and MRR for k in 1, 3, 5, 8 (gold or alt page in the top k hits)
  - per-language breakdown, reranker on versus off, and extractive versus LLM path
- Output: `evals/results/library.json` and `.parquet` in the dashboard schema. The `--fast` subset (committed corpus, test split, `FakeLLM`) runs in CI.

## 11. Correctness properties and how they are tested

Hypothesis profile `ci` (200 examples), `dev` (30). Shared strategies in `tests/strategies.py`:
- `page_texts()`: English, Urdu, and mixed text with sentence punctuation (`.`, `؟`, `۔`), numbers with decimals and Urdu digits, bullets, hyphenated line breaks, ZWNJ, diacritics, and Arabic-letter variants.
- `mini_corpora()`: 1 to 6 documents, 1 to 8 pages, built from `page_texts()`, each with a manifest entry. Embedded with `FakeEmbedder` (hashed bag-of-tokens, deterministic, cosine meaningful for overlap) and `FakeReranker` (token-overlap score).
- `queries(corpus)`: verbatim windows of existing sentences, perturbed queries, random strings, empty, overlong, and Urdu or English text.
- `llm_outputs()`: arbitrary JSON including wrong ids, extra keys, huge strings, invented numbers, injected URLs, non-JSON.

| ID | Property | Test approach |
|---|---|---|
| LIB-P1 | Every result is `answered` with at least one valid citation per claim, or `refused` with a `refusal` object | Any query on any `mini_corpora` with `FakeLLM` in normal and adversarial modes. Assert the contract invariant on the Pydantic model and validate against the JSON Schema |
| LIB-P2 | Every returned citation quote equals `page_text[span[0]:span[1]]` of the stored page, and span lies inside the page | Same generator. Re-fetch the page from the Store and compare. Includes `closest_hits` and truncated quotes |
| LIB-P3 | `search_guidance` returns at most `top_k` hits, no duplicate chunk ids, ordered by `score` descending | Random `top_k` in 1..20, random filters. Also with the reranker on, off, and failing |
| LIB-P4 | Adding an irrelevant document does not change the top-1 hit for a query with a clear match | Constrained generator (see note). Query is a verbatim window from one target chunk. Added document shares no query terms with it and has a length close to the corpus mean. Assert top-1 unchanged. Not a theorem for BM25 in general because IDF and length normalization shift. The test states its constraints and records out-of-constraint counterexamples as non-failures |
| LIB-P5 | Instructions injected into a chunk never make a result schema-invalid | Chunks get payloads from an injection list plus Hypothesis mutations. `FakeLLM` runs in `echo_injection` and `garbage` modes. Assert the result validates, P1 and P2 hold, and no claim contains a URL or number absent from its quotes |
| LIB-P6 | No committed file belongs to a document with `redistributable = false` | `scripts/check_corpus_licenses.py`. A Hypothesis test builds random manifests (random flags, tiers, missing fields) and random file trees in a temp directory. The checker verdict must equal an oracle computed from the same inputs. The script also runs on the real repo in CI |
| LIB-P7 | Chunk ids are idempotent: ingesting identical input twice gives identical ids and identical Store contents | Run the pipeline twice over `mini_corpora`. Compare ids, rows, and `stats()` |
| LIB-P8 | RRF is deterministic, independent of the order of equal-rank input, never ranks an item above one that beats it in both lists, and returns a subset of the union | Random ranked lists with ties. Also run the full retrieval twice and compare |
| LIB-P9 | Normalization is idempotent and quotes stay verbatim after it | `normalize(normalize(x)) == normalize(x)`. For any `text` and any sentence span, the quote equals the slice of normalized text |
| LIB-P10 | Refusal is monotone in the threshold: raising `τ_evid` never turns a refusal into an answer | `decide()` on random signal tuples with `τ1 < τ2`. Also end to end on `mini_corpora` with thresholds swept |
| LIB-P11 | `MemoryStore` and `PgVectorStore` agree | Contract suite and a property test on random data (Postgres-marked): same ids and order, cosine within 1e-5, same filter results, same idempotent upserts and deletes |
| LIB-P12 | Calibration (dev) and evaluation (test) question ids are disjoint, and the split matches the committed split hash | CI script on `questions.jsonl` and `calibration.json` |
| LIB-P13 | Sentence spans are valid, ordered, non-overlapping, and cover all non-whitespace characters of the text | Random `page_texts()` |
| LIB-P14 | Every claim in an answer survives only if its numbers occur in its quotes | LLM fuzz with invented numbers. Assert no surviving claim has an unsupported number |
| LIB-P15 | The LLM can only tighten a result: for any LLM output the status is no more permissive than with the extractive path's evidence gate (never `answered` when the gate refused) | Compare the verdict of `decide()` with the final status over fuzzed LLM outputs |
| LIB-P16 | Unreadable pages are never indexed | Corpora with pages classified unreadable. No chunk, vector, or BM25 posting references them |
| LIB-P17 | Filters are respected: every hit satisfies every given filter | Random filters over `mini_corpora` |
| LIB-P18 | A query with sockets disabled completes using only local state | The whole suite runs under `no_network`. A dedicated end-to-end test on the committed pack with `FakeLLM` (LIB-R11.2) |

Unit tests cover: hand-built Urdu and English sentence splitting cases, the unreadable-page rule on fixture PDFs (a clean PDF, an empty page, and a synthetic garbled one), the conflict detector on fixed sentences, and the threshold selection function.

## 12. Performance and latency budget (LIB-R8.3)

Target host: 2 vCPU, 4 GB, no GPU, Library process about 700 to 900 MB. Figures below are **estimates** from model size, not measurements. Task 18 measures them and fixes the budget if they miss.

`search_guidance`, p95 target 1.5 s, planned budget 1.0 s:

| Stage | Estimate (2 vCPU) |
|---|---|
| validate, normalize, detect language | under 5 ms |
| embed query (e5-small int8, 20 to 40 tokens) | 20 to 40 ms |
| BM25 over one language index | 5 to 20 ms |
| dense search (exact pgvector scan, 20k × 384) | 30 to 80 ms |
| RRF, dedupe, exact score fill-in | under 10 ms |
| rerank 20 pairs (int8, up to 256 tokens each) | 300 to 600 ms |
| result build, citations | under 10 ms |
| **Total** | **about 0.4 to 0.8 s** |

`answer_with_citations`, p95 target 8 s with a real LLM:

| Stage | Budget |
|---|---|
| search (above) | 1.0 s |
| scope gate, prompt build | under 50 ms |
| LLM call (network, provider) | 5.0 s, hard timeout 6.0 s |
| verification, assembly | under 100 ms |
| extractive fallback if LLM times out | 0.3 s extra (sentence rerank) |
| **Library-side total** | **about 1.5 s plus LLM** |

With `FakeLLM` the whole call is search plus under 0.2 s. The provider's latency is outside the Library's control, so the requirement is checked as "Library overhead under 2.5 s and LLM call under 5.5 s".

Measurement: `scripts/bench_library.py` runs the 50 eval questions plus 150 generated paraphrases, 3 passes, against a Library in a container started with `--cpus=2 --memory=4g` (Docker Desktop on the laptop approximates the VPS, and it is rerun on the VPS in the deployment spec). It records per-stage timers (the server logs them as structured fields), p50 and p95, and peak RSS, and writes `evals/results/library_perf.json`. `tests/perf/` holds a smoke version with a loose CI margin (3×), marked `perf`.

Memory estimate: ONNX Runtime plus two int8 models about 350 MB, BM25 and chunk cache about 60 MB, Python and libraries about 150 MB, total about 600 MB. Postgres about 200 MB. Both fit alongside the other organs, but the deployment spec sets the limits.

## 13. Security

- **Input limits.** `query` at most 1,000 characters after normalization, control characters removed, empty rejected. `top_k` in 1..20. `filters` lists at most 20 entries of at most 100 characters, matched against known values. Request body at most 16 KB.
- **SQL.** psycopg 3 with bound parameters only. Filters are `= ANY(%s)`. Table and column names are constants. A unit test greps the package for string-built SQL (`f"…SELECT`, `%` formatting, `.format(` near SQL keywords).
- **LLM output** is untrusted: schema-validated, size-limited, verified (§7).
- **Secrets.** LLM keys from environment only. Nothing in logs: the logger redacts values of variables named `*KEY*`, `*TOKEN*`, `*SECRET*`, and the DB DSN password. `.env.example` lists names only.
- **Fetch script.** Allow-listed https hosts, pinned sha256, size and type checks, filename from `doc_id`, quarantine on mismatch (§3.4).
- **PDF parsing** in a child process with timeout and memory limit, at build or fetch time only.
- **Containers.** Non-root user, read-only root filesystem except a writable temp directory and the model cache mount, DB role without superuser rights.
- **Privacy.** Queries are logged as a hash and length by default. Full text logging is behind `STITCH_LIB_LOG_QUERIES=1`.

## 14. Configuration

| Variable | Purpose | Default |
|---|---|---|
| `STITCH_LIBRARY_STORE` | `pgvector` or `memory` | `pgvector` in Compose, `memory` otherwise |
| `STITCH_LIBRARY_DSN` | Postgres DSN (no password in the repo) | unset |
| `STITCH_EMBED_MODEL` | embedding model id | `intfloat/multilingual-e5-small` |
| `STITCH_RERANK_MODEL` | reranker id, or `none` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` |
| `STITCH_RERANK_LANGS` | query languages that use the reranker | `en,ur` |
| `STITCH_MODEL_DIR` | local model cache | `/models` in the image, `data/raw/models` locally |
| `STITCH_LIB_THREADS` | ONNX intra-op threads | 2 |
| `STITCH_LLM_PROVIDER` | `fake`, `anthropic`, `openai` | `fake` |
| `STITCH_LIB_REQUIRE_LLM` | return `UPSTREAM_UNAVAILABLE` instead of extractive fallback | false |
| `STITCH_LIB_CONFLICT_POLICY` | `refuse` (`state_both` is stretch) | `refuse` |
| `STITCH_LIB_LOG_QUERIES` | log raw query text | 0 |

## 15. Decisions

| # | Decision | Alternatives rejected |
|---|---|---|
| 1 | e5-small default, bge-m3 opt-in | paraphrase-MiniLM (kept as fallback), bge-m3 as default |
| 2 | Reranker default mMARCO-mMiniLM, per-language gating, `none` fallback | bge-reranker-v2-m3 (size), jina reranker (license) |
| 3 | In-process BM25 per language | Postgres FTS, SQLite FTS5 |
| 4 | Exact pgvector search, no index, untyped vector column | HNSW from the start |
| 5 | Quotes sliced from stored text by sentence id, never produced by the LLM | LLM-written quotes verified after the fact |
| 6 | Answer text assembled from claims only | LLM free-text answer plus claim mapping |
| 7 | Conflict: refuse with both passages | state both |
| 8 | Extractive fallback by default, `REQUIRE_LLM` option | always `UPSTREAM_UNAVAILABLE` |
| 9 | Commit only documents with recorded evidence and owner confirmation, including derived artifacts | commit all public documents |
| 10 | Eval: 20 dev, 30 test, plus unreported dev-extra for calibration | tune on all 50 |
| 11 | `pypdfium2` with `pdfminer.six` fallback | PyMuPDF (AGPL) |
| 12 | `onnxruntime` + `tokenizers`, no PyTorch at runtime | `sentence-transformers` in the image |

## 16. Risks

| Risk | Mitigation |
|---|---|
| Few documents are clearly redistributable, so the committed corpus is thin and the demo cannot answer the headline question | Plan the demo questions around CDC and our own digests. Ask Sphere and NDMA for written permission early. Be explicit in the eval report about the committed share |
| Urdu PDF text is garbled or reordered | Unreadable-page rule, reorder detection, text-first translations for committed Urdu, OCR as a stretch |
| mMARCO reranker is weak or harmful for Urdu | Per-language gating from the dev check, `none` fallback, per-language thresholds |
| e5-small underperforms on Urdu | Dev comparison with paraphrase-MiniLM and bge-m3 in task 7. Switch default if it loses by a stated margin |
| 20 dev questions are too few to calibrate | `dev_extra`, pooled thresholds with a warning, conservative 3:1 cost. State the uncertainty in the eval report |
| Threshold drifts when the model or corpus changes | `calibration.json` carries model ids. Stale calibration blocks the eval and logs an error at startup |
| FakeLLM recordings go stale after a retrieval change | Missing key falls back to extractive. `record_llm_demo.py --check` lists stale keys. CI runs it |
| Conflict detector misses conflicts | Documented false negatives. Two eval items measure it. The Brain's detector is a second line |
| int8 quantization degrades quality | Parity check in `export_models.py`, fp32 fallback |
| Library memory exceeds budget | Measured in task 18. 50,000-chunk cap. Reranker can be disabled by env |
| `pg_advisory_lock` or extension setup fails on a host | Init script creates the extension. Seeder logs the exact failing step. `memory` store works with no Postgres |
| License evidence is wrong on a committed doc | Owner confirmation field, CI check, one-command removal and pack rebuild. Document the process in `data/demo/MANIFEST.md` |
| Sentence splitter errors move citation boundaries | Quote validity does not depend on correct sentence boundaries, only on spans. Accuracy tests with hand-built cases |

## 17. Proposed contract changes (not applied; steering files untouched)

1. `answer_with_citations` input: add optional `answer_lang: "en|ur"`. Today a single `lang` field must mean query language, retrieval restriction, and answer language at once.
2. `answer_with_citations` output: add `generation: { "mode": "llm|extractive", "provider": str, "model": str | null }`. The UI must be able to label extractive answers and say which model wrote the claims. Today this would only be in `warnings`.
3. `search_guidance` hit: add `chunk_id: str`, `span: [int, int]`, `title: str`, `publisher: str`. The Brain and UI need to cite a hit without a second call, and `span` makes hit text verifiable.
4. `search_guidance` input: allow `filters.lang?: ["en","ur"]` and `filters.doc_id?: [str]` (useful for tests and for fetched versus committed comparisons).
5. Clarify in section 5 that a refusal is `ok: true` and that the `NO_EVIDENCE` error code is reserved and unused by the Library.
6. `Provenance.model` is a single object, but the Library uses an embedder, a reranker, and an LLM. Either allow `models: [..]` or document the composite convention in §9.2.

Each needs the usual coupled change (steering file, `stitch_common`, consumers) and a version bump to 0.4, done by whoever owns the contract file.

## 18. Notes on `requirements.md` (not edited)

1. LIB-R1.1: pages that are neither English nor Urdu (Arabic, Persian, blank) need a state. This design uses `other` and excludes them like unreadable pages.
2. LIB-R2.3 and the contract: `lang` is one field doing three jobs. I read it as "restrict retrieval to that language, and answer in it". `auto` searches both and answers in the query language. Proposed contract change 1 separates answer language.
3. LIB-R4.3: the conflict policy is left to design. Decision in §8.6.
4. LIB-R4.5 and R9.1: a 50-question set cannot give a tuning split and an untouched evaluation split with useful sample sizes. Design adds a dev split of 20, a test split of 30, and unreported dev-extra items. Confidence intervals will be wide.
5. LIB-P4 is not a theorem for BM25 (IDF and length normalization change when a document is added). The test uses constrained generators and states them.
6. LIB-R8.3: answer latency "with a real LLM" depends on the provider. The design checks Library overhead and LLM time separately.
7. LIB-R10.1 and R10.2: derived artifacts (page text, chunks, embeddings) of a non-redistributable document are derivatives. The design treats them like the source file. The requirement should say so.
8. LIB-R1.4: `redistributable` is a bare flag. The design adds `license_evidence` and `owner_confirmed`, otherwise the flag is an assertion nobody checked.
9. LIB-R7.3: "extractive answers or `UPSTREAM_UNAVAILABLE`" leaves the choice open. Default is extractive, with an env switch.
10. LIB-R10.4 and the introduction's example question: the demo question's natural source (Sphere) is not safe to commit, so "committed subset answers every demo question" constrains which demo questions exist. See §3.2.
11. LIB-R3.3 says quotes are verbatim, and the contract caps them at 400 characters. Sentences longer than 400 need a truncation rule (§7.3 step 2).
