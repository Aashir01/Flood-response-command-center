# voice-mcp: Requirements

Organ: speech-to-text and text-to-speech, Urdu and English. Prefix `VOX`. Contract: `mcp-contracts.md` §7. Priority: **cuttable** (lowest).

## Introduction
The Voice transcribes spoken questions (Whisper) and speaks the briefing (TTS) in Urdu or English.

## Requirements

### VOX-R1 Transcription
1. WHEN `transcribe` is called with valid audio, THE Voice SHALL return text, detected language, timestamped segments, and `lang_confidence`, using Whisper on CPU.
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
1. THE Voice SHALL run fully on CPU with locally stored models (no external API required).
2. THE Voice SHALL cache synthesized audio by hash of (text, lang, voice) and ship pre-rendered demo-briefing audio so the demo works if TTS is disabled.
3. WHERE the Voice organ is disabled or unavailable, THE system SHALL still produce a text briefing and show the Voice as unwell without blocking the other organs.

### VOX-R4 Safety and privacy
1. THE Voice SHALL not persist user audio beyond the request.
2. THE Voice SHALL not log transcribed text at info level.

### VOX-R5 Ops
1. THE Voice SHALL expose `GET /healthz` and a `Provenance` block with model names and hashes.

### VOX-R6 Eval
1. THE Voice eval SHALL report word error rate (WER) for English and Urdu on a small recorded or public test set, and a TTS intelligibility check by round-trip (TTS then ASR) WER.

## Correctness properties (formalized in design)
- VOX-P1: `speak` output duration is > 0 and monotone non-decreasing in text length (for the same language and voice, within a tolerance).
- VOX-P2: text normalization is idempotent.
- VOX-P3: caching returns byte-identical audio for identical (text, lang, voice).
- VOX-P4: oversized or malformed audio is rejected with `INVALID_INPUT`, never a crash.

## Out of scope
Voice cloning. Real-time streaming conversation. Speaker diarization.

## Open questions
1. TTS engine for Urdu on CPU: candidates are Piper (limited Urdu), MMS-TTS (Meta, CC-BY-NC), Coqui XTTS (non-commercial license), or a hosted API as fallback. License matters for a public repo. Proposal: MMS-TTS `urd-script_arabic` for Urdu and Piper for English, with licenses disclosed. Is non-commercial acceptable?
2. Whisper size: `small` for Urdu quality, or `base` for speed?
