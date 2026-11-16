# voice-mcp: Tasks

Tags: `core` (must ship if Voice ships), `stretch`, `cuttable`, `gate` (a decision point), `owner` (needs the repo owner). Each task lists the requirements and properties it satisfies, the tests that prove it, a "Done when", and hours. Commit after each task (`feat(voice): ...`).

**Time-box (VOX-R8):** tasks 1 to 9 plus buffer are the capped 8 h. Voice starts only after Brain, Library, Ledger, Oracle, and Eyes core tasks are complete. **Go/no-go checkpoint: Nov 28** (task 11). Integration work (tasks 10) is counted separately.

Blocked by: **bootstrap** (`stitch_common` Voice models and envelope, `surgeon`, hooks, shared test plugin). Task 10 needs the Brain and the frontend.

## Hour budget

| Task | Hours | Counts toward the 8 h cap |
|---|---|---|
| 1 Scaffold, models, settings, `fake` provider | 0.5 | yes |
| 2 AudioStore, cache key, `prerendered`, budget store | 0.75 | yes |
| 3 Text normalization | 1.25 | yes |
| 4 Splitter and audio joining | 0.5 | yes |
| 5 Azure provider | 1.0 | yes |
| 6 `transcribe` | 1.25 | yes |
| 7 MCP server, contract tests, P3 and P5 | 0.5 | yes |
| 8 Prerender script and licensing gate | 0.5 | yes |
| 9 WER eval and recordings | 0.75 | yes |
| Buffer | 1.0 | yes |
| **Subtotal (capped)** | **8.0** | |
| 10 Integration (Brain proxy and script, Compose, UI) | about 6 (1 Brain, 0.5 Compose, 4 frontend task 16, 0.5 test) | no (other specs) |
| 11 Go/no-go checkpoint | 0.5 | no |
| 12 Google provider | 1.5 | no (stretch) |
| 13 `local-mms` stub and docs | 0.5 | no (cuttable) |
| 14 Documentation and write-up | 0.5 | no |

## Minimal path (if time runs out)
Tasks 1, 2, 3 (English numbers and units, Urdu minimum: digits and units tables), 4, 7, 8 with the `fake` provider and `prerendered` playback, then 10 (Brain proxy and UI Play). That is about 4 h of organ work and gives **cut path A** (prerendered playback only) with no key and no Whisper. Add task 6 (`transcribe`) if the clock allows, task 5 (Azure) if the owner has a working key.

**Cut order inside Voice (first cut first):** (1) task 13 `local-mms` (stub only); (2) task 12 Google; (3) task 9 round-trip eval (keep WER from recordings); (4) Urdu `native` number mode comparison; (5) task 6 `transcribe` (cut path C: speak only); (6) task 5 Azure live synthesis (cut path A: prerendered only); (7) everything (cut path B: disabled, per design §11.3). Cutting Voice must not break any other spec's tests (VOX-R8.3).

## Tasks

- [ ] **1. Scaffold the organ with `surgeon`, models, settings, `fake` provider** `core` (0.5 h)
  - Generate `organs/voice/` (pyproject with extras `google` and `local-mms`, `src/stitch_voice`, tests). Wire `stitch_common` Voice models. `settings.py` with the env table (design §7). `/healthz` returning `capabilities`, `tts_provider`, `hosted`, `whisper_model`.
  - `providers/base.py` (protocol, typed errors) and `providers/fake.py` (deterministic tone WAV, duration proportional to spoken characters).
  - Tests: import, healthz, `fake` determinism, `no_network` fixture on by default. Refs: VOX-R5.1, R7.1, R7.5, R9.2.
  - Done when: `uv run pytest` is green on the skeleton and `fake` is selectable by env.

- [ ] **2. AudioStore, cache key, `prerendered` provider, budget store** `core` (0.75 h)
  - `core/keys.py` (canonical JSON hash including `pipeline_version`), `store.py` (`AudioStore` with atomic writes, LRU eviction, separate read-only prerendered root; `BudgetStore` in SQLite), `core/budget.py` (reserve, release, monthly rollover by UTC month, 80 % warning), `providers/prerendered.py` (index lookup by text hash and language; `NOT_FOUND` otherwise).
  - Tests: atomic write (kill mid-write leaves no partial file), eviction never touches prerendered entries, budget never exceeds the cap under concurrent reservations, month rollover with an injected clock, release after failure. Refs: VOX-R3.2, R7.3, R7.5, VOX-P3 (store part).
  - Done when: a cache hit returns identical bytes and `NOT_FOUND` is returned for unknown text.

