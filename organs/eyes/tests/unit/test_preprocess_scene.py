"""Quantization (EYE-X7), nodata handling, scene catalog (EYE-X6), bbox windows (EYE-X5)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest
from eyes_strategies import bboxes
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from stitch_common.organs.eyes import SegmentFloodIn
from stitch_eyes.core.preprocess import (
    NODATA,
    QUANT_HI,
    QUANT_LO,
    STEP_DB,
    dequantize_db,
    fill_invalid_db,
    prepare,
    quantize_db,
)
from stitch_eyes.data.scene import (
    Catalog,
    SceneNotFound,
    WindowError,
    read_codes,
    window_for_bbox,
)


@settings(deadline=None)
@given(
    st.lists(
        st.floats(QUANT_LO, QUANT_HI, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=200,
    )
)
def test_eye_x7_roundtrip_error_at_most_0_08_db(values: list[float]) -> None:
    a = np.array(values)
    codes = quantize_db(a)
    assert codes.dtype == np.uint8 and codes.min() >= 1
    back = dequantize_db(codes)
    assert np.max(np.abs(back - a)) <= STEP_DB / 2 + 1e-5 <= 0.08


def test_eye_x7_nodata_is_preserved_and_values_clip() -> None:
    codes = quantize_db(np.array([np.nan, np.inf, -80.0, 40.0]))
    assert codes[0] == NODATA and codes[1] == NODATA
    assert codes[2] == 1 and codes[3] == 255
    back = dequantize_db(codes)
    assert np.isnan(back[0]) and back[2] == pytest.approx(QUANT_LO)
    assert back[3] == pytest.approx(QUANT_HI, abs=1e-5)


def test_training_and_organ_share_one_quantization() -> None:
    """The training loader imports the organ's preprocess module (one source of truth)."""
    src = (Path(__file__).resolve().parents[2] / "training" / "data.py").read_text("utf-8")
    assert "from stitch_eyes.core.preprocess import" in src
    assert "def quantize_db" not in src


def test_prepare_fills_nodata_with_the_valid_median() -> None:
    codes = np.full((2, 4, 4), 100, np.uint8)
    codes[0, 0, 0] = 0
    codes[1, 3, 3] = 0
    codes[:, 1, 1] = 50
    p = prepare(codes)
    assert p.valid.sum() == 14 and p.valid_fraction == pytest.approx(14 / 16)
    assert np.all(np.isfinite(p.db))
    assert p.db[0, 0, 0] == pytest.approx(dequantize_db(np.uint8(100)))
    with pytest.raises(ValueError):
        prepare(np.zeros((2, 3, 3), np.uint8))


def test_fill_invalid_db_for_training_chips() -> None:
    a = np.array([[[1.0, np.nan], [3.0, 5.0]]], dtype=np.float32)
    filled, valid = fill_invalid_db(a)
    assert filled[0, 0, 1] == 3.0 and valid.tolist() == [[True, False], [True, True]]


def test_eye_x6_not_found_lists_nearest_dates_by_distance(synthetic_demo: Path) -> None:
    cat = Catalog(synthetic_demo / "eyes")
    scene, days = cat.find("pk-test", date(2022, 8, 28), 3)
    assert scene.scene_id == "syn-scene" and days == 1
    with pytest.raises(SceneNotFound) as e:
        cat.find("pk-test", date(2022, 9, 30), 3)
    assert e.value.nearest == [date(2022, 9, 10), date(2022, 8, 27)]
    assert "2022-09-10, 2022-08-27" in str(e.value)
    with pytest.raises(SceneNotFound) as e2:
        cat.find("pk-nowhere", date(2022, 8, 27), 3)
    assert e2.value.nearest == [] and "pk-test" in str(e2.value)


def test_window_mapping_round_trip(synthetic_demo: Path) -> None:
    from pyproj import Transformer

    scene = Catalog(synthetic_demo / "eyes").scenes[0]
    tr = Transformer.from_crs(scene.crs, "EPSG:4326", always_xy=True)
    # a UTM box of rows 40..140 and cols 30..90, converted to a WGS84 bbox
    x0, x1 = scene.x0 + 30 * 10 + 1, scene.x0 + 90 * 10 - 1
    y1, y0 = scene.y1 - 40 * 10 - 1, scene.y1 - 140 * 10 + 1
    w, s = tr.transform(x0, y0)
    e, n = tr.transform(x1, y1)
    win = window_for_bbox(scene, (w, s, e, n), 2000.0)
    # the WGS84 box is slightly larger than the UTM box (grid rotation): at most 2 px
    assert 28 <= win.col0 <= 30 and 90 <= win.col0 + win.width <= 92
    assert 38 <= win.row0 <= 40 and 140 <= win.row0 + win.height <= 142
    codes = read_codes(scene, win)
    assert codes.shape == (2, win.height, win.width)
    t = win.transform(scene)
    assert t.c == scene.x0 + win.col0 * 10 and t.f == scene.y1 - win.row0 * 10


def test_eye_x5_bbox_outside_or_too_large(synthetic_demo: Path) -> None:
    scene = Catalog(synthetic_demo / "eyes").scenes[0]
    with pytest.raises(WindowError) as e:
        window_for_bbox(scene, (10.0, 10.0, 11.0, 11.0), 2000.0)
    assert e.value.kind == "not_found"
    with pytest.raises(WindowError) as e2:
        window_for_bbox(scene, (60.0, 20.0, 75.0, 30.0), 1.0)
    assert e2.value.kind == "too_large"


@settings(deadline=None)
@given(bboxes(valid=False))
def test_eye_x5_reversed_or_empty_bbox_is_invalid_input(
    bbox: tuple[float, float, float, float],
) -> None:
    """Reversed boxes fail the contract model; zero-width boxes fail the service check."""
    from stitch_common.tooling import ToolFailure
    from stitch_eyes.service import check_request

    args = {"region_id": "pk-sindh", "date": "2022-08-27", "bbox": list(bbox)}
    try:
        p = SegmentFloodIn.model_validate(args)
    except ValidationError:
        return
    with pytest.raises(ToolFailure) as e:
        check_request(p.bbox, 256)
    assert e.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("tile", [0, 3, 100, 2048])
def test_eye_x5_tile_size_must_be_a_power_of_two(tile: int) -> None:
    from stitch_common.tooling import ToolFailure
    from stitch_eyes.service import check_request

    with pytest.raises(ToolFailure) as e:
        check_request(None, tile)
    assert e.value.code == "INVALID_INPUT"


@settings(deadline=None)
@given(bboxes(valid=True))
def test_eye_x5_valid_bbox_is_accepted(bbox: tuple[float, float, float, float]) -> None:
    p = SegmentFloodIn(region_id="pk-sindh", date=date(2022, 8, 27), bbox=bbox)
    assert p.bbox is not None
