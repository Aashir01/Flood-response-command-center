"""Voice orchestration: provider chains, cache, budget, guards, and the contract outputs.

``speak`` and ``transcribe`` build ``SpeakOut``/``TranscribeOut`` here and nowhere else, so the
output schema cannot depend on the provider (VOX-P5). Errors map to envelope codes per design 6.
Transcripts are never logged; logs carry durations, languages and provider names only.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from stitch_common.logging import get_logger
from stitch_common.organs.voice import Segment as OutSegment
from stitch_common.organs.voice import SpeakIn, SpeakOut, TranscribeIn, TranscribeOut
from stitch_common.provenance import DataSource, ModelInfo
from stitch_common.tooling import Outcome, ToolFailure, current_mode
from stitch_voice import decode
from stitch_voice.core import audio, guards
from stitch_voice.core.keys import PIPELINE_VERSION, cache_key
from stitch_voice.core.normalize import normalize
from stitch_voice.core.split import chunks
from stitch_voice.providers.azure import AzureTTS
from stitch_voice.providers.base import (
    BudgetExceeded,
    Lang,
    NotFound,
    ProviderError,
    STTProvider,
    Transcript,
    TTSProvider,
)
from stitch_voice.providers.deepgram import DeepgramSTT, DeepgramTTS
from stitch_voice.providers.fake import FakeSTT, FakeTTS
from stitch_voice.providers.prerendered import PrerenderedStore
from stitch_voice.providers.whisper import WhisperSTT
from stitch_voice.settings import Settings, load_settings
from stitch_voice.store import AudioStore, BudgetStore

TOOL_VERSION = "0.2.0"
URDU_NEEDS_AZURE = "Urdu speech needs Azure; Urdu text briefing is shown"
PAUSE_S = 0.4
_log = get_logger("stitch.voice")

_TERMS: dict[str, DataSource] = {
    "deepgram": DataSource(
        id="deepgram-api",
        name="Deepgram API (Aura-2 TTS, Nova-3 STT), mip_opt_out=true",
        license="Deepgram Terms of Service 2026-08-06; output is AI-generated",
        as_of=None,
    ),
    "azure": DataSource(
        id="azure-neural-tts",
        name="Azure AI Speech Neural TTS",
        license="Microsoft Product Terms",
        as_of=None,
    ),
    "whisper": DataSource(
        id="openai-whisper-weights",
        name="Whisper weights (CTranslate2 conversion) run locally by faster-whisper",
        license="MIT",
        as_of=None,
    ),
}
_VOICE_RULES: dict[str, re.Pattern[str]] = {
    "deepgram": re.compile(r"^aura-2-[a-z]+-en$"),
    "azure": re.compile(r"^ur-PK-[A-Za-z]+Neural$"),
}


class VoiceService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        tts: Sequence[TTSProvider] | None = None,
        stt: Sequence[STTProvider] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = s = settings or load_settings()
        self.cache = AudioStore(s.cache_dir / "audio", s.cache_mb * 1024 * 1024)
        self.prerendered = PrerenderedStore(s.prerendered_dir)
        self.budget: BudgetStore | None
        try:
            self.budget = BudgetStore(
                s.cache_dir / "budget.sqlite3", clock or (lambda: datetime.now(UTC))
            )
        except (OSError, sqlite3.Error):
            # Fail closed: without the budget counter no paid call is made. The server still
            # starts (prerendered, local Whisper) and /healthz reports the cache as unwritable.
            self.budget = None
            _log.warning("voice cache is not writable; hosted providers disabled")
        self.tts = list(tts) if tts is not None else self._default_tts()
        self.stt = list(stt) if stt is not None else self._default_stt()
        if self.budget is None:
            self.tts = [p for p in self.tts if not p.hosted]
            self.stt = [p for p in self.stt if not p.hosted]

    # -- provider selection --------------------------------------------------------------
    def _default_tts(self) -> list[TTSProvider]:
        s = self.settings
        if s.tts_provider == "fake":
            return [FakeTTS()]
        if s.tts_provider == "prerendered":
            return []
        chain: list[TTSProvider] = []
        if s.deepgram_ready:
            chain.append(
                DeepgramTTS(s.deepgram_api_key, s.deepgram_voice_en, base_url=s.deepgram_base_url)
            )
        if s.azure_ready:
            chain.append(AzureTTS(s.azure_speech_key, s.azure_speech_region, s.azure_voice_ur))
        return chain

    def _default_stt(self) -> list[STTProvider]:
        s = self.settings
        if s.stt_provider == "fake":
            return [FakeSTT()]
        whisper = WhisperSTT(s.whisper_model, s.whisper_model_dir, s.whisper_download)
        if s.stt_provider == "deepgram" and s.deepgram_ready:
            return [DeepgramSTT(s.deepgram_api_key, base_url=s.deepgram_base_url), whisper]
        return [whisper]

    def _budget(self) -> BudgetStore:
        if self.budget is None:  # hosted providers are removed in this case; defensive only
            raise BudgetExceeded("the budget store is not available")
        return self.budget

    def meta(self) -> dict[str, Any]:
        tts = [p.name for p in self.tts if p.available()]
        return {
            "capabilities": ["speak", "transcribe"],
            "tts_provider": self.settings.tts_provider,
            "tts_chain": [*tts, "prerendered"],
            "stt_chain": [p.name for p in self.stt],
            "hosted": any(p.hosted for p in self.tts) or any(p.hosted for p in self.stt),
            "whisper_model": self.settings.whisper_model,
            "urdu_tts": "azure" if any(p.supports("ur") for p in self.tts) else "prerendered",
            "prerendered_entries": self.prerendered.count(),
        }

    def health(self) -> dict[str, bool]:
        return {"cache_writable": _writable(self.settings.cache_dir)}

    def cores(self) -> dict[str, Callable[[Any], Any]]:
        return {"speak": self.speak, "transcribe": self.transcribe}

    # -- speak ---------------------------------------------------------------------------
    def speak(self, params: SpeakIn) -> Outcome[SpeakOut]:
        lang: Lang = params.lang
        warnings: list[str] = []
        if params.format == "mp3":
            warnings.append("FORMAT_WAV_ONLY: audio is returned as wav")
        chain = [p for p in self.tts if p.supports(lang) and p.available()]
        if params.voice is not None:
            self._check_voice(params.voice, lang, chain)
        if not normalize(params.text, lang):
            raise ToolFailure("INVALID_INPUT", "text has nothing speakable after normalization")
        errors: list[ProviderError] = []
        for provider in chain:
            if params.voice is not None and not _voice_ok(provider.name, params.voice):
                continue
            try:
                return self._speak_with(provider, params, lang, warnings)
            except ProviderError as exc:
                errors.append(exc)
                warnings.append(f"TTS_FALLBACK: {provider.name}: {exc.message}")
                _log.warning("tts provider failed", extra={"provider": provider.name, "lang": lang})
        try:
            hit = self.prerendered.lookup(params.text, lang, params.voice)
        except NotFound:
            hit = None
        if hit is not None:
            data = SpeakOut(
                audio_b64=base64.b64encode(hit.wav).decode("ascii"),
                format="wav",
                duration_s=hit.duration_s or audio.wav_info(hit.wav).duration_s,
                sample_rate=hit.sample_rate,
                lang=lang,
                provider="prerendered",
                synthesized="prerendered",
                voice=hit.voice or None,
            )
            sources = [_TERMS[hit.source_provider]] if hit.source_provider in _TERMS else []
            return Outcome(data, warnings=warnings, data_sources=sources, mode="demo")
        if lang == "ur" and not any(p.supports("ur") for p in chain):
            raise ToolFailure(
                "UPSTREAM_UNAVAILABLE", URDU_NEEDS_AZURE, False, [*warnings, URDU_NEEDS_AZURE]
            )
        if not chain and self.settings.tts_provider == "prerendered":
            raise ToolFailure("NOT_FOUND", "no pre-rendered audio for this text", False, warnings)
        retryable = bool(errors) and all(e.retryable for e in errors)
        message = "no speech synthesis provider is available"
        if errors:
            message += f" ({errors[-1].message})"
        raise ToolFailure("UPSTREAM_UNAVAILABLE", message, retryable, warnings)

    def _check_voice(self, voice: str, lang: Lang, chain: list[TTSProvider]) -> None:
        if any(p.name == "fake" for p in chain):
            return
        if lang == "ur" and _VOICE_RULES["deepgram"].match(voice):
            raise ToolFailure("INVALID_INPUT", "an English voice cannot read Urdu text")
        known = any(rule.match(voice) for rule in _VOICE_RULES.values())
        if not known and not self._prerendered_voice(voice):
            raise ToolFailure("INVALID_INPUT", "unknown voice")

    def _prerendered_voice(self, voice: str) -> bool:
        return any(e.get("voice") == voice for e in self.prerendered._index())

    def _speak_with(
        self, provider: TTSProvider, params: SpeakIn, lang: Lang, warnings: list[str]
    ) -> Outcome[SpeakOut]:
        voice = params.voice or provider.default_voice(lang)
        key = cache_key(params.text, lang, voice, provider.name)
        cached = self.cache.get(key)
        if cached is not None:
            wav, meta = cached
            info = audio.wav_info(wav)
            return self._speak_out(wav, info, lang, provider, voice, "cache", warnings, meta)
        spoken = normalize(params.text, lang)
        parts = chunks(spoken, provider.max_chunk_chars)
        chars = sum(len(p) for p in parts)
        reserved = 0
        if provider.hosted:
            decision = self._budget().reserve(
                provider.name, "tts_chars", chars, self.settings.tts_monthly_char_cap
            )
            if not decision.allowed:
                raise BudgetExceeded("monthly TTS character cap reached")
            reserved = chars
            if decision.warn:
                warnings.append("TTS_BUDGET_80PCT")
        try:
            pieces = _synthesize_all(provider, parts, lang, voice)
            wav = pieces[0] if len(pieces) == 1 else audio.join_wav(pieces, PAUSE_S)
        except audio.AudioError as exc:
            if reserved:
                self._budget().release(provider.name, "tts_chars", reserved)
            raise ProviderError(f"could not join audio ({exc})") from exc
        except ProviderError:
            if reserved:
                self._budget().release(provider.name, "tts_chars", reserved)
            raise
        info = audio.wav_info(wav)
        meta = {
            "lang": lang,
            "voice": voice,
            "provider": provider.name,
            "format": "wav",
            "duration_s": info.duration_s,
            "sample_rate": info.sample_rate,
            "chars": chars,
            "generated_at": datetime.now(UTC).isoformat(),
            "tool_version": TOOL_VERSION,
            "pipeline_version": PIPELINE_VERSION,
        }
        self.cache.put(key, wav, meta)
        _log.info(
            "speech synthesized",
            extra={"provider": provider.name, "lang": lang, "chunks": len(parts), "chars": chars},
        )
        return self._speak_out(wav, info, lang, provider, voice, "live", warnings, meta)

    def _speak_out(
        self,
        wav: bytes,
        info: audio.WavInfo,
        lang: Lang,
        provider: TTSProvider,
        voice: str,
        synthesized: str,
        warnings: list[str],
        meta: dict[str, Any],
    ) -> Outcome[SpeakOut]:
        data = SpeakOut.model_validate(
            {
                "audio_b64": base64.b64encode(wav).decode("ascii"),
                "format": "wav",
                "duration_s": info.duration_s,
                "sample_rate": info.sample_rate,
                "lang": lang,
                "provider": provider.name,
                "synthesized": synthesized,
                "voice": voice,
            }
        )
        model = ModelInfo(name=f"{provider.name}:{voice}", version=PIPELINE_VERSION, sha256="")
        sources = [_TERMS[provider.name]] if provider.name in _TERMS else []
        mode = "live" if provider.hosted and synthesized == "live" else current_mode()
        return Outcome(data, warnings=warnings, data_sources=sources, model=model, mode=mode)

    # -- transcribe ----------------------------------------------------------------------
    def transcribe(self, params: TranscribeIn) -> Outcome[TranscribeOut]:
        try:
            raw = base64.b64decode(params.audio_b64, validate=True)
        except (binascii.Error, ValueError):
            raise ToolFailure("INVALID_INPUT", "audio_b64 is not valid base64") from None
        hint: Lang | None = params.lang_hint if params.lang_hint in ("en", "ur") else None
        try:
            checked = decode.check_audio(raw, params.format)
        except audio.AudioError as exc:
            raise ToolFailure("INVALID_INPUT", str(exc)) from None
        warnings: list[str] = []
        if checked.duration_s <= 0 or (
            checked.level_dbfs is not None and guards.is_silent(checked.level_dbfs)
        ):
            return self._no_speech(hint, warnings, None)
        errors: list[ProviderError] = []
        for provider in self.stt:
            seconds = math.ceil(checked.duration_s)
            if provider.hosted:
                decision = self._budget().reserve(
                    provider.name, "stt_seconds", seconds, self.settings.stt_monthly_seconds_cap
                )
                if not decision.allowed:
                    warnings.append(f"STT_FALLBACK: {provider.name}: monthly STT cap reached")
                    continue
            try:
                result = provider.transcribe(raw, params.format, hint, checked.duration_s)
            except ProviderError as exc:
                if provider.hosted:
                    self._budget().release(provider.name, "stt_seconds", seconds)
                errors.append(exc)
                warnings.append(f"STT_FALLBACK: {provider.name}: {exc.message}")
                continue
            return self._transcript_out(result, provider, checked.duration_s, warnings)
        retryable = bool(errors) and all(e.retryable for e in errors)
        message = "no speech-to-text engine is available"
        if errors:
            message += f" ({errors[-1].message})"
        raise ToolFailure("UPSTREAM_UNAVAILABLE", message, retryable, warnings)

    def _no_speech(
        self, hint: Lang | None, warnings: list[str], model: ModelInfo | None
    ) -> Outcome[TranscribeOut]:
        data = TranscribeOut(
            text="", lang=hint or "en", segments=[], lang_confidence=1.0 if hint else 0.0
        )
        return Outcome(data, warnings=[*warnings, "NO_SPEECH"], model=model)

    def _transcript_out(
        self, result: Transcript, provider: STTProvider, duration_s: float, warnings: list[str]
    ) -> Outcome[TranscribeOut]:
        model = ModelInfo(name=result.model or provider.name, version="1", sha256="")
        if provider.name == "whisper" and isinstance(provider, WhisperSTT):
            model = ModelInfo(
                name=result.model, version=provider.size, sha256=provider.model_sha256
            )
        _log.info(
            "transcribed",
            extra={"provider": provider.name, "lang": result.lang, "duration_s": duration_s},
        )
        text = result.text.strip()
        speech_s = result.speech_s if result.speech_s is not None else duration_s
        if not text or speech_s < guards.MIN_SPEECH_S or guards.is_filler(text, speech_s):
            return self._no_speech(result.lang, warnings, model)
        text, trimmed = guards.trim_repetition(text)
        if trimmed:
            warnings.append("REPETITION_TRIMMED")
        segments = [
            OutSegment(start=s.start, end=max(s.start, s.end), text=s.text) for s in result.segments
        ]
        data = TranscribeOut(
            text=text,
            lang=result.lang,
            segments=segments,
            lang_confidence=min(1.0, max(0.0, result.lang_confidence)),
        )
        sources = [_TERMS[provider.name]] if provider.name in _TERMS else []
        mode = "live" if provider.hosted else current_mode()
        return Outcome(data, warnings=warnings, data_sources=sources, model=model, mode=mode)


# Hosted chunks are independent requests; up to this many run at once (order is kept).
HOSTED_PARALLEL_CHUNKS = 4


def _synthesize_all(provider: TTSProvider, parts: list[str], lang: Lang, voice: str) -> list[bytes]:
    """Synthesize every chunk, in input order. Hosted providers run up to
    ``HOSTED_PARALLEL_CHUNKS`` requests in parallel; local ones run sequentially."""
    if not provider.hosted or len(parts) < 2:
        return [provider.synthesize(part, lang, voice).wav for part in parts]
    workers = min(HOSTED_PARALLEL_CHUNKS, len(parts))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tts") as pool:
        return [
            chunk.wav for chunk in pool.map(lambda p: provider.synthesize(p, lang, voice), parts)
        ]


def _voice_ok(provider: str, voice: str) -> bool:
    rule = _VOICE_RULES.get(provider)
    return rule is None or bool(rule.match(voice))


def _writable(path: Any) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".healthz"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False
