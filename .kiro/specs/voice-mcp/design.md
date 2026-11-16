# voice-mcp: Design

Implements `requirements.md` (VOX-R1..R9, VOX-P1..P5). Contract: `mcp-contracts.md` §7 (v0.3).

## 1. Overview

The Voice organ has two tools. `transcribe` turns a short recording into text with Whisper on CPU. `speak` turns text into audio through a pluggable TTS provider, with local caching and a character budget so a free tier is never exceeded by accident.

It is the **lowest priority organ and the first thing cut** (VOX-R8). The design therefore makes three things true:
1. **Nothing waits on Voice.** The Brain never puts Voice in a briefing's task graph. Voice is called only when a user presses Play or Record (§12).
2. **Every layer has a no-key, no-network path.** `prerendered` and `fake` providers work offline, and `transcribe` runs locally.
3. **Cutting is a configuration change**, not a code change (§11).

All logic that can be pure is pure and lives in `core/`: text normalization, sentence splitting, audio validation and joining, hallucination guards, budget arithmetic. Providers, Whisper, and storage are thin adapters. The core is what the property tests run against.

```
organs/voice/src/stitch_voice/
  core/
    audio.py         sniff and validate containers, duration limits, PCM and WAV helpers, WAV join, MP3 frame join, silence
    normalize.py     spoken-form normalization, en and ur (entry point; calls the modules below)
    numbers.py       number to words (en; ur with lakh/crore), ordinals, decimals
    units.py         unit and symbol tables (m3/s, km2, mm, %, ...)
    dates.py         ISO dates and month tables
    latin.py         the Latin-text rule for Urdu (VOX-R2.4)
    split.py         sentence splitter and chunker
    guards.py        silence, hallucination, repetition guards; language selection
    budget.py        monthly character budget arithmetic
    keys.py          cache key
  providers/
    base.py          TTSProvider protocol and result types
    azure.py  google.py  prerendered.py  local_mms.py  fake.py
  asr.py             faster-whisper wrapper, lazy load and idle unload
  store.py           AudioStore (files), BudgetStore (SQLite)
  server.py          MCP tools, envelope, error mapping
  http.py            /healthz
  settings.py        env config
tests/{unit,property,contract}/       strategies.py shares Hypothesis strategies
data/demo/voice/{scripts/en.txt, scripts/ur.txt, index.json}   audio files appear here only if allowed (§8)
scripts/prerender_demo_audio.py       dev-time, needs keys
evals/voice/                          WER eval
```

## 2. Speech-to-text: engine choice

### 2.1 Candidates on a 2 vCPU / 4 GiB host

| | faster-whisper (CTranslate2) | openai-whisper | whisper.cpp | ONNX Whisper |
|---|---|---|---|---|
| License | MIT (verified, repository LICENSE) | MIT (verified); weights released under the same repo license | MIT (stated from memory, not re-verified) | depends on the export |
| CPU speed (published benchmark, 13 min audio, `small`, 8 threads on an i7-12700K) | int8 1m42s, fp32 2m37s | fp32 6m58s | fp32 2m05s | not benchmarked in any source I could verify |
| Memory (same benchmark) | 1477 MB int8, 2257 MB fp32 | 2335 MB | 1049 MB | unknown |
| Needs system FFmpeg | **No**, it decodes with PyAV (bundled FFmpeg libraries; verified in its README) | Yes | Needs 16 kHz WAV input prepared separately | needs your own decoding |
| Runtime weight | CTranslate2 + PyAV, no PyTorch | PyTorch (large) | C++ binary or third-party Python bindings | ONNX Runtime plus a hand-written decoding loop |
| Built-in VAD | Yes (Silero VAD via `vad_filter`) | No | Recent versions have VAD support | No |
| Python integration | First-class | First-class | subprocess or bindings, different API | custom |
Source for the benchmark rows: the faster-whisper README (small model, CPU table).

**Recommendation: faster-whisper, `int8` compute type, `base` model by default.** It is the only option that is fast on CPU, avoids PyTorch and a system FFmpeg in the image (smaller image, simpler hardening), ships a VAD, and is in Python. whisper.cpp is a close second on speed and memory but needs a subprocess or a third-party binding and a separate audio-prep step. openai-whisper is about 4x slower in the same benchmark and pulls PyTorch. An ONNX path is rejected as unproven for this time-box.

Expected speed (extrapolation, **not measured**): the benchmark is 8 threads; with 2 threads the same work takes roughly 3 to 4 times longer, and `base` has about a third of `small`'s parameters. A 15 s clip should take a few seconds with `base` int8 and a handful more with `small`, comfortably under VOX-R1.5's 15 s, but task 6 measures it on the VPS size and the requirement stays unproven until then.

### 2.2 Urdu accuracy: what to expect

Whisper includes Urdu, but the smaller models are weak for it.
- A 2025 study of lightweight Whisper models on low-resource Urdu transcription (arXiv 2508.09865) reports WER of **67.08 % for `tiny`, 53.67 % for `base`, and 33.68 % for `small`** on its test set (abstract). A benchmark of Urdu ASR families (arXiv 2409.11252) finds `whisper-large` best on conversational speech. These sets differ from ours; treat them as order of magnitude.
- Consequence: with the default `base`, expect **about half of Urdu words wrong** on natural speech. English with `base` is far better, typically a small fraction of that error rate on clear speech; our own eval measures it (§10).
- Spoken Urdu and Hindi are near-identical in speech, and Whisper often labels Urdu speech as Hindi. §2.5 handles this.

