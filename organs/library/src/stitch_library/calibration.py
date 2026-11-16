"""Refusal thresholds from ``calibration.json`` (design 8.3 and 8.4).

Thresholds belong to a ``(embedder model id, reranker model id)`` profile, then to the query
language and the scorer (``rerank`` logit or best ``dense`` cosine when the reranker did not run).
A profile missing for the loaded models gives ``status = "missing"`` and conservative built-in
defaults; the server logs an error and every result carries ``CALIBRATION_MISSING``. A profile
marked ``provisional`` adds ``CALIBRATION_PROVISIONAL``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stitch_library.core.decide import Thresholds

CALIBRATION_PATH = Path(__file__).resolve().parent / "calibration.json"
# Used only when no profile matches the loaded models. Deliberately strict.
FALLBACK = {"tau_scope": 0.0, "rerank": 0.0, "dense": 0.5}


def profile_key(embed_model_id: str, rerank_model_id: str) -> str:
    return f"{embed_model_id}+{rerank_model_id}"


@dataclass
class Calibration:
    key: str
    status: str  # "ok" | "provisional" | "missing"
    tau_scope: float
    tau_evid: dict[str, dict[str, float]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def thresholds(self, lang: str, scorer: str) -> Thresholds:
        per_lang = self.tau_evid.get(lang) or self.tau_evid.get("pooled") or {}
        tau = per_lang.get(scorer)
        if tau is None:
            tau = FALLBACK["rerank" if scorer == "rerank" else "dense"]
        return Thresholds(tau_scope=self.tau_scope, tau_evid=float(tau))

    @property
    def warning(self) -> str | None:
        if self.status == "missing":
            return "CALIBRATION_MISSING"
        if self.status == "provisional":
            return "CALIBRATION_PROVISIONAL"
        return None


def load_calibration(key: str, path: Path = CALIBRATION_PATH) -> Calibration:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    prof = (data.get("profiles") or {}).get(key)
    if not prof:
        return Calibration(key, "missing", FALLBACK["tau_scope"], {}, {})
    status = "provisional" if prof.get("provisional") else "ok"
    return Calibration(key, status, float(prof["tau_scope"]), prof.get("tau_evid", {}), prof)


def write_profile(key: str, profile: dict[str, Any], path: Path = CALIBRATION_PATH) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("profiles", {})[key] = profile
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
