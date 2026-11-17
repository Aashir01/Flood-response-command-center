"""Voice settings from the environment (design sections 7 and 14).

Secrets are read here and only passed to the provider that needs them. They are never logged,
never put in error messages, and never included in ``repr``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        file_path = os.environ.get(f"{name}_FILE", "").strip()
        if file_path and Path(file_path).is_file():
            value = Path(file_path).read_text(encoding="utf-8").strip()
    return value or default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    tts_provider: str = "deepgram"
    stt_provider: str = "whisper"
    deepgram_api_key: str = field(default="", repr=False)
    deepgram_voice_en: str = "aura-2-thalia-en"
    deepgram_base_url: str = "https://api.deepgram.com"
    azure_speech_key: str = field(default="", repr=False)
    azure_speech_region: str = ""
    azure_voice_ur: str = "ur-PK-UzmaNeural"
    whisper_model: str = "base"
    whisper_model_dir: str = ""
    whisper_download: bool = False
    cache_dir: Path = REPO_ROOT / "data" / "cache" / "voice"
    prerendered_dir: Path = REPO_ROOT / "data" / "cache" / "voice" / "prerendered"
    cache_mb: int = 100
    tts_monthly_char_cap: int = 200_000
    stt_monthly_seconds_cap: int = 3600

    @property
    def deepgram_ready(self) -> bool:
        return bool(self.deepgram_api_key)

    @property
    def azure_ready(self) -> bool:
        return bool(self.azure_speech_key and self.azure_speech_region)


def load_settings() -> Settings:
    cache_dir = Path(_env("STITCH_VOICE_CACHE_DIR", str(REPO_ROOT / "data" / "cache" / "voice")))
    return Settings(
        tts_provider=_env("STITCH_TTS_PROVIDER", "deepgram").lower(),
        stt_provider=_env("STITCH_STT_PROVIDER", "whisper").lower(),
        deepgram_api_key=_env("DEEPGRAM_API_KEY"),
        deepgram_voice_en=_env("STITCH_DEEPGRAM_VOICE_EN", "aura-2-thalia-en"),
        deepgram_base_url=_env("STITCH_DEEPGRAM_BASE_URL", "https://api.deepgram.com"),
        azure_speech_key=_env("AZURE_SPEECH_KEY"),
        azure_speech_region=_env("AZURE_SPEECH_REGION"),
        azure_voice_ur=_env("STITCH_AZURE_VOICE_UR", "ur-PK-UzmaNeural"),
        whisper_model=_env("STITCH_WHISPER_MODEL", "base"),
        whisper_model_dir=_env("STITCH_WHISPER_MODEL_DIR"),
        whisper_download=_env("STITCH_WHISPER_DOWNLOAD", "0") == "1",
        cache_dir=cache_dir,
        prerendered_dir=Path(_env("STITCH_VOICE_PRERENDERED_DIR", str(cache_dir / "prerendered"))),
        cache_mb=_int("STITCH_VOICE_CACHE_MB", 100),
        tts_monthly_char_cap=_int("STITCH_TTS_MONTHLY_CHAR_CAP", 200_000),
        stt_monthly_seconds_cap=_int("STITCH_STT_MONTHLY_SECONDS_CAP", 3600),
    )
