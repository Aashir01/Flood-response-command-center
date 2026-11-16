"""Shared types from mcp-contracts.md section 2.

Strictness decisions where the contract text is ambiguous:

* ``BBox`` requires ``-180 <= west <= east <= 180`` and ``-90 <= south <= north <= 90``.
  Boxes that cross the antimeridian are not supported.
* ``Citation.span`` requires ``0 <= start <= end``.
* ``AwareDatetime`` is used wherever the contract says "ISO 8601 UTC datetime".
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, model_validator

from stitch_common.base import Contract

Lang = Literal["en", "ur"]
LangOrAuto = Literal["en", "ur", "auto"]
Mode = Literal["demo", "live"]
OrganName = Literal["eyes", "oracle", "library", "ledger", "voice"]
ErrorCode = Literal[
    "INVALID_INPUT",
    "NOT_FOUND",
    "NO_EVIDENCE",
    "INFEASIBLE",
    "UPSTREAM_UNAVAILABLE",
    "TIMEOUT",
    "INTERNAL",
]

Slug = Annotated[str, Field(min_length=1, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]
NonNeg = Annotated[float, Field(ge=0.0)]
JsonPointer = Annotated[str, Field(pattern=r"^(/([^~/]|~[01])*)*$")]


def _check_bbox(v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    west, south, east, north = v
    if not (-180.0 <= west <= east <= 180.0):
        raise ValueError("bbox requires -180 <= west <= east <= 180")
    if not (-90.0 <= south <= north <= 90.0):
        raise ValueError("bbox requires -90 <= south <= north <= 90")
    return v


BBox = Annotated[tuple[float, float, float, float], AfterValidator(_check_bbox)]


class Interval(Contract):
    """Predictive interval. Invariant (BOOT-P3): ``p10 <= p50 <= p90``."""

    p10: float
    p50: float
    p90: float

    @model_validator(mode="after")
    def _ordered(self) -> Interval:
        if not (self.p10 <= self.p50 <= self.p90):
            raise ValueError("Interval requires p10 <= p50 <= p90")
        return self


class Citation(Contract):
    doc_id: str = Field(min_length=1)
    title: str
    publisher: str
    page: int = Field(ge=1)
    span: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]]
    quote: str = Field(max_length=400)
    lang: Lang
    url: str | None

    @model_validator(mode="after")
    def _span_ordered(self) -> Citation:
        if self.span[0] > self.span[1]:
            raise ValueError("Citation.span requires start <= end")
        return self


class EvidenceRef(Contract):
    """What the Brain stores for provenance. ``json_pointer`` is an RFC 6901 pointer.

    v0.4 clarification: ``run_id`` is the call-level ``provenance.run_id`` of the ToolResult the
    pointer points into (or the Brain-generated id for Brain-origin evidence). It is the key of
    ``GET /evidence/{run_id}``.
    """

    run_id: str = Field(min_length=1)
    organ: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    json_pointer: JsonPointer


class FeatureCollection(Contract):
    """Minimal GeoJSON FeatureCollection (WGS84). Features are kept as plain dicts."""

    type: Literal["FeatureCollection"]
    features: list[dict[str, Any]]
    bbox: list[float] | None = None
