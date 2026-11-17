"""Tool cores on the synthetic offline dataset (design 10, 11): error table, labels (EYE-X9),
determinism (EYE-P6), no-water input (EYE-P7, stub), identities (EYE-P3) and the envelope."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from eyes_strategies import ConstantModel
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_common.envelope import ToolResult
from stitch_common.tooling import run_tool
from stitch_eyes.service import (
    DEMO_WARNING,
    EVAL_DATASET,
    MODE_FALLBACK_WARNING,
    NO_FLOOD_WARNING,
    NO_OVERLAY_NOTE,
    NOTE_MODEL,
    NOTE_THRESHOLD,
    EyesService,
)
from stitch_eyes.settings import Settings

ARGS = {"region_id": "pk-test", "date": "2022-08-27"}


def call(svc: EyesService, tool: str, args: dict[str, Any]) -> ToolResult[Any]:
    return asyncio.run(run_tool("eyes", tool, "test", svc.cores()[tool], args))


@pytest.fixture(scope="module")
def svc(synthetic_settings: Settings) -> EyesService:
    return EyesService(synthetic_settings)


def test_segment_flood_on_the_synthetic_scene(svc: EyesService) -> None:
    r = call(svc, "segment_flood", ARGS)
    assert r.ok, r.error
    d = r.data
    # flooded field rows 61..239 x cols 151..249 (179 x 99 px of ~100 m2), lake is permanent
    assert d.flood_extent_km2 == pytest.approx(179 * 99 * 100 / 1e6, rel=0.03)
    assert d.permanent_water_km2 == pytest.approx(np.pi * 40**2 * 100 / 1e6, rel=0.05)
    assert d.tiles_processed == 4 and d.model_variant == "vh-threshold-baseline"
    assert d.valid_fraction == pytest.approx(1 - 5 / 300)
    assert 0.5 <= d.confidence <= 1.0
    assert len(d.extent_geojson.features) >= 1
    # EYE-X9 honest labels
    assert d.validation.validated_for_region is False
    assert d.validation.eval_dataset == EVAL_DATASET == "sen1floods11_test"
    assert d.validation.note == NOTE_THRESHOLD
    assert d.reference_overlay_geojson is None and d.reference_overlay_note == NO_OVERLAY_NOTE
    assert DEMO_WARNING in r.warnings
    p = r.provenance
    assert p.organ == "eyes" and p.mode == "demo" and p.model is not None
    assert p.model.name == "vh-threshold-baseline"
    assert {s.id for s in p.data_sources} >= {"syn-scene", "jrc-gsw-v1.4-occurrence"}


def test_note_constants_say_not_validated() -> None:
    for note in (NOTE_MODEL, NOTE_THRESHOLD):
        assert "Demo scene: Sindh, Aug 2022" in note
        assert "Sen1Floods11 test split only" in note
        assert "not a validated result" in note


def test_eye_p3_compare_identities_and_district_sum(svc: EyesService) -> None:
    r = call(svc, "compare_with_permanent_water", ARGS)
    assert r.ok
    d = r.data
    assert 0 <= d.new_flood_km2 <= d.total_water_km2
    assert d.new_flood_km2 == pytest.approx(d.total_water_km2 - d.permanent_water_km2, abs=2e-6)
    assert sum(x.flooded_km2 for x in d.by_district) == pytest.approx(d.new_flood_km2, abs=2e-6)
    assert [x.district_id for x in d.by_district] == ["pk-test-b", "pk-test-a"]
    assert all(x.district_area_km2 and x.district_area_km2 > 0 for x in d.by_district)
    assert all(x.flooded_roads_km is None for x in d.by_district)
    seg = call(svc, "segment_flood", ARGS).data
    assert seg.flood_extent_km2 == d.new_flood_km2


def test_eye_p6_same_input_same_output(svc: EyesService, synthetic_settings: Settings) -> None:
    a = call(svc, "segment_flood", ARGS)
    fresh = EyesService(synthetic_settings)  # no cache shared
    b = call(fresh, "segment_flood", ARGS)
    assert a.data.model_dump() == b.data.model_dump()
    assert a.provenance.inputs_hash == b.provenance.inputs_hash
    assert a.provenance.run_id != b.provenance.run_id


def test_eye_p7_no_water_stub_gives_zero_area(synthetic_settings: Settings) -> None:
    s = EyesService(synthetic_settings, model=ConstantModel(-12.0))
    r = call(s, "segment_flood", ARGS)
    assert r.ok
    assert r.data.flood_extent_km2 == 0.0 and r.data.permanent_water_km2 == 0.0
    assert r.data.extent_geojson.features == [] and r.data.confidence is None
    assert NO_FLOOD_WARNING in r.warnings
    assert r.data.model_variant is None  # a stub has no contract label, and says so
    assert any("no contract label" in w for w in r.warnings)


def test_all_nodata_window_is_not_found(
    synthetic_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stitch_eyes.pipeline as pl

    monkeypatch.setattr(pl, "read_codes", lambda sc, w: np.zeros((2, w.height, w.width), np.uint8))
    r = call(EyesService(synthetic_settings), "segment_flood", ARGS)
    assert (
        r.error is not None and r.error.code == "NOT_FOUND" and "no valid data" in r.error.message
    )


def test_errors_unknown_region_far_date_and_tolerance(svc: EyesService) -> None:
    r = call(svc, "segment_flood", {"region_id": "pk-nowhere", "date": "2022-08-27"})
    assert r.error is not None and r.error.code == "NOT_FOUND" and not r.error.retryable
    r = call(svc, "segment_flood", {"region_id": "pk-test", "date": "2023-01-01"})
    assert r.error is not None and r.error.code == "NOT_FOUND"
    assert "2022-09-10, 2022-08-27" in r.error.message
    r = call(svc, "segment_flood", {"region_id": "pk-test", "date": "2022-08-29"})
    assert r.ok and any(w.startswith("SCENE_DATE:") for w in r.warnings)


def test_errors_bbox_and_tile_size(svc: EyesService, synthetic_demo: Path) -> None:
    r = call(svc, "segment_flood", {**ARGS, "bbox": [10.0, 10.0, 11.0, 11.0]})
    assert r.error is not None and r.error.code == "NOT_FOUND"
    r = call(svc, "segment_flood", {**ARGS, "tile_size": 100})
    assert r.error is not None and r.error.code == "INVALID_INPUT"
    small = EyesService(dataclasses.replace(svc.settings, max_area_km2=0.5))
    r = call(small, "segment_flood", ARGS)
    assert r.error is not None and r.error.code == "INVALID_INPUT"
    bbox = json.loads((synthetic_demo / "eyes" / "catalog.json").read_text())["scenes"][0]["bbox"]
    r = call(svc, "compare_with_permanent_water", {**ARGS, "bbox": bbox})
    assert r.ok


def test_live_mode_falls_back_to_demo_with_a_warning(svc: EyesService) -> None:
    r = call(svc, "segment_flood", {**ARGS, "mode": "live"})
    assert r.ok and r.provenance.mode == "demo" and MODE_FALLBACK_WARNING in r.warnings


def test_model_hash_mismatch_is_internal(synthetic_demo: Path, tmp_path: Path) -> None:
    src = Path(__file__).resolve().parents[2] / "models"
    check = json.loads((src / "export_check.json").read_text("utf-8"))
    (tmp_path / check["file"]).write_bytes(b"not a model")
    (tmp_path / "export_check.json").write_text(json.dumps(check), "utf-8")
    s = Settings(
        demo_dir=synthetic_demo,
        model_dir=tmp_path,
        model_choice="auto",
        threads=1,
        date_tolerance_days=3,
        max_area_km2=2000.0,
        warm=False,
    )
    svc = EyesService(s)
    r = call(svc, "segment_flood", ARGS)
    assert r.error is not None and r.error.code == "INTERNAL" and "hash" in r.error.message
    assert svc.health()["model"] is False
    missing = EyesService(dataclasses.replace(s, model_dir=tmp_path / "nope"))
    r = call(missing, "segment_flood", ARGS)
    assert r.error is not None and r.error.code == "INTERNAL"


def test_scenes_resource_rows(svc: EyesService) -> None:
    rows = svc.scenes()
    assert [(r.region_id, r.date.isoformat(), r.scene_id) for r in rows] == [
        ("pk-test", "2022-08-27", "syn-scene"),
        ("pk-test", "2022-09-10", "syn-scene-b"),
    ]
    assert all(r.validated_for_region is False for r in rows)


arguments = st.dictionaries(
    st.sampled_from(["region_id", "date", "bbox", "tile_size", "mode", "x"]),
    st.none()
    | st.booleans()
    | st.integers(-5, 5000)
    | st.text(max_size=12)
    | st.lists(st.floats(-200, 200), max_size=5),
    max_size=5,
)


@settings(deadline=None, max_examples=60)
@given(arguments)
def test_envelope_invariant_for_arbitrary_arguments(svc: EyesService, args: dict[str, Any]) -> None:
    """BOOT-P1: any arguments give a well-formed envelope, never an exception."""
    for tool in ("segment_flood", "compare_with_permanent_water"):
        r = call(svc, tool, args)
        assert r.ok == (r.data is not None and r.error is None)
        assert r.ok or r.error is not None