Mitigations, in order of cost:
1. **Never trust the transcript.** The UI places it in the ask box, editable, with the detected language and a note "check the text", and never auto-submits (frontend design §12). A text box is always available.
2. **Bias decoding** with a short `initial_prompt` of flood vocabulary in the target language (district names, "flood", "river", "aid"). Whisper conditions on the prompt; the benefit is plausible but unmeasured, so the eval compares with and without it and the default follows the numbers.
3. **Larger model by env**: `STITCH_WHISPER_MODEL=small`, or per language `STITCH_WHISPER_MODEL_UR=small`. `small` int8 needs about 0.6 to 1 GiB RSS (unmeasured), which exceeds the 640 MiB Voice limit in the deployment budget; using it means raising the limit and running `lite` (Eyes off) on a 4 GiB host, or a bigger VPS plan. This is an owner decision once the plan is known.
4. **Cut transcription, keep speech** (§11). Reading the briefing aloud is the headline feature; the Urdu microphone is a nicety.

### 2.3 Audio input
- Input arrives as base64 in JSON (`audio_b64`, `format`, `lang_hint`). The Brain accepts up to 4 MB of JSON; the Voice tool re-validates.
- **Validation order (all pure, before any decoder runs):**
  1. Base64 decodes strictly; decoded size ≤ 10 MB (`INVALID_INPUT` otherwise).
  2. Magic bytes match the declared format: WAV `RIFF....WAVE`, WebM/Matroska `1A 45 DF A3`, Ogg `OggS`, MP3 `ID3` or an MPEG sync word. Mismatch is `INVALID_INPUT` (no guessing).
  3. Container duration (from the header via PyAV, without decoding) ≤ 60 s. If the header lies or has no duration, decoding aborts as soon as 60 s of samples (16 kHz × 60) have been produced and returns `INVALID_INPUT`. This blocks a small compressed file that expands to hours of audio.
  4. Decode to mono float32 16 kHz in a worker thread with a 10 s timeout, from memory (`BytesIO`), never from disk.
- **Format choice by the client**: the browser sends 16 kHz mono WAV (frontend design §12), which bypasses most codec risk. WebM/Opus (from `MediaRecorder` on Chromium and Firefox), OGG and MP3 are accepted through PyAV. Safari's MP4/AAC is not in the contract and is rejected with a clear message.
- FFmpeg parsers process untrusted input. Mitigations: runs in a non-root, read-only, memory-limited container; the size and duration pre-checks above; a decode timeout; no shell, no temp files.
- `INVALID_INPUT` is never retryable; a decoder crash maps to `INVALID_INPUT` with the generic message "could not decode audio", never an exception to the client (VOX-P4).

### 2.4 Silence and hallucination guard (VOX-R1.4)
Whisper hallucinates plausible text on silence or noise. Defense in layers (anecdotal practitioner reports and the faster-whisper docs support VAD plus disabling previous-text conditioning; the effect size here is measured by our own tests, not assumed):
1. **Energy gate** (`guards.energy_gate`): RMS below −50 dBFS over the whole clip returns empty text with warning `NO_SPEECH`, without running the model.
2. **VAD**: `vad_filter=True` (Silero), `min_silence_duration_ms=500`, `speech_pad_ms=400`. If total detected speech is under 0.3 s, return empty text with `NO_SPEECH`.
3. **Decoding settings**: `condition_on_previous_text=False`, `temperature=0` (fixed, so results are deterministic), `no_speech_threshold=0.6`, `log_prob_threshold=-1.0`, `compression_ratio_threshold=2.4`, `beam_size=5` (1 when `STITCH_ASR_FAST=1`).
4. **Segment filter**: drop segments with `no_speech_prob > 0.6` and `avg_logprob < -1.0`.
5. **Repetition guard**: if any 3-gram repeats more than 4 times, truncate at the second repetition and warn `REPETITION_TRIMMED`.
6. **Short-clip phrase guard**: when total speech is under 1.5 s and the entire output is one of a small list of known filler phrases (English "thanks for watching", "thank you", "subtitles by …"), return empty with `NO_SPEECH`. The list is deliberately small and English only, because Urdu words like "شکریہ" are legitimate input.
All guards except the model call are pure functions. Unit tests cover them with a fake recognizer; one integration test runs the real `tiny` model on generated silence, white noise, and a pure tone and asserts empty text.

### 2.5 Language selection
`lang_hint` is `en`, `ur`, or `auto` (default `auto`).
- `en` or `ur`: decode with that language (VOX-R1.3), `lang_confidence = 1.0`, no detection.
- `auto`: run Whisper's language identification on the first 30 s, restrict to `{en, ur, hi}`, renormalize the three probabilities. Spoken Hindi and Urdu are close, so **`hi` is mapped to `ur`** (an Urdu-speaking user is far more likely than a Hindi speaker; output is Urdu script). `lang = argmax`, `lang_confidence` = renormalized mass of that language (`ur` mass includes `hi`). If the top language overall (all 99) is neither en, ur, nor hi and its probability exceeds 0.5, return `INVALID_INPUT` "unsupported language" with `warnings: ["LANGUAGE_UNSUPPORTED:<code>"]` instead of forcing a wrong decode. Property test: mapping is total and `lang_confidence ∈ [0,1]`.

### 2.6 Resource behavior
- One transcription at a time (semaphore of 1); a second request waits up to 30 s, then returns `TIMEOUT` (retryable).
- Model loads lazily on first call and unloads after `STITCH_IDLE_UNLOAD_S` (default 300); weights are baked into the image (pinned revision and sha256 recorded in provenance `model`); no network at runtime.
- `cpu_threads=2`, `num_workers=1`.
- User audio is held only in memory for the request and dropped (VOX-R4.1). The transcript is never logged at info level (VOX-R4.2); logs carry duration, language, model, and timings only.

## 3. Speech synthesis

