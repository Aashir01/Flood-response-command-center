# voice-mcp

The Voice organ of Stitch: speaks the briefing and transcribes short spoken questions, in English
and Urdu. Contract v0.5, `.kiro/steering/mcp-contracts.md` section 7. Priority: cuttable. If Voice
is off or unwell, the Brain still produces the text briefing.

## Tools

| Tool | Input | Output |
|---|---|---|
| `speak` | `text` (at most 4000 characters), `lang` `en` or `ur`, optional `voice`, `format` | WAV as base64, `duration_s`, `sample_rate`, `provider`, `synthesized` (`live`, `cache`, `prerendered`), `voice` |
| `transcribe` | `audio_b64` (wav, webm, mp3, ogg; at most 60 s and 10 MB), optional `lang_hint` | `text`, `lang`, `segments`, `lang_confidence` |

All audio is AI-generated (Deepgram terms 3.5(c)); the UI must say so and name the provider.
`speak` always returns WAV; a request for `mp3` gets WAV and the warning `FORMAT_WAV_ONLY`.

## Providers

| Language | Speech synthesis, in order | Speech recognition |
|---|---|---|
| English | Deepgram Aura-2 (`aura-2-thalia-en`, 24 kHz) when `DEEPGRAM_API_KEY` is set, then the prerendered cache | Deepgram Nova-3 when `STITCH_STT_PROVIDER=deepgram` and keyed, then local faster-whisper |
| Urdu | Azure `ur-PK-UzmaNeural` when `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` are set, then the prerendered cache, else `UPSTREAM_UNAVAILABLE` with the warning "Urdu speech needs Azure; Urdu text briefing is shown" | Nova-3 (`language=ur`) or faster-whisper |

Deepgram has no Urdu voice, and Urdu is never read by an English voice (asking for an English
voice with `lang: ur` is `INVALID_INPUT`). Without Azure, Urdu speech works only for text that is
in the prerendered cache, and the prerender script cannot fill it for Urdu.

Every Deepgram request sets `mip_opt_out=true`. Deepgram STT sends the user's audio to a hosted
service, so it is opt-in. User audio is never written to disk, and transcripts are not logged.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `STITCH_TTS_PROVIDER` | `deepgram` | `deepgram` (with Azure for Urdu when keyed), `prerendered` (cache only), `fake` (tones, tests) |
| `STITCH_STT_PROVIDER` | `whisper` | `deepgram` (Nova-3, falls back to Whisper), `whisper`, `fake` |
| `DEEPGRAM_API_KEY` | unset | Deepgram key (or `DEEPGRAM_API_KEY_FILE`) |
| `STITCH_DEEPGRAM_VOICE_EN` | `aura-2-thalia-en` | English voice |
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | unset | Urdu speech |
| `STITCH_WHISPER_MODEL` | `base` | faster-whisper size; never downloaded at runtime unless `STITCH_WHISPER_DOWNLOAD=1` |
| `STITCH_VOICE_CACHE_DIR` | `data/cache/voice` | synthesized-audio cache and budget database (git-ignored) |
| `STITCH_VOICE_PRERENDERED_DIR` | `<cache>/prerendered` | prerendered demo audio and `index.json` |
| `STITCH_TTS_MONTHLY_CHAR_CAP` | `200000` | paid TTS characters per provider per UTC month; over the cap no request is sent |
| `STITCH_STT_MONTHLY_SECONDS_CAP` | `3600` | paid STT seconds per provider per UTC month |

## Run

```
uv sync --all-packages
uv run python -m stitch_voice.server --stdio                 # stdio (Kiro, Brain)
uv run python -m stitch_voice.server --http --port 8000      # streamable HTTP and GET /healthz
uv run python scripts/mcp_probe.py voice-mcp --timeout 180
```

Three ways to run it:

* No key, offline: `STITCH_TTS_PROVIDER=fake STITCH_STT_PROVIDER=fake` gives deterministic tones
  and a fixed transcript (tests and CI). `STITCH_TTS_PROVIDER=prerendered` serves only the cache.
* Deepgram: set `DEEPGRAM_API_KEY` (and `STITCH_STT_PROVIDER=deepgram` for the microphone).
* Azure for Urdu: also set `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`.

`/healthz` returns `meta` with the capabilities, the provider chains, whether a hosted service is
used, the Urdu route (`azure` or `prerendered`) and the number of prerendered entries.

## Prerendered demo audio

The spoken scripts of the default demo briefing are committed in `data/demo/voice/scripts/`
(built from the Brain with `--build-scripts`; `--check-scripts` fails when they drift). The audio
is not committed: Deepgram's terms do not clearly permit redistributing it (`docs/decisions.md`).
Generate it where it is served:

```
uv run python scripts/prerender_voice.py --dry-run           # sizes and budget, no calls
uv run python scripts/prerender_voice.py --env-file .env     # writes data/cache/voice/prerendered
docker compose run --rm voice python -m stitch_voice.prerender --out /cache/voice/prerendered
```

The English demo script (3,818 characters, 5,892 spoken after number expansion) renders to about
6.7 minutes of 24 kHz WAV, about 19 MB, which is 25 MB as base64 in the `speak` result.

## Tests and evals

```
uv run pytest organs/voice                                   # unit, property (VOX-P1..P5), contract, smoke
uv run pytest organs/voice/tests/live -m live                # real Deepgram calls; key from env or .env
uv run python -m evals.run --organ voice --seed 0 --fast     # English round-trip WER; not_run without a key
```

Live tests and evals spend Deepgram credit (a few hundred characters and under a minute of
audio). The eval caches transcripts by audio hash under `data/cache/voice/eval/`.

## Layout

```
src/stitch_voice/
  core/          pure logic: normalization (en, ur), sentence splitting, WAV join, guards, budget, cache keys
  providers/     deepgram, azure, whisper, prerendered, fake; shared HTTP retries
  decode.py      input audio checks (magic bytes, 60 s limit, level), in memory
  service.py     provider chains, cache, budget, error mapping; builds every output
  store.py       audio cache (atomic, LRU) and the monthly budget in SQLite
  prerender.py   renders the demo scripts into the prerendered cache (python -m stitch_voice.prerender)
  server.py      thin MCP layer from stitch_common.mcp_app
tests/  unit/ property/ contract/ live/ test_smoke_stdio.py
```