- [ ] **3. Text normalization for speech** `core` (1.25 h)
  - `core/numbers.py` (English; Urdu with the lakh and crore system, irregular 0 to 99 table), `units.py`, `dates.py`, `latin.py` (dictionary, acronym spelling, letter-by-letter spelling, no Latin remains in Urdu output), `normalize.py` (order in design §4).
  - **Owner step (15 min, can be asynchronous):** a native Urdu speaker reviews the number table, 30 composed sample numbers, the units, the month names, and the letter names.
  - Tests: table-driven unit tests per rule (including `m3/s`, `m³/s`, `km2`, `1,234,567`, decimals, ISO dates, `GloFAS`, `NDMA`); property **VOX-P2** idempotence on mixed generated text; unit test that unspeakables (URLs, UUIDs, JSON pointers, `[1]`) are stripped. Refs: VOX-R2.3, R2.4, VOX-P2.
  - Done when: P2 passes under `ci`, and the English and Urdu sample sentences produce the expected spoken forms in the review sheet.

- [ ] **4. Sentence splitter and audio joining** `core` (0.5 h)
  - `core/split.py` (boundaries including `۔` and `؟`, protected abbreviations, 800-character chunks, long-sentence fallback), `core/audio.py` (WAV join with silence via `wave`; MP3 frame join with ID3/Xing stripping, parameter check, zero-payload silence frames, frame-count duration).
  - Tests: splitter rejoin reproduces the text; WAV join duration equals the sum plus pauses; MP3 join decoded with PyAV matches the sum plus pauses within 20 ms and has no decode errors; mismatched parameters raise the typed error; **VOX-P1** duration positivity and monotonicity with `fake`. Refs: VOX-R2.2, VOX-P1.
  - Done when: P1 passes and a joined MP3 of five chunks decodes cleanly.

- [ ] **5. Azure provider** `core` (1.0 h) *(live parts need `AZURE_SPEECH_KEY`)*
  - `providers/azure.py` per design §3.3: SSML template with XML escaping, regional host, `Ocp-Apim-Subscription-Key` auth, output formats `riff-24khz-16bit-mono-pcm` and `audio-24khz-48kbitrate-mono-mp3`, retries with `Retry-After` for 429 and 5xx, `CredentialsRejected` for 401, request-rate token bucket, character budget reservation, 20 s timeout, secrets never in messages or logs.
  - Live checks (marker `live`, run by hand, never in CI): confirm the standard host URL and key-header auth; list voices from the voices endpoint and confirm `ur-PK-UzmaNeural`, `ur-PK-AsadNeural`, and the English default (else choose an alternative and update the default); listen to Urdu with `words` versus `native` number mode and set the default.
  - Tests (CI, no network): httpx `MockTransport` for success, 429 then success, 401, 503 exhaustion, timeout; SSML injection property (output parses as XML and contains only expected tags); budget refusal makes zero HTTP calls. Refs: VOX-R2.1, R7.2, R7.5, R7.6, R4.3, **VOX-P5** (Azure leg).
  - Done when: mock tests pass; if a key is available, one real English and one real Urdu chunk are synthesized and audible (record the result in `docs/`).

