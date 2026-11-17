# ruff: noqa: E501
"""Environment configuration for eyes-mcp.

| Variable | Meaning | Default |
|---|---|---|
| ``STITCH_DEMO_DIR`` | dataset root | ``<repo>/data/demo`` |
| ``STITCH_EYES_MODEL_DIR`` | model directory (``eyes_unet_r18.onnx``, ``export_check.json``) | ``organs/eyes/models`` |
| ``STITCH_EYES_MODEL`` | ``auto`` (shipped ONNX) or ``threshold`` (documented fallback) | ``auto`` |
| ``STITCH_EYES_THREADS`` | ONNX Runtime intra-op threads | ``2`` |
| ``STITCH_EYES_DATE_TOLERANCE_DAYS`` | nearest scene accepted within this many days | ``3`` |
| ``STITCH_EYES_MAX_AREA_KM2`` | largest window | ``2000`` |
| ``STITCH_EYES_WARM`` | ``1`` warms the demo-scene cache at server start | ``1`` |
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ORGAN_DIR = Path(__file__).resolve().parents[2]
REPO = ORGAN_DIR.parents[1]


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    demo_dir: Path
    model_dir: Path
    model_choice: str
    threads: int
    date_tolerance_days: int
    max_area_km2: float
    warm: bool
    perm_dilate_px: int = 3
    low_conf_threshold: float = 0.75
    min_polygon_km2: float = 0.005
    simplify_m: float = 15.0
    max_features: int = 3000
    cache_size: int = 8

    @property
    def eyes_dir(self) -> Path:
        return self.demo_dir / "eyes"

    @property
    def boundaries(self) -> Path:
        return self.demo_dir / "boundaries" / "pk_districts.geojson"

    @classmethod
    def from_env(cls) -> Settings:
        demo = Path(os.environ.get("STITCH_DEMO_DIR", REPO / "data" / "demo"))
        return cls(
            demo_dir=demo,
            model_dir=Path(os.environ.get("STITCH_EYES_MODEL_DIR", ORGAN_DIR / "models")),
            model_choice=os.environ.get("STITCH_EYES_MODEL", "auto").strip().lower(),
            threads=max(int(_float("STITCH_EYES_THREADS", 2)), 1),
            date_tolerance_days=max(int(_float("STITCH_EYES_DATE_TOLERANCE_DAYS", 3)), 0),
            max_area_km2=_float("STITCH_EYES_MAX_AREA_KM2", 2000.0),
            warm=os.environ.get("STITCH_EYES_WARM", "1") == "1",
        )
