"""eyes-mcp tool I/O (mcp-contracts.md section 3).

Ambiguities: ``reference_overlay_geojson`` and ``validation`` are required in the output
(``| null`` without ``?``). ``tile_size`` must be positive.
"""

from __future__ import annotations

from datetime import date

from pydantic import AwareDatetime, Field

from stitch_common.base import Contract
from stitch_common.types import BBox, FeatureCollection, NonNeg, Slug, Unit


class SegmentFloodIn(Contract):
    region_id: Slug
    date: date
    bbox: BBox | None = None
    tile_size: int = Field(default=256, gt=0)


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
    confidence: Unit
    tiles_processed: int = Field(ge=0)
    source_scene: SourceScene
    validation: Validation
    reference_overlay_geojson: FeatureCollection | None


class CompareWithPermanentWaterIn(Contract):
    region_id: Slug
    date: date
    bbox: BBox | None = None


class DistrictFlood(Contract):
    district_id: str
    name: str
    flooded_km2: NonNeg
    flooded_fraction: Unit


class CompareWithPermanentWaterOut(Contract):
    total_water_km2: NonNeg
    permanent_water_km2: NonNeg
    new_flood_km2: NonNeg
    by_district: list[DistrictFlood]
