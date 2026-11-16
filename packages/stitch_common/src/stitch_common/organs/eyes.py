"""eyes-mcp tool I/O (mcp-contracts.md section 3).

Ambiguities: ``reference_overlay_geojson`` and ``validation`` are required in the output
(``| null`` without ``?``). ``tile_size`` must be positive.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field

from stitch_common.base import Contract
from stitch_common.types import BBox, FeatureCollection, Mode, NonNeg, Slug, Unit

ModelVariant = Literal["unet-resnet18-s1-int8", "vh-threshold-baseline"]


class SegmentFloodIn(Contract):
    region_id: Slug
    date: date
    bbox: BBox | None = None
    tile_size: int = Field(default=256, gt=0)
    mode: Mode | None = None  # v0.4: optional, the Brain passes the requested mode


class SourceScene(Contract):
    sensor: str
    acquired: AwareDatetime
    scene_id: str


class Validation(Contract):
    validated_for_region: bool
    eval_dataset: str
    note: str


class SegmentFloodOut(Contract):
    flood_extent_km2: NonNeg
    extent_geojson: FeatureCollection
    permanent_water_km2: NonNeg
    confidence: Unit | None  # v0.4: null when no flood pixels exist
    tiles_processed: int = Field(ge=0)
    source_scene: SourceScene
    validation: Validation
    reference_overlay_geojson: FeatureCollection | None
    # v0.4 (all optional, absent means unknown):
    reference_overlay_note: str | None = None  # source, product date, licence, "qualitative only"
    valid_fraction: Unit | None = None  # share of window pixels with valid data
    model_variant: ModelVariant | None = None  # honest fallback reporting


class CompareWithPermanentWaterIn(Contract):
    region_id: Slug
    date: date
    bbox: BBox | None = None
    mode: Mode | None = None  # v0.4


class DistrictFlood(Contract):
    district_id: str
    name: str
    flooded_km2: NonNeg
    flooded_fraction: Unit
    district_area_km2: NonNeg | None = None  # v0.4: district area inside the window
    flooded_roads_km: NonNeg | None = None  # v0.4: flooded road length in the district


class CompareWithPermanentWaterOut(Contract):
    total_water_km2: NonNeg
    permanent_water_km2: NonNeg
    new_flood_km2: NonNeg
    by_district: list[DistrictFlood]


class SceneInfo(Contract):
    """One item of the read-only resource ``eyes://scenes`` (v0.4)."""

    region_id: Slug
    date: date
    scene_id: str
    sensor: str | None = None
    validated_for_region: bool | None = None