### 3.1 Pipeline
```
speak(text, lang, voice?, format?)
  validate (len <= 4000, lang in {en, ur}, voice allowed for provider)    -> INVALID_INPUT
  key = sha256(canonical{text, lang, voice_resolved, provider, format, pipeline_version})
  AudioStore.get(key)            -> hit: synthesized="cache"
  [prerendered store lookup]      -> hit: synthesized="prerendered"
  normalize(text, lang)           -> spoken text (core/normalize.py)
  split into chunks               -> core/split.py
  budget.reserve(chars)           -> refuse when the monthly cap would be exceeded
  provider.synthesize(chunk) for each chunk (bounded concurrency 1, rate limited)
  join chunks with pauses         -> core/audio.py
  AudioStore.put(key, audio)      -> synthesized="live"
  result { audio_b64, format, duration_s, sample_rate, lang, provider, synthesized }
```
Chain on failure (VOX-R7.6): primary provider error or missing credentials → configured fallbacks (default `prerendered` only; `google` can be added as `STITCH_TTS_FALLBACKS=google,prerendered`) → if none can serve, return `UPSTREAM_UNAVAILABLE` (retryable true for 429 and 5xx, false for credentials or cap) and the Brain shows Voice as unwell.

### 3.2 `TTSProvider` interface
```python
# interface sketch
class TTSProvider(Protocol):
    name: ProviderName                                     # azure|google|prerendered|local-mms|fake
    def supports(self, lang: Lang) -> bool: ...
    def voices(self, lang: Lang) -> list[str]: ...
    def default_voice(self, lang: Lang) -> str: ...
    def available(self) -> ProviderStatus: ...             # configured? credentials present? (no network call)
    async def synthesize(self, chunk: SpeechChunk, voice: str, fmt: AudioFormat) -> ChunkAudio: ...
        # SpeechChunk: spoken text plus pause hints; ChunkAudio: bytes, format, sample_rate, duration_s
```
The `speak` output schema is produced by the orchestrator, never by providers, so swapping providers cannot change it (VOX-P5). Providers raise typed errors (`CredentialsRejected`, `RateLimited(retry_after)`, `Upstream5xx`, `NotFound`, `UnsupportedVoice`) mapped to envelope errors in one place.

### 3.3 Providers

**`azure` (default when keys exist).**
- Azure AI Speech REST text-to-speech, not the SDK. Reasons: the SDK is a large native, closed-source wheel; REST needs only `httpx` (BSD-3, not re-verified) and keeps the image small and the license story clean.
- Request: `POST https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1` (host form from memory; the regional table in the REST doc lists the custom-voice variant, so task 5 confirms the exact standard URL with a live call), headers `Ocp-Apim-Subscription-Key`, `Content-Type: application/ssml+xml`, `X-Microsoft-OutputFormat`, `User-Agent` (required by the doc, under 255 chars). The documented requirements also cover `Authorization: Bearer` tokens; key-header auth is confirmed in task 5.
- Output formats (verified in the Audio outputs list and the sample request): `riff-24khz-16bit-mono-pcm` for `wav`, `audio-24khz-48kbitrate-mono-mp3` for `mp3`. Audio from one request is truncated at 10 minutes (verified); our chunks are far shorter.
- Voices: Urdu `ur-PK-UzmaNeural` (default, female) and `ur-PK-AsadNeural` (male alternative), both Neural category Standard per the requirements' verified facts. English default `en-GB-SoniaNeural` (a long-standing Neural voice, not verified in the current voice list; task 5 checks `GET .../cognitiveservices/voices/list` and falls back to `en-US-AriaNeural` or `en-IN-NeerjaNeural` if absent). Override with `STITCH_AZURE_VOICE_EN` and `STITCH_AZURE_VOICE_UR`.
- SSML built from a template with all text XML-escaped (`&`, `<`, `>`, quotes) so input can never inject SSML tags (property test). Pauses between sentences inside one request: `<break time="350ms"/>`. Language attribute `xml:lang="ur-PK"` or `"en-GB"`.
- Error handling: 429, 502, 503 → up to 3 attempts with exponential backoff and jitter, honoring `Retry-After` (status codes verified in the REST doc); 401 → `CredentialsRejected` (no retry, message never contains the key); 400 → `INTERNAL` with the response text redacted; timeout 20 s per chunk.
- Rate guard: token bucket `STITCH_TTS_RPM` (default 15). The free tier is reported by community posts at 20 requests per minute (not verified on an official page; the quotas page says F0 limits are not adjustable). Chunking (§3.5) keeps a 4000-character briefing to about 5 requests.

