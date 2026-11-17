# voice-mcp: Requirements

Organ: speech-to-text and text-to-speech, Urdu and English. Prefix `VOX`. Contract: `mcp-contracts.md` §7. Priority: **cuttable** (lowest), time-boxed (VOX-R8).

## Introduction
The Voice transcribes spoken questions (Whisper) and speaks the briefing (TTS) in Urdu or English.

## Requirements

### VOX-R1 Transcription
1. WHEN `transcribe` is called with valid audio, THE Voice SHALL return text, detected language, timestamped segments, and `lang_confidence`, using Whisper on CPU by default, or Deepgram Nova-3 when `STITCH_STT_PROVIDER=deepgram` and a key is set (revision R-DG below).
2. THE Voice SHALL accept `wav`, `webm`, `mp3`, and `ogg` of at most 60 s and 10 MB, and return `INVALID_INPUT` otherwise.
3. WHERE `lang_hint` is given, THE Voice SHALL use it to constrain decoding.
4. IF the audio is silent or contains no speech, THEN THE Voice SHALL return empty text with a warning and not hallucinate text.
5. THE Voice SHALL complete a 15 s clip in under 15 s on 2 vCPU using the configured Whisper size.

### VOX-R2 Speech synthesis
1. WHEN `speak` is called with text of at most 4000 characters and `lang` of `en` or `ur`, THE Voice SHALL return audio with duration, sample rate, and format.
2. THE Voice SHALL split long text at sentence boundaries, synthesize each part, and join them with short pauses.
3. THE Voice SHALL normalize numbers, units (e.g. "m3/s", "km2"), and dates into spoken words in the target language before synthesis.
4. IF `lang = ur` and text contains Latin-script identifiers, THEN THE Voice SHALL read them in a defined fallback (spell out or transliterate), documented in design.
5. IF the requested language lacks a configured voice, THEN THE Voice SHALL return `INVALID_INPUT` and not silently use another language.

### VOX-R3 Offline and cache
1. THE Voice SHALL run Whisper speech-to-text locally on CPU, with the model size set by `STITCH_WHISPER_MODEL` (default `base`, `tiny` supported, larger sizes opt-in).
2. THE Voice SHALL cache synthesized audio by hash of (text, lang, voice, provider) and ship pre-rendered demo-briefing audio (Urdu and English) so the demo works offline. The pre-rendered audio SHALL only be committed if the TTS provider terms permit redistribution of generated audio, and the provider SHALL be named in THIRD_PARTY.md.
3. WHERE the Voice organ is disabled or unavailable, THE system SHALL still produce a text briefing and show the Voice as unwell without blocking the other organs.

### VOX-R4 Safety and privacy
1. THE Voice SHALL not persist user audio beyond the request.
2. THE Voice SHALL not log transcribed text at info level.
3. THE Voice SHALL send only briefing text (never user audio) to a hosted TTS provider, and the UI SHALL disclose this before first use.

### VOX-R5 Ops
1. THE Voice SHALL expose `GET /healthz` and a `Provenance` block with model names and hashes.

### VOX-R6 Eval
1. THE Voice eval SHALL report word error rate (WER) for English and Urdu on a small recorded or public test set, and a TTS intelligibility check by round-trip (TTS then ASR) WER.

