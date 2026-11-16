"""Typed Brain configuration loaded from ``brain/config/*.yaml``. Loading is the only I/O; the
models are passed into ``core`` as plain data."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from stitch_brain.paths import config_dir


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LangText(_M):
    en: str
    ur: str

    def get(self, lang: str) -> str:
        return self.ur if lang == "ur" else self.en


class EyesCfg(_M):
    date: date


class OracleCfg(_M):
    station_id: str
    horizon_days: int = Field(ge=1, le=14)
    as_of: date | None = None
    coverage: float = 0.8


class CommodityCfg(_M):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: LangText
    unit: str
    unit_cost: float = Field(ge=0)
    per_person_need_per_day: float | None = Field(default=None, gt=0)
    per_person_need: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _one_need(self) -> CommodityCfg:
        if (self.per_person_need_per_day is None) == (self.per_person_need is None):
            raise ValueError("exactly one of per_person_need_per_day and per_person_need")
        return self

    def need(self, period_days: int) -> float:
        if self.per_person_need_per_day is not None:
            return self.per_person_need_per_day * period_days
        assert self.per_person_need is not None
        return self.per_person_need


class SeverityCfg(_M):
    f_noise: float = 0.01
    f_sat: float = 0.30
    lambda_: float = Field(default=0.25, alias="lambda")
    pi: float = 0.10
    kappa: float = 0.5

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class QuantityCfg(_M):
    commodity_id: str
    units: list[str]


class QuestionCfg(_M):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    query: LangText
    quantity: QuantityCfg | None = None


class ScenarioCfg(_M):
    id: str
    region: str
    label: LangText
    fixture_set: str
    ledger_scenario_id: str
    eyes: EyesCfg
    oracle: OracleCfg
    basin_districts: list[str]
    period_days: int = Field(ge=1)
    commodities: list[CommodityCfg] = Field(min_length=1)
    supply: dict[str, float]
    budget: float | None = None
    equity_floor: float | None = None
    integer: bool = True
    severity: SeverityCfg
    guidance_questions: list[QuestionCfg]

    def commodity(self, cid: str) -> CommodityCfg | None:
        return next((c for c in self.commodities if c.id == cid), None)


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def parse_scenarios(raw: dict[str, Any]) -> dict[str, ScenarioCfg]:
    items: dict[str, dict[str, Any]] = dict(raw.get("scenarios") or {})
    out: dict[str, ScenarioCfg] = {}

    def resolved(sid: str, depth: int = 0) -> dict[str, Any]:
        if depth > 4:
            raise ValueError("scenario extends chain too deep")
        item = dict(items[sid])
        parent = item.pop("extends", None)
        return _merge(resolved(parent, depth + 1), item) if parent else item

    for sid in items:
        out[sid] = ScenarioCfg.model_validate({**resolved(sid), "id": sid})
    return out


@lru_cache(maxsize=4)
def load_scenarios(path: str | None = None) -> dict[str, ScenarioCfg]:
    p = Path(path) if path else config_dir() / "scenarios.yaml"
    return parse_scenarios(_read_yaml(p))


# --- organs.yaml -------------------------------------------------------------------------------
class OrganEndpoint(_M):
    transport: Literal["stdio", "http"] = "stdio"
    command: list[str] | None = None
    url: str | None = None
    healthz_url: str | None = None
    demo_url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    max_in_flight: int = 2
    connect_timeout_s: float = 20.0


class OrgansCfg(_M):
    organs: dict[str, OrganEndpoint]


@lru_cache(maxsize=4)
def load_organs(path: str | None = None) -> OrgansCfg:
    p = Path(path) if path else config_dir() / "organs.yaml"
    return OrgansCfg.model_validate(_read_yaml(p))


# --- i18n ----------------------------------------------------------------------------------------
class LangPack(_M):
    lang: Literal["en", "ur"]
    list_sep: str
    disputed_suffix: str
    section_titles: dict[str, str]
    tables: dict[str, dict[str, str]]
    units: dict[str, list[str]]
    modeled_terms: list[str]
    forbidden_oracle_terms: list[str]
    templates: dict[str, str]
    conflicts: dict[str, str]
    assumptions: dict[str, str]
    disclaimer: str


class I18n(_M):
    packs: dict[str, LangPack]

    def pack(self, lang: str) -> LangPack:
        return self.packs.get(lang) or self.packs["en"]

    def pattern(self, template_id: str, lang: str) -> str:
        return self.pack(lang).templates[template_id]

    def unit_aliases(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in self.packs.values():
            for k, al in p.units.items():
                out.setdefault(k, [])
                out[k] += [a for a in al if a not in out[k]]
        return out

    def lookup_tables(self) -> dict[str, dict[str, dict[str, str]]]:
        out: dict[str, dict[str, dict[str, str]]] = {}
        for lang, p in self.packs.items():
            for name, table in p.tables.items():
                out.setdefault(name, {})[lang] = dict(table)
        return out


@lru_cache(maxsize=2)
def load_i18n(path: str | None = None) -> I18n:
    d = Path(path) if path else config_dir() / "i18n"
    packs = {}
    for lang in ("en", "ur"):
        f = d / f"{lang}.yaml"
        if f.exists():
            packs[lang] = LangPack.model_validate(_read_yaml(f))
    i18n = I18n(packs=packs)
    from stitch_brain.core.derive import set_lookups

    set_lookups(i18n.lookup_tables())
    return i18n


@lru_cache(maxsize=2)
def load_rules(path: str | None = None) -> Any:
    """The conflict rule set (``conflict_rules.yaml``), parsed and statically checked."""
    from stitch_brain.core.rules import load_ruleset_text

    p = Path(path) if path else config_dir() / "conflict_rules.yaml"
    return load_ruleset_text(p.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def load_yaml(name: str) -> Any:
    return _read_yaml(config_dir() / name)
