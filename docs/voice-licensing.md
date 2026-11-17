# Voice: licensing of generated audio (voice task 8 gate)

Decision: generated speech audio is **not committed** to the repository. It is rendered at deploy
time into the git-ignored cache (`data/cache/voice/prerendered/`, or the `voice_cache` volume in
Compose) and served from there inside the running app. Gate option (b) of voice design 8.3.

## Evidence consulted

Deepgram Terms of Service, https://deepgram.com/terms, "Last Updated: August 6, 2026", read on
2026-11-17:

- 3.1: audio returned by the Services is "Output"; Input and Output are "Your Content".
- 3.4: Deepgram does not claim ownership of Your Content, but "we make no representations that you
  own or have rights in any similar output". No clause grants a licence to redistribute Output.
- 3.5(c): we must not present audio Output as human-made and must give the legally required
  notice that it is artificially generated.
- 2.4(c): no distributing or publicly displaying "any part of our Services". Whether a WAV file in
  a public repository counts is unclear.
- 2.4(i): no use of Output for benchmarking or competitive analysis. The round-trip WER eval is an
  internal intelligibility check and is labelled that way.
- 3.3: model-improvement opt-out per request; every Stitch request sets `mip_opt_out=true`.

Azure (Urdu) was not used: no key is configured. Its terms were not re-read for this decision.
Voice design 8.2 lists the Microsoft sources and why they were not conclusive.

## What is committed

- `data/demo/voice/scripts/en.txt` and `ur.txt`: the spoken text of the demo briefing, built by the
  Brain (our own text, MIT).
- The code that renders and serves the audio. No audio files.

## How the demo gets audio

```
# local
uv run python scripts/prerender_voice.py --env-file .env
# Compose (live override gives the container the key and egress)
docker compose -f compose.yaml -f deploy/compose.live.yaml --profile voice run --rm --no-deps \
  voice python -m stitch_voice.prerender --out /cache/voice/prerendered
```

Checked locally on 2026-11-17: English rendered (Aura-2 `aura-2-thalia-en`, about 400 s, 24 kHz
WAV); Urdu skipped because Deepgram has no Urdu voice and Azure is not configured. Without audio
in the cache, `speak` returns `UPSTREAM_UNAVAILABLE` (Urdu with the warning "Urdu speech needs
Azure; Urdu text briefing is shown") and the UI shows the text briefing.

The UI must label the audio as AI-generated and name the provider (Deepgram terms 3.5(c)).