### VOX-R7 Pluggable TTS providers
1. THE Voice SHALL define a `TTSProvider` interface and select the provider with `STITCH_TTS_PROVIDER`. Values: `deepgram` (English, default when keyed), `azure` (Urdu), `google` (fallback), `prerendered`, `local-mms` (optional, off by default), and `fake`.
2. THE `azure` provider SHALL call Azure Neural TTS with `ur-PK-UzmaNeural` (default Urdu voice, `ur-PK-AsadNeural` as the male alternative) and an English neural voice. THE `google` provider SHALL implement the same interface as a fallback. Keys are read from env (`AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, and Google application credentials) and never committed. Deepgram (`DEEPGRAM_API_KEY`) was added by the owner in Nov 2026 (revision R-DG); other vendors are out of scope.
3. THE `prerendered` provider SHALL serve only the cached demo audio and return `NOT_FOUND` for other text, so the offline demo works with no key or network.
4. THE `local-mms` provider (non-commercial model license) SHALL be disabled unless explicitly enabled, SHALL NOT be bundled in default images, and SHALL be listed in `THIRD_PARTY.md` as an optional non-commercial mode.
5. WHEN the provider changes, THE `speak` output schema SHALL NOT change, and `provider` (`azure`, `google`, `prerendered`, `local-mms`, or `fake`) and `synthesized` (`live`, `cache`, or `prerendered`) SHALL be reported.
6. IF the hosted provider fails or no key is set, THEN THE Voice SHALL fall back to `prerendered` for demo text, otherwise return `UPSTREAM_UNAVAILABLE` and the Brain SHALL show Voice as unwell.

### VOX-R8 Time-box
1. THE Voice work SHALL start only after Brain, Library, Ledger, Oracle, and Eyes core tasks are complete, and the total Voice effort SHALL be capped at about 8 hours.
2. THE go/no-go checkpoint is **Nov 28**. IF Voice is not working end to end by then (transcribe plus speak through the Brain and UI), THEN THE team SHALL switch to pre-rendered audio for the demo briefing (Whisper transcribe kept only if already working), or disable Voice entirely, with the UI showing Voice as disabled.
3. Cutting Voice SHALL NOT break any other spec's tests or the demo.

### VOX-R9 Demo-first
1. `transcribe` SHALL work offline (local Whisper). `speak` SHALL work offline for the pre-rendered demo briefing.
2. THE tests SHALL run with sockets disabled and a fake TTS provider.

## Correctness properties (formalized in design)
- VOX-P1: `speak` output duration is > 0 and monotone non-decreasing in text length (for the same language and voice, within a tolerance).
- VOX-P2: text normalization is idempotent.
- VOX-P3: caching returns byte-identical audio for identical (text, lang, voice).
- VOX-P4: oversized or malformed audio is rejected with `INVALID_INPUT`, never a crash.

- VOX-P5: swapping TTS providers never changes the `speak` output schema.

## Out of scope
Voice cloning. Real-time streaming conversation. Speaker diarization.

## Decisions (resolved)
1. Default TTS is a hosted API behind a pluggable interface. A non-commercial local model would create a license mismatch with the MIT repo, so it is an optional local mode, off by default, listed in THIRD_PARTY.md.
2. Azure Neural TTS is the default vendor and Google Cloud TTS the fallback. ElevenLabs is excluded (cost). Whisper `base` by default, `tiny` allowed, size set by env.
3. Voice is time-boxed and the first thing cut if the schedule slips.

## Verified facts (Microsoft Learn language-support and Azure pricing pages, checked Nov 2026)
- `ur-PK` has Neural voices `ur-PK-UzmaNeural` (female) and `ur-PK-AsadNeural` (male), category Standard.
- The Free (F0) Speech tier includes 0.5 million Neural TTS characters per month. A demo briefing is a few thousand characters, so pre-rendering demo audio and light live use fit the free tier.
- The pay-as-you-go per-character price did not render on the fetched pricing page. Confirm it in the Azure portal before enabling paid use.

## Open checks (before committing pre-rendered audio)
1. Confirm Azure's terms allow committing generated audio to a public MIT repo. If they do not, the pre-rendered files are generated at image build time from a key, or the demo falls back to text with live synthesis only.
2. Confirm a Pakistan-accessible Azure account can use the Speech resource, and pick a region.
## Revision R-DG: Deepgram (owner decision, Nov 2026)
Deepgram is the owner's hosted voice API. Verified against Deepgram docs and a live probe: Aura-2 TTS speaks English, Spanish, German, French, Dutch, Italian, Japanese only (no Urdu); Nova-3 STT supports `en` and monolingual `ur`.
- VOX-R10.1 WHEN `STITCH_STT_PROVIDER=deepgram` and `DEEPGRAM_API_KEY` is set, THE Voice SHALL transcribe with Nova-3 (`language` from `lang_hint`, `ur` or `en`; `auto` uses `detect_language`), otherwise with local Whisper. A Deepgram failure SHALL fall back to local Whisper with a warning.
- VOX-R10.2 English `speak` SHALL use Deepgram Aura-2 (`STITCH_DEEPGRAM_VOICE_EN`, default `aura-2-thalia-en`) when keyed. Urdu `speak` SHALL use Azure `ur-PK-UzmaNeural` when `AZURE_SPEECH_KEY` is set, else prerendered audio, else `UPSTREAM_UNAVAILABLE` with the warning "Urdu speech needs Azure; Urdu text briefing is shown". Urdu SHALL never be synthesized with an English voice.
- VOX-R10.3 Deepgram STT sends user audio to a hosted service. This amends VOX-R4.3: it is opt-in by env, every request sets `mip_opt_out=true`, and the UI disclosure SHALL name Deepgram for the microphone.
- VOX-R10.4 Paid calls SHALL pass a monthly budget guard (characters for TTS, seconds for STT); over the cap no request is sent.
- VOX-R10.5 Deepgram's terms do not clearly permit redistributing generated audio, so prerendered audio SHALL be generated at build or deploy time into a git-ignored cache and not committed (`docs/decisions.md`).