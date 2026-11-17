"""Result models for the eval runner. ``evals/results/schema.json`` is exported from these."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

ORGANS = ("eyes", "oracle", "library", "ledger", "brain", "voice")
Status = Literal["pass", "fail", "not_run", "error"]


class MetricResult(BaseModel):
    """One measured metric. ``target`` is None when the metric has no pass/fail threshold."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_.\-]+$")
    label: str = Field(min_length=1)
    value: float
    target: float | None = None
    unit: str = ""
    direction: Literal["higher", "lower"]
    dataset: str = Field(min_length=1)
    mode: Literal["demo", "live", "synthetic"] = "demo"
    timestamp: datetime
    git_sha: str
    seed: int
    notes: str = ""

    @property
    def met_target(self) -> bool | None:
        if self.target is None:
            return None
        return (
            self.value >= self.target if self.direction == "higher" else self.value <= self.target
        )


class OrganResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    metrics: list[MetricResult] = Field(default_factory=list)
    message: str = ""


class Latest(BaseModel):
    """Shape of ``evals/results/latest.json``."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    git_sha: str
    organs: dict[str, OrganResult]


def results_schema() -> dict[str, object]:
    """JSON Schema of ``latest.json`` (per-organ files are one ``OrganResult``)."""
    return TypeAdapter(Latest).json_schema()
