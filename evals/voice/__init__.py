"""Voice evals (VOX-R6, design 10): ``python -m evals.run --organ voice --seed 0 [--fast]``.

Metrics:
* ``voice.roundtrip_wer_en``: English round trip. Sentences of the committed demo script
  (``data/demo/voice/scripts/en.txt``, chosen with ``seed``) are spoken by Deepgram Aura-2 and
  transcribed by Deepgram Nova-3 through the Voice service; WER against the spoken form of the
  sentence (``normalize``, so "m3/s" is scored as "cubic metres per second"). This is an internal
  intelligibility check of our pipeline, not a vendor comparison (Deepgram terms 2.4(i)).
  Runs only when ``DEEPGRAM_API_KEY`` is set; otherwise ``not_run``. Synthesized audio comes
  from the Voice cache and transcripts are cached by audio hash in
  ``data/cache/voice/eval/`` (git-ignored), so reruns cost nothing; set
  ``STITCH_VOICE_EVAL_FRESH=1`` to transcribe again.
* ``voice.wer_en`` and ``voice.wer_ur`` on owner recordings, and the Urdu round trip: not run.
  The recordings (``evals/voice/data/``) do not exist yet, and Deepgram has no Urdu voice
  (Urdu speech needs Azure).

WER is our own token Levenshtein with the normalization of design 10 (NFC, lower case,
punctuation including ``،`` ``۔`` ``؟`` removed, Arabic diacritics stripped, Arabic yeh and kaf
mapped to Urdu forms, Eastern digits to Western).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import random
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from evals.models import MetricResult, OrganResult

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_EN = ROOT / "data" / "demo" / "voice" / "scripts" / "en.txt"
EVAL_CACHE = ROOT / "data" / "cache" / "voice" / "eval"
RECORDINGS = Path(__file__).resolve().parent / "data"
TARGET_ROUNDTRIP_EN = 0.15
FAST_N, FULL_N = 3, 12

_DIACRITICS = re.compile("[\u064b-\u065f\u0670]")
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_ARABIC_TO_URDU = str.maketrans({"\u064a": "\u06cc", "\u0643": "\u06a9", "\u0649": "\u06cc"})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def wer_normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    text = _DIACRITICS.sub("", text).translate(_ARABIC_TO_URDU).translate(_DIGITS)
    text = text.replace("-", " ")
    return _PUNCT.sub(" ", text).split()


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, w in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != w))
        prev = cur
    return prev[-1]


def wer(refs: list[str], hyps: list[str]) -> float:
    """Corpus WER: total edits over total reference words."""
    edits = words = 0
    for r, h in zip(refs, hyps, strict=True):
        rt, ht = wer_normalize(r), wer_normalize(h)
        edits += edit_distance(rt, ht)
        words += len(rt)
    return edits / words if words else 0.0


def pick_sentences(text: str, n: int, seed: int) -> list[str]:
    from stitch_voice.core.split import sentences

    pool = [s.strip() for s in sentences(text) if len(s.split()) >= 4]
    rng = random.Random(seed)
    return rng.sample(pool, min(n, len(pool)))


def _cached_transcript(svc: object, wav_b64: str) -> tuple[str, bool]:
    from stitch_common.organs.voice import TranscribeIn
    from stitch_voice.service import VoiceService

    assert isinstance(svc, VoiceService)
    digest = hashlib.sha256(wav_b64.encode("ascii")).hexdigest()
    path = EVAL_CACHE / f"nova-3-en-{digest[:16]}.json"
    if path.is_file() and os.environ.get("STITCH_VOICE_EVAL_FRESH") != "1":
        return str(json.loads(path.read_text(encoding="utf-8"))["text"]), True
    out = svc.transcribe(TranscribeIn(audio_b64=wav_b64, format="wav", lang_hint="en"))
    EVAL_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": out.data.text}, ensure_ascii=False), encoding="utf-8")
    return out.data.text, False


def roundtrip_en(fast: bool, seed: int, git_sha: str) -> MetricResult:
    from stitch_common.organs.voice import SpeakIn
    from stitch_voice.core.normalize import normalize
    from stitch_voice.service import VoiceService
    from stitch_voice.settings import load_settings

    settings = dataclasses.replace(
        load_settings(), tts_provider="deepgram", stt_provider="deepgram"
    )
    svc = VoiceService(settings)
    picked = pick_sentences(SCRIPT_EN.read_text(encoding="utf-8"), FAST_N if fast else FULL_N, seed)
    refs, hyps, cached = [], [], 0
    for sentence in picked:
        spoken = svc.speak(SpeakIn(text=sentence, lang="en")).data
        if spoken.provider != "deepgram":
            raise RuntimeError(f"round trip needs Deepgram TTS, got {spoken.provider}")
        text, hit = _cached_transcript(svc, spoken.audio_b64)
        cached += hit
        refs.append(normalize(sentence, "en"))
        hyps.append(text)
    return MetricResult(
        id="voice.roundtrip_wer_en",
        label="English round-trip WER (Aura-2 then Nova-3)",
        value=round(wer(refs, hyps), 4),
        target=TARGET_ROUNDTRIP_EN,
        unit="fraction",
        direction="lower",
        dataset=f"demo briefing script sentences ({len(picked)}, seed {seed})",
        mode="live",
        timestamp=datetime.now(UTC),
        git_sha=git_sha,
        seed=seed,
        notes=(
            "Internal intelligibility check of the Voice pipeline, not a vendor benchmark. "
            "Reference is the normalized spoken form. "
            f"{cached} of {len(picked)} transcripts from the eval cache. "
            "Urdu WER and Urdu round trip not run: no owner recordings yet, and Deepgram has "
            "no Urdu voice (needs Azure)."
        ),
    )


def run(fast: bool, seed: int) -> OrganResult:
    from evals.run import git_sha

    if not os.environ.get("DEEPGRAM_API_KEY", "").strip():
        return OrganResult(
            status="not_run",
            message=(
                "DEEPGRAM_API_KEY not set: English round trip not run; Urdu needs owner "
                "recordings and Azure"
            ),
        )
    metric = roundtrip_en(fast, seed, git_sha())
    status = "fail" if metric.met_target is False else "pass"
    return OrganResult(
        status=status,
        metrics=[metric],
        message="wer_en, wer_ur, roundtrip_wer_ur: not run (no recordings; Urdu needs Azure)",
    )