**Character budget (VOX-R7, F0 quota guard).** The free (F0) tier includes 0.5 million neural TTS characters per month (verified in the requirements' facts and several Microsoft Q&A answers). `BudgetStore` (SQLite in the `voice_cache` volume, atomic writes) keeps a counter per provider per UTC calendar month. `STITCH_TTS_MONTHLY_CHAR_CAP` defaults to 400,000 (80 % of the free allowance). Before each live request, the provider reserves `len(ssml_body)` characters (conservative: counts tags as well as text, since the billing treatment of markup is not re-verified). A reservation that would exceed the cap raises `BudgetExceeded` → `UPSTREAM_UNAVAILABLE`, message "monthly TTS character cap reached", `retryable=false`, no network call. A failed request (non-2xx) releases its reservation. Cache hits and prerendered audio cost zero. At 80 % of the cap, results carry warning `TTS_BUDGET_80PCT`. Per-request limit remains 4000 characters (VOX-R2.1). The pay-as-you-go price is not on a verified page (a Microsoft Q&A thread quotes about $15 per 1M characters); the owner confirms before enabling paid use, and the cap protects against overage if the key belongs to a paid resource. An attacker cannot burn the quota through the Brain because `/voice/speak` accepts a `briefing_id`, not arbitrary text, by default (§12).

**`google` (fallback, cuttable).** Google Cloud Text-to-Speech has **no `ur-PK` voices**: the voice list (checked) offers only `ur-IN`: `ur-IN-Standard-A/B`, `ur-IN-Wavenet-A` (female) and `ur-IN-Wavenet-B` (male), and a set of Chirp 3 HD voices. Default voice `ur-IN-Wavenet-A`; English `en-GB-Wavenet-A` (not verified). The locale mismatch (India versus Pakistan) is spoken-Urdu compatible but is disclosed in the result's provenance. Implemented over REST with a service-account token through `google-auth` as an **optional extra** (`pip install stitch-voice[google]`), not installed in the default image (to avoid pulling `grpc` and `protobuf` dependencies). Budget cap defaults to 0 (disabled until the owner sets a cap) because the free-tier amounts are not verified here.

**`prerendered`.** Read-only `AudioStore` loaded from `data/demo/voice/index.json` (and, if present, the writable `voice_cache` volume). Lookup is by `sha256(text)` and `lang` (and `voice` if requested); the provider that generated the file is recorded in the index but is not part of the lookup, so `STITCH_TTS_PROVIDER=prerendered` serves audio produced earlier by Azure. Any other text returns `NOT_FOUND` (VOX-R7.3). Reports `provider: "prerendered"`, `synthesized: "prerendered"`.

**`local-mms`.** Optional, off by default, not bundled in default images, requires `STITCH_ENABLE_LOCAL_MMS=1`, a separate Docker target with PyTorch, and an explicit THIRD_PARTY entry marking it non-commercial (VOX-R7.4). The license of the MMS TTS models is stated in the requirements as CC BY-NC and is not re-verified here. **First feature cut** if time runs short: the interface and a stub that returns `INVALID_INPUT` "provider not installed" ship, the model code does not.

**`fake`.** Deterministic synthetic audio for tests: a 16 kHz mono WAV of a sine tone whose frequency is derived from a hash of the sentence, with duration `0.06 s × spoken characters` plus the configured pauses. No network. Used by the whole test suite and by CI so the Voice path is exercised without keys. Reports `provider: "fake"`.

### 3.4 Output format policy
- Default requested format is `mp3` (small: about 6 KB per second at 48 kbps, so a 4000-character briefing is about 1.5 MB rather than 13 MB as WAV). `wav` is returned when requested, by `fake`, and by providers that cannot produce mp3. The result states the actual `format`. The frontend and Brain treat both.
- Base64 inflates by a third; the Brain's JSON limit is 4 MB on voice routes (proposed change in the Brain spec), and 4000 characters at 48 kbps fits.

### 3.5 Splitting and joining (VOX-R2.2)
- **Splitter** (`core/split.py`): runs after normalization. Sentence boundaries at `.`, `!`, `?`, newline, and the Urdu full stop `۔` (U+06D4) and question mark `؟` (U+061F). Decimal points do not split because numbers were already expanded to words; a short abbreviation list (`Dr.`, `St.`, `No.`) is protected. Sentences are grouped into **chunks of up to 800 characters** at sentence boundaries (a sentence longer than 800 is split at commas and then at word boundaries). Grouping keeps requests to a handful per briefing, which matters for the free tier's request-rate limit.
- **Pauses inside a chunk** are SSML `<break time="350ms"/>` between sentences. **Between chunks**, the joiner inserts 400 ms of silence.
- **Joining WAV**: parse each chunk with the stdlib `wave` module, assert identical sample rate, width, and channels, concatenate PCM frames plus generated zero-sample silence, write one header. Exact and trivially testable.
- **Joining MP3** (`core/audio.mp3_join`): Azure's CBR mp3 chunks share parameters, so frames concatenate into a valid stream. The joiner strips ID3v2 tags and any Xing/Info frame from each chunk, verifies that every chunk has the same MPEG version, layer, sampling rate, channel mode, and bitrate, concatenates frames, and builds the silence by emitting **zero-payload frames** (header copied from the first frame, side information and main data zeroed; such a frame decodes to silence). Duration is computed by counting frames (576 or 1152 samples per frame by version). If parameters ever differ, the joiner returns an internal error and the orchestrator re-requests the whole text as WAV. Tests decode the joined stream with PyAV (decoding, not encoding, which the default wheels support) and assert the duration within 20 ms of the sum plus pauses. MP3 *encoding* is deliberately avoided because it is not verified that the PyAV wheels carry an MP3 encoder.

## 4. Text normalization for speech (VOX-R2.3, R2.4, VOX-P2)

`normalize(text, lang) -> str` is pure, deterministic, and idempotent. It runs in this order:
1. Unicode NFC; remove control characters except newline; collapse whitespace.
2. **Strip the unspeakable**: URLs, e-mail addresses, UUIDs and hex strings of 8 or more characters, JSON pointers (`/data/forecast/3/p50`), markdown markers, bracketed citation markers (`[1]`, `[doc 12]`). Run ids and pointers should never reach Voice (the Brain builds a spoken script, §12), but the normalizer removes any that do.
3. **Dates**: ISO `YYYY-MM-DD` and `YYYY-MM-DDTHH:MM:SSZ` become "30 August 2022"; in English "thirty August two thousand twenty-two" (years 1100 to 2099 that are not round read as two pairs: "twenty twenty-two"), in Urdu "۳۰ اگست" spelled out as words with the full year read as a number (e.g., "دو ہزار بائیس"). Month names from a table (Urdu: جنوری فروری مارچ اپریل مئی جون جولائی اگست ستمبر اکتوبر نومبر دسمبر).
4. **Units and symbols**, only when adjacent to a number (so words like "m" or "mm" in prose are not touched): `m3/s`, `m³/s` → "cubic metres per second" / "کیوبک میٹر فی سیکنڈ"; `km2`, `km²` → "square kilometres" / "مربع کلومیٹر"; `mm` → "millimetres" / "ملی میٹر"; `km` → "kilometres" / "کلومیٹر"; `m` → "metres" / "میٹر"; `ha` → "hectares" / "ہیکٹر"; `%` → "percent" / "فیصد"; `PKR` and `Rs` → "rupees" / "روپے"; `kg`, `t` handled similarly. Table-driven (`units.py`), singular/plural handled where English needs it ("1 metre", "2 metres").
5. **Numbers** to words: integers, thousands separators (`1,234,567`), decimals ("point" followed by digits; Urdu "اعشاریہ"), negative, ranges `3-5`, ordinals (en only, from a small table). English uses the Western system. **Urdu uses the South Asian system (hazaar, lakh, crore)**, which is how Pakistani readers expect "1,200,000 people" ("بارہ لاکھ"). Urdu numbers 0 to 99 are irregular and come from a lookup table (`numbers.py`), then compose with سو (hundred), ہزار, لاکھ, کروڑ. The Urdu table and a sample of 30 composed numbers must be reviewed by a native speaker before the pre-render (task 3). `STITCH_VOICE_NUM_MODE=native` skips number conversion and lets the provider read digits, in case the Azure Urdu voice reads digits acceptably; task 5 listens to both and picks the default.
6. **Latin text inside Urdu** (the VOX-R2.4 rule), applied only when `lang = ur`:
   1. If the token is in the **transliteration dictionary** (`latin.py`, a small curated table of names that occur in briefings: GloFAS, Open-Meteo, Sentinel-1/2, UNOSAT, Copernicus, NDMA, PDMA, WorldPop, OpenStreetMap, Sen1Floods11, Stitch), replace it with its Urdu-script reading.
   2. Else if it is an **acronym or code** (all capitals and digits, 2 to 8 characters), **spell it** letter by letter using Urdu letter names (A "اے", B "بی", C "سی", ... Z "زیڈ"; digits already converted).
   3. Else (any other Latin word) **spell it letter by letter as well**. This is audible but unambiguous. The alternative of switching the voice mid-sentence is not available because `ur-PK` voices are not multilingual (no `<lang>` support is assumed).
   4. After this step no Latin letters remain in Urdu output; that is what makes the step idempotent.
   English text keeps Latin tokens (they are read by the English voice).
7. Final whitespace and punctuation tidy; a trailing sentence-final mark is appended if absent.

**Idempotence (VOX-P2) holds by construction**: the output of steps 3 to 6 contains no digits, no ISO dates, no unit-after-number patterns, and (for `ur`) no Latin letters, so a second pass finds nothing to rewrite, and steps 1, 2, and 7 are idempotent. A Hypothesis test checks `normalize(normalize(x)) == normalize(x)` over mixed generated text (digits, units, dates, Latin, Urdu, punctuation, control characters).

## 5. Caching and storage

- **Key** (VOX-R3.2): `sha256(canonical_json{text, lang, voice, provider, format, pipeline_version})`. `text` is the raw input; `voice` is the resolved voice; `pipeline_version` is a constant bumped when normalization or joining changes, so stale audio is never served after a rule change.
- `AudioStore`: files at `<root>/<key[:2]>/<key>.<ext>` plus a sidecar JSON with `{lang, voice, provider, format, duration_s, sample_rate, chars, generated_at, tool_version}`. Writes are atomic (temp file in the same directory, `os.replace`). Total size cap `STITCH_VOICE_CACHE_MB` (default 100) with least-recently-used eviction; **prerendered entries are never evicted** (they live in a separate read-only root).
- Roots: read-only `/app/data/demo/voice` (baked, may contain only text scripts and `index.json` if audio cannot be committed) and the read-write `voice_cache` volume (§8, Compose gets a `voice_cache` volume; proposed change to deployment).
- VOX-P3: identical `(text, lang, voice)` for the same provider and format returns byte-identical audio from the cache on the second call. With `fake`, even uncached synthesis is deterministic.

## 6. Contract mapping and errors

| Situation | Code | Retryable |
|---|---|---|
| bad base64, wrong magic bytes, over 10 MB or 60 s, undecodable, unsupported language, text over 4000 characters, unknown voice, unsupported `lang` | `INVALID_INPUT` | no |
| `prerendered` provider and text not in the index | `NOT_FOUND` | no |
| provider 429 / 5xx / timeout after retries | `UPSTREAM_UNAVAILABLE` | yes |
| credentials rejected, monthly character cap reached, no provider available | `UPSTREAM_UNAVAILABLE` | no |
| ASR queue wait over 30 s | `TIMEOUT` | yes |
| silence, no speech | `ok: true`, `text: ""`, warning `NO_SPEECH` | n/a |
| any unexpected exception | `INTERNAL` (stack trace never returned) | no |
`transcribe` and `speak` always return the envelope; they never raise to the client. Provenance: `organ: voice`; `model` is `{name: "faster-whisper:<size>", version, sha256}` for `transcribe`, `{name: "<provider>:<voice>", version, sha256: null}` for `speak`; `data_sources` lists the model and, for TTS, the provider terms identifier.

## 7. Settings (env)

| Variable | Purpose | Default |
|---|---|---|
| `STITCH_WHISPER_MODEL` | `tiny`, `base`, `small`, ... | `base` |
| `STITCH_WHISPER_MODEL_UR` | optional override for Urdu | unset |
| `STITCH_ASR_FAST` | beam 1 | `0` |
| `STITCH_TTS_PROVIDER` | `azure`, `google`, `prerendered`, `local-mms`, `fake` | `azure` in code, `prerendered` in Compose |
| `STITCH_TTS_FALLBACKS` | ordered fallbacks | `prerendered` |
| `STITCH_TTS_MONTHLY_CHAR_CAP` | Azure character cap | `400000` |
| `STITCH_TTS_RPM` | request-rate guard | `15` |
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` (and `*_FILE`) | Azure | unset |
| `STITCH_AZURE_VOICE_UR`, `STITCH_AZURE_VOICE_EN` | voice overrides | `ur-PK-UzmaNeural`, `en-GB-SoniaNeural` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google (optional extra) | unset |
| `STITCH_VOICE_NUM_MODE` | `words` or `native` | `words` |
| `STITCH_VOICE_CACHE_MB`, `STITCH_IDLE_UNLOAD_S`, `STITCH_LAZY_LOAD` | resources | 100, 300, 1 |
| `STITCH_ENABLE_LOCAL_MMS` | optional non-commercial provider | `0` |

## 8. Pre-rendering the demo briefing and the licensing question

### 8.1 Script
`scripts/prerender_demo_audio.py` (developer time only; needs keys; never runs in CI or Compose by default):
1. Reads `data/demo/voice/scripts/en.txt` and `ur.txt`, the exact spoken scripts the Brain produces for the default demo briefing. A Brain test asserts the generated script equals these files so a prerendered lookup always matches.
2. Prints characters per file and the budget impact (`--dry-run`), then calls the live provider through the normal `speak` pipeline with a fixed voice, writing `<lang>-<sha8>.mp3` and updating `index.json` with provider, voice, sha256 of text, duration, generated date, and tool version.
3. A demo script of about 1,500 characters in each language costs about 3,000 characters, under 1 % of the free allowance.

### 8.2 Is committing generated audio allowed? What I found
- Microsoft Learn Q&A answers (community and staff, **not binding terms**) say TTS output can be used commercially with no separate license; one answer distinguishes F0 from paid tiers for the commercial grant; another says not to redistribute the audio outside your application unless permitted. The answers are not consistent with each other. Sources: [commercial use thread](https://learn.microsoft.com/en-us/answers/questions/6067434/commercial-use-of-azure-text-to-speech-audio-in-a), [caching/redistribution thread](https://learn.microsoft.com/en-us/answers/questions/5596131/azure-ai-speech-terms-on-caching-redistribution-of), [prerecorded audio licensing thread](https://learn.microsoft.com/en-us/answers/questions/6053926/where-can-i-obtain-written-licensing-clarification), [Text to speech code of conduct](https://learn.microsoft.com/en-us/legal/cognitive-services/speech-service/text-to-speech/code-of-conduct) (content rights and disclosure duties), [data, privacy and security for TTS](https://learn.microsoft.com/en-us/legal/cognitive-services/speech-service/text-to-speech/data-privacy-security) (mentions disclosing synthetic voices).
- I did **not** read the binding Microsoft Product Terms or the Azure AI services terms, so I cannot confirm whether publishing the raw audio files in a public MIT repository is permitted.
- **Confidence:** about 70 % that playing generated audio inside the application is fine (all sources agree); about 40 % that committing the raw files to a public repository is clearly covered. That is not enough to commit them by default.

### 8.3 Design consequence (works whichever way the answer falls)
- Committed to the repo: the **text scripts** and `index.json` (our own work), and **fake-provider audio** (our own synthetic tones) so CI and clean-clone offline runs exercise the whole Voice path.
- **Azure audio is not committed** until the owner has read the Product Terms (gate task 8, 30 minutes) or obtained written confirmation. If cleared, run the script, commit the files with a MANIFEST row naming the provider and voice and a THIRD_PARTY entry, and set `PRERENDERED_COMMITTED=true`.
- If not cleared (or not yet checked): generate the audio **on the VPS** with the owner's key through a one-shot `voice-prerender` command into the `voice_cache` volume (`docker compose run --rm voice python -m stitch_voice.prerender --demo`), run once after deploy. Serving that audio inside the running app is the use all sources describe as allowed. The public demo then has real speech, and the repository contains none.
- A clean clone without any audio plays the `fake` tone with the provider shown honestly ("Voice: demo tones, no speech synthesized in this build"). The UI already shows the provider (FRN-R14.4).
- Disclosure: the UI labels the audio as AI-generated and names the provider; Microsoft's guidance asks for disclosure of synthetic voice use.

## 9. Properties

| ID | Statement | Test (Hypothesis, `ci` profile unless noted) |
|---|---|---|
| VOX-P1 | `duration_s > 0`, and non-decreasing when sentences are appended (same lang and voice, tolerance 50 ms) | `property/test_duration.py`: sentence lists from a strategy; provider `fake`; compare `speak(prefix)` and `speak(prefix + extra)`. A 3-pair live check with Azure exists under the `live` marker (excluded from CI). |
| VOX-P2 | `normalize` is idempotent | `property/test_normalize_idempotent.py` over mixed text; also unit tables for numbers, units, dates, Latin rule |
| VOX-P3 | identical `(text, lang, voice)` returns byte-identical audio | `property/test_cache_identity.py`: a "noisy" provider that returns different bytes on each call proves the second response comes from the cache (`synthesized: "cache"`) and is identical; `fake` is deterministic without a cache |
| VOX-P4 | oversized or malformed audio is rejected with `INVALID_INPUT`, never a crash | `property/test_audio_rejection.py`: arbitrary bytes under each declared format, truncated real files, bad base64, sizes around the limit (limit lowered through env for speed), declared-format mismatches; asserts a returned envelope, no exception, and elapsed time under the decode timeout |
| VOX-P5 | swapping providers never changes the `speak` output schema | `property/test_provider_schema.py`: the same request through `fake`, `prerendered` (fixture), `azure` (httpx `MockTransport`), and `google` (mock); every response validates against the `stitch_common` model and has the identical key set |
Additional tests: SSML injection (output parses as XML, only expected tags), WAV and MP3 join duration, silence guard (real `tiny` model on silence/noise/tone), language-mapping totality, budget arithmetic (never exceeds cap; release on failure), sentence splitter (re-joining chunks reproduces the text).

## 10. Evaluation (VOX-R6)
`evals/voice/` produces results in the bootstrap eval schema.
- **WER implementation**: our own Levenshtein over tokens (about 30 lines); no extra dependency. Text normalization before scoring: NFC; lower-case (English); remove punctuation including `،` `۔` `؟`; strip Arabic diacritics (U+064B to U+065F, U+0670); map Arabic variants to Urdu forms (ي→ی, ك→ک); convert Eastern digits to Western.
- **Test set**: 10 English and 10 Urdu utterances of flood-domain sentences (district names, "river level", "evacuation"), recorded by the owner (about 5 to 15 s each) and committed with transcripts under `evals/voice/data/` (own recordings, owner consents, license CC0). Optional larger set: a small Common Voice Urdu sample fetched by a script and not committed (its license is believed to be CC0 and must be checked before any use).
- **Metrics**: `voice.wer_en`, `voice.wer_ur`, `voice.rtf` (processing time divided by audio duration; target under 1.0), `voice.roundtrip_wer_en`, `voice.roundtrip_wer_ur`.
- **Round trip** (TTS then ASR) runs only when the provider is a real synthesizer (`azure`, `google`, `local-mms`); with `fake` or `prerendered` it reports `not_run`, because a tone or an old recording says nothing about intelligibility. Sentences come from the demo scripts.
- **Targets (honest)**: `wer_en` ≤ 0.15 with `base`; `wer_ur` is reported with target 0.45 and a note that `base` is expected to miss it based on published results (53.7 % on a comparable low-resource Urdu set); the eval also runs `small` when the model is available to give the owner a data-based choice. Every result carries `mode`, model, seed, and notes.

## 11. Time-box, go/no-go, and the cut path

### 11.1 Effort plan (about 8 h; VOX-R8.1)
| # | Work | Hours |
|---|---|---|
| 1 | Scaffold (surgeon), contract models, settings, `fake` provider, `/healthz` | 0.5 |
| 2 | AudioStore, cache key, `prerendered` provider and index, budget store | 0.75 |
| 3 | Normalization (en and ur numbers, units, dates, Latin rule), P2 | 1.25 |
| 4 | Splitter, WAV and MP3 join, P1 | 0.5 |
| 5 | Azure provider (SSML, retries, budget guard), live check with a key, voice list check | 1.0 |
| 6 | `transcribe` (validation, faster-whisper, VAD, guards, language rule), P4 | 1.25 |
| 7 | MCP server, envelope, contract tests, P3, P5 | 0.5 |
| 8 | Prerender script, licensing gate, MANIFEST and THIRD_PARTY | 0.5 |
| 9 | WER eval and recordings | 0.75 |
| | Buffer | 1.0 |
| | **Total** | **8.0** |
Not inside the 8 h: Google provider (1.5 h stretch), local-mms (cut), the Voice UI (frontend task 16, 4 h), the Brain proxy and script builder (about 1 h), and the Compose changes (about 0.5 h). Counting everything, Voice costs about 14 h end to end; VOX-R8.1's "about 8 hours" is read as the organ itself (issue list).

### 11.2 Go/no-go on Nov 28 (end-to-end criteria)
| # | Criterion | Evidence |
|---|---|---|
| E1 | In the browser, **Play** reads the demo briefing aloud in English and in Urdu through the Brain, with the provider shown, working with the network blocked | Playwright `stack` test plus manual listen |
| E2 | A live Azure synthesis succeeded for both languages and a native Urdu speaker finds it intelligible; or `prerendered` audio exists (committed, or generated on the VPS) | recorded file and owner sign-off |
| E3 | `transcribe` returns text for a 15 s English recording in under 15 s on the target VPS size, returns language `ur` for an Urdu recording (accuracy reported, not required), and returns empty text for silence | eval run output |
| E4 | The Voice container is healthy inside its memory limit and the full stack shows no OOM kill during the briefing plus one transcription | `docker stats` log |
| E5 | P1 to P5 and contract tests pass with sockets disabled | CI |
**Decision:** all of E1, E3, E4, E5 and E2 → **GO** (full Voice). Otherwise take the first matching row:
| Failing | Action |
|---|---|
| E1 (cannot play the briefing at all) | **Cut path B: Voice disabled** |
| E2 (no working Azure key or unclear terms) | **Cut path A: prerendered playback only** (audio generated on the VPS if the repo cannot hold it; `fake` tone otherwise) |
| E3 (transcribe too slow, wrong, or unstable) | **Cut path C: speak only**: microphone hidden, text input only |
| E4 (memory) | Voice moves to `tiny` or to the `lite` profile; if still failing, path B |

### 11.3 Cut paths and exactly what changes
- **A. Prerendered playback only.** Set `STITCH_TTS_PROVIDER=prerendered`. Voice still runs. `speak` works for the demo briefing text only (other text returns `NOT_FOUND`; the Brain surfaces it as "audio available for the demo briefing only"). `transcribe` stays if E3 passed. Brain: no change. UI: Play works; arbitrary-text voice features are not offered (there are none). No key is needed at runtime. Deployment: no key secrets needed.
- **B. Disabled.** Compose `lite` override (Voice not started), Brain `STITCH_ORGANS_DISABLED=voice`, `/organs` reports Voice `disabled`. UI: the Voice jar shows `disabled`, Play and Record are disabled with the text alternative (FRN-R15.2); the ask box is text-only. Tests: Voice tests are skipped through the `needs_voice` marker (VOX-R8.3); the frontend `voice-cut` Playwright scenario already covers the UI. No other spec's tests change.
- **C. Speak only.** Voice's health `meta.capabilities` lists `["speak"]` (proposed); the UI hides the microphone when `transcribe` is not a capability. The Brain's `/voice/transcribe` returns 503 with a clear message. Voice's Whisper dependency and model stay out of the image if desired (smaller image and memory): a build argument `WITH_ASR=0`.

## 12. Voice on the critical path? Risk analysis

**Is it on the critical path? No, by design.** The Brain's task graph never calls Voice (BRN-R3); Voice is invoked only from user actions (`/voice/*`), the frontend renders a disabled Voice without breaking (FRN-R15.2), and the deployment lists Voice as an optional dependency (`required: false`). The risks are about **time and resources**, not correctness of the briefing.

| Risk | Impact | Mitigation |
|---|---|---|
| Voice work consumes time needed by Brain, Library, Ledger, Oracle, Eyes | demo core late | VOX-R8.1 ordering, 8 h cap, Nov 28 checkpoint, buffer item, cut paths (§11) |
| Azure account or payment unavailable from Pakistan | no live TTS | prerendered path; owner confirms access early (deployment owner-facts list); `fake` keeps tests alive |
| Licensing of committed audio unclear | repository risk | do not commit Azure audio until cleared; generate on the VPS (§8.3) |
| Urdu transcription quality is poor with `base` | demo embarrassment | honest labelling, editable transcript, text box, optional `small`, cut path C |
| Memory: 640 MiB limit near Whisper `base` peak; host near its 4 GiB floor | OOM kills Voice or neighbors | lazy load and idle unload, `tiny` option, cgroup limit confines the damage, `lite` mode |
| Open TTS proxy burns the free quota (denial of service by cost) | no audio for the demo | `/voice/speak` takes `briefing_id`, arbitrary text disabled by default, character cap, request-rate guard, Brain rate limit |
| Key leakage | financial | env or file secret only, redaction in logs, never in error messages |
| MP3 joining glitches | audible clicks | WAV default for joined output of fake; MP3 join tested by decoding; fallback re-request as WAV |
| Urdu number and identifier reading wrong | wrong spoken facts | normalization tables reviewed by a native speaker; `native` mode comparison; Brain's spoken script avoids identifiers; numbers come from code, not from Voice |
| FFmpeg parsing of hostile audio | memory or crash | pre-validation, duration abort, container limits, non-root, timeout |
| Tests flaky because of model loading | slow CI | real-model tests are marked `slow` and run in the nightly or the stack job only; unit and property tests use `fake` |

## 13. Facts checked while writing this design
- Licenses (GitHub repository license files): faster-whisper MIT, openai/whisper MIT.
- faster-whisper README: PyAV decoding, no system FFmpeg; CPU benchmark rows for `small` (openai-whisper 6m58s fp32; whisper.cpp 2m05s fp32; faster-whisper 2m37s fp32, 1m42s int8; memory 2335, 1049, 2257, 1477 MB).
- Azure REST doc: SSML request with `Content-Type: application/ssml+xml`, `X-Microsoft-OutputFormat`, `User-Agent`; output format names `riff-24khz-16bit-mono-pcm` and `audio-24khz-48kbitrate-mono-mp3`; 10-minute audio cap; status codes 400/401/415/429/502/503.
- Free F0 tier: 0.5 million Neural TTS characters per month (Microsoft Q&A answers); F0 limits are not adjustable (quotas page snippet).
- Google Cloud TTS: Urdu is offered as `ur-IN` only (Standard, Wavenet, Chirp 3 HD); no `ur-PK`.
- Urdu Whisper accuracy: arXiv 2508.09865 (tiny 67.08 %, base 53.67 %, small 33.68 % WER) and arXiv 2409.11252 (large best on conversational speech), both from search abstracts.
- **Not verified:** the binding Microsoft terms on audio redistribution; the exact standard Azure TTS host URL and key-header auth (task 5 confirms by a live call); the pay-as-you-go price per character; the current voice list for `en-GB-SoniaNeural`; whether PyAV wheels include an MP3 encoder (avoided); PyAV, CTranslate2, httpx, and Silero VAD licenses; real speed and memory on 2 vCPU; whether Google's free-tier amounts still apply; the F0 request-rate limit from an official page.

## Proposed contract changes
1. **`speak` output: add optional `voice: str`** (the resolved voice name). The UI and provenance disclosure use it; today only `provider` is reported. Backward compatible; bump to 0.4.
2. **Brain API** (brain spec, not `mcp-contracts.md` tools): `POST /voice/speak` takes `{briefing_id, lang, voice?}` and builds the spoken script on the server from the stored briefing; arbitrary `{text}` is accepted only when `STITCH_ALLOW_ARBITRARY_TTS=1` (off by default, to protect the quota). A deterministic script builder (claims to speakable sentences without ids or pointers) lives in the Brain, and `data/demo/voice/scripts/{en,ur}.txt` must equal its output for the demo briefing (a Brain test).
3. **Organ health `meta`**: `/healthz` of Voice returns `{capabilities: ["speak","transcribe"], tts_provider, hosted: bool, whisper_model}`, and the Brain forwards it in `GET /organs`.
4. **Brain limits**: JSON body up to 4 MB on `/voice/transcribe`; `/voice/*` rate-limited per client.
5. **Compose**: a `voice_cache` volume and the env variables in §7 (deployment design).
6. **Warning codes** on `transcribe` (`NO_SPEECH`, `REPETITION_TRIMMED`, `LANGUAGE_UNSUPPORTED:<code>`) and `speak` (`TTS_BUDGET_80PCT`) documented as stable strings in §7 of the contracts.