- [ ] **6. `transcribe`: validation, decoding, faster-whisper, guards, language** `core` (1.25 h)
  - `core/audio.py` validation (base64, size, magic bytes, header duration, decode abort at 60 s, from memory, timeout), `core/guards.py` (energy gate, segment filter, repetition trim, short-phrase guard, language selection with `hi` mapped to `ur`), `asr.py` (faster-whisper `int8`, `cpu_threads=2`, VAD, `condition_on_previous_text=False`, temperature 0, lazy load, idle unload, one-at-a-time semaphore, optional per-language model, optional `initial_prompt`).
  - Tests: **VOX-P4** (`property/test_audio_rejection.py`: arbitrary bytes per declared format, truncated real files, bad base64, boundary sizes with a lowered limit, format mismatch, a tiny compressed file declared longer than 60 s; asserts an envelope, no exception, bounded time); guards unit tests with a fake recognizer; one `slow` integration test with the real `tiny` model on silence, white noise, and a tone (empty text), and on a short English fixture (non-empty); language mapping totality property. Refs: VOX-R1.1 to R1.4, R3.1, R4.1, R4.2, VOX-P4.
  - Measure on the dev laptop and, when available, the VPS: real-time factor for `tiny`, `base`, `small` on a 15 s clip (VOX-R1.5). Record in `docs/`.
  - Done when: P4 passes, silence and noise return empty text with `NO_SPEECH`, and the 15 s English clip transcribes in under 15 s with `base` on a 2 vCPU limit (`docker run --cpus 2`).

- [ ] **7. MCP server, envelope, contract tests, P3, P5** `core` (0.5 h)
  - `server.py` with `transcribe` and `speak`, error mapping (design §6), provenance (`model`, `data_sources`), provider chain with fallbacks, `/healthz`, stdio and HTTP transports.
  - Tests: contract tests (inputs and outputs validate with `additionalProperties: false`); **VOX-P3** (noisy provider proves cache identity); **VOX-P5** (identical schema across `fake`, `prerendered`, `azure` mock, `google` mock); smoke test starting the server, listing tools, calling both. Refs: VOX-R1, R2, R5, R7.5, R7.6, VOX-P3, VOX-P5.
  - Done when: the `on-save-contract-validate` hook passes and P3 and P5 are green.

- [ ] **8. Pre-render script and licensing gate** `core` + `gate` + `owner` (0.5 h)
  - `scripts/prerender_demo_audio.py` (`--dry-run` prints characters and budget impact; writes `<lang>-<sha8>.<ext>` and `index.json` with provider, voice, text hash, duration, date, tool version). `data/demo/voice/scripts/en.txt` and `ur.txt` are produced from the Brain's script builder (task 10) or hand-written first and checked later.
  - **Gate (owner, 30 min):** read the Microsoft Product Terms and the Azure AI services terms for Speech output (links in design §8.2). Decide: (a) cleared in writing: run the script, commit the audio, add MANIFEST and THIRD_PARTY rows naming Azure and the voices, set the flag; (b) not cleared or not checked: do **not** commit Azure audio; generate on the VPS after deploy with `docker compose run --rm voice python -m stitch_voice.prerender --demo`; commit only the scripts, `index.json` without audio, and `fake`-provider audio so clean-clone offline runs still exercise the path.
  - Tests: dry run output is deterministic; `index.json` schema; every audio file in `data/demo/voice` appears in the MANIFEST (also checked by the deployment hygiene script); a Brain test (task 10) asserting the script text equals the committed files. Refs: VOX-R3.2, R7.3, R4.3, DEP-R8.1.
  - Done when: the gate decision is written in `docs/voice-licensing.md` with the evidence consulted, and the demo briefing has playable audio in the chosen way.

- [ ] **9. WER eval and recordings** `core` (0.75 h) *(cut the round trip first)*
  - `evals/voice/`: own WER function with Urdu normalization (design §10), the 10 English and 10 Urdu recorded utterances with transcripts (owner records; 15 min), `rtf`, and the round trip for real synthesizers only (`not_run` otherwise). Compare `base` and `small` (and `initial_prompt` on or off) when models are present. Write results in the bootstrap schema with targets and notes (Urdu target 0.45 stated as expected to miss with `base`).
  - Tests: WER unit tests (identical text 0, full substitution 1, insertions), normalization tests (diacritics, Arabic yeh and kaf, digit mapping), reproducibility with `--seed 0`. Refs: VOX-R6.
  - Done when: `python -m evals.run --organ voice --fast --seed 0` writes results with real numbers and the dashboard shows them.

