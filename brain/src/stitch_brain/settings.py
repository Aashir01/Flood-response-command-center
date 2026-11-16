"""Brain settings from the environment (design 18). Read once per app or run; tests build their
own ``Settings`` instead of mutating the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ORGANS = ("eyes", "oracle", "library", "ledger", "voice")
DEFAULT_CORS = ("http://localhost:3000", "https://stitch.aashirnoman.dev")


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "on", "yes")


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    llm_provider: str = "fake"
    recorded_organs: tuple[str, ...] = ()
    disabled_organs: tuple[str, ...] = ()
    planner: str = "default"
    phrase: bool = True
    fake_strict: bool = False
    run_deadline_s: float = 60.0
    organ_deadline_s: float = 45.0
    db_path: str | None = None
    cors_origins: tuple[str, ...] = DEFAULT_CORS
    trusted_proxy: bool = False
    ur_digits: str = "ascii"
    log_prompts: bool = False
    allow_arbitrary_tts: bool = False
    max_runs: int = 4
    rate_limits: dict[str, tuple[float, int]] = field(
        default_factory=lambda: {
            "briefings": (6.0, 3),
            "ask": (20.0, 5),
            "voice": (10.0, 3),
            "default": (120.0, 30),
        }
    )

    @property
    def recorded_all(self) -> bool:
        return "all" in self.recorded_organs

    def is_recorded(self, organ: str) -> bool:
        return self.recorded_all or organ in self.recorded_organs

    @classmethod
    def from_env(cls) -> Settings:
        mode = "live" if os.environ.get("STITCH_MODE", "demo").strip().lower() == "live" else "demo"
        live = mode == "live"
        return cls(
            mode=mode,
            llm_provider=os.environ.get("STITCH_LLM_PROVIDER", "fake").strip().lower() or "fake",
            recorded_organs=_csv("STITCH_RECORDED_ORGANS"),
            disabled_organs=_csv("STITCH_ORGANS_DISABLED"),
            planner=os.environ.get("STITCH_BRAIN_PLANNER", "default"),
            phrase=os.environ.get("STITCH_BRAIN_PHRASE", "on").strip().lower() != "off",
            fake_strict=_flag("STITCH_FAKE_STRICT"),
            run_deadline_s=_float("STITCH_RUN_DEADLINE_S", 90.0 if live else 60.0),
            organ_deadline_s=_float("STITCH_ORGAN_DEADLINE_S", 70.0 if live else 45.0),
            db_path=os.environ.get("STITCH_BRAIN_DB") or None,
            cors_origins=_csv("STITCH_CORS_ORIGINS", ",".join(DEFAULT_CORS)),
            trusted_proxy=_flag("STITCH_TRUSTED_PROXY"),
            ur_digits="extended" if os.environ.get("STITCH_UR_DIGITS") == "extended" else "ascii",
            log_prompts=_flag("STITCH_LOG_PROMPTS"),
            allow_arbitrary_tts=_flag("STITCH_ALLOW_ARBITRARY_TTS"),
        )