- [ ] **10. Integration: Brain proxy and script, Compose, UI** `core` for the proxy and UI Play, `cuttable` for the microphone (about 6 h across specs)
  - Brain (brain spec): `POST /voice/speak {briefing_id, lang}` with the deterministic script builder; `POST /voice/transcribe` (4 MB JSON limit); forward Voice `meta` in `/organs`; `STITCH_ORGANS_DISABLED`; arbitrary-text TTS off by default; rate limits. Tests: script equals the committed `scripts/{en,ur}.txt` for the demo briefing.
  - Deployment: `voice` service with the 640 MiB limit, `voice_cache` volume, env, `required: false` dependency, `lite` override.
  - Frontend (frontend task 16): Play, disclosure dialog, provider and voice label, Record (WAV via AudioWorklet), text fallback, disabled state. Update the frontend to send `{briefing_id, lang}` instead of text.
  - Tests: Playwright `stack` run of Play in both languages with the network blocked; `voice-cut` scenario.
  - Done when: E1 in design §11.2 holds.

- [ ] **11. Go/no-go checkpoint, Nov 28** `gate` (0.5 h)
  - Evaluate E1 to E5 (design §11.2). Write the outcome in `docs/voice-checkpoint.md`: GO, or the cut path taken (A prerendered only, B disabled, C speak only), with the evidence (test output, `docker stats`, listening notes) and the exact configuration change. Apply the cut by configuration (§11.3), update the UI states, and confirm the full test suites of the other specs still pass.
  - Done when: the decision and its evidence are committed and the stack runs in the chosen configuration.

- [ ] **12. Google provider (fallback)** `stretch` (1.5 h)
  - `providers/google.py` over REST with service-account auth through the optional `google` extra; default voice `ur-IN-Wavenet-A` and an English Wavenet voice; same budget and rate guards with the cap defaulting to 0; provenance notes the `ur-IN` locale. Not installed in the default image.
  - Tests: mock transport success and failure, schema equality with other providers (P5), the extra is absent from the default image (`check_images.py`). Refs: VOX-R7.1, R7.2, R7.5.
  - Done when: the mock tests pass; a live Urdu sample is audible if credentials exist.

- [ ] **13. `local-mms` stub and documentation** `cuttable` (0.5 h)
  - Provider stub that is disabled unless `STITCH_ENABLE_LOCAL_MMS=1`, returns `INVALID_INPUT` "provider not installed" when the extra is absent, separate Docker target not built by default, THIRD_PARTY entry marking the models as non-commercial (CC BY-NC per the requirements; re-verify the model card before enabling). Refs: VOX-R7.1, R7.4.
  - Done when: the default image has no PyTorch and the stub test passes.

- [ ] **14. Documentation and write-up** `core` (0.5 h)
  - `organs/voice/README.md` (tools, env, providers, limits, privacy, cut paths), `docs/voice-licensing.md`, `docs/voice-checkpoint.md`, THIRD_PARTY rows (faster-whisper, CTranslate2, PyAV, httpx, Silero VAD, Whisper weights, Azure Neural TTS, voices used), and the `docs/kiro-writeup.md` entry on time-boxing a cuttable organ with a spec-driven decision gate.
  - Done when: a reader can run Voice with `fake`, with `prerendered`, and with Azure from the README.

## Traceability

| Requirement | Tasks |
|---|---|
| VOX-R1 | 6 |
| VOX-R2 | 3, 4, 5 |
| VOX-R3 | 2, 6, 8, 10 |
| VOX-R4 | 5, 6, 8 |
| VOX-R5 | 1, 7 |
| VOX-R6 | 9 |
| VOX-R7 | 1, 2, 5, 7, 8, 12, 13 |
| VOX-R8 | 11, 10, minimal path above |
| VOX-R9 | 1, 6, 7, 10 |

| Property | Task | Test file |
|---|---|---|
| VOX-P1 | 4 | `property/test_duration.py` |
| VOX-P2 | 3 | `property/test_normalize_idempotent.py` |
| VOX-P3 | 2 (store), 7 | `property/test_cache_identity.py` |
| VOX-P4 | 6 | `property/test_audio_rejection.py` |
| VOX-P5 | 5 (Azure leg), 7, 12 | `property/test_provider_schema.py` |
