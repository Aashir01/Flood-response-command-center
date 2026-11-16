"""ORA-R1.2, R8.3, R11.1: the committed demo dataset loads offline and is well formed."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from stitch_oracle.data.loader import (
    DISCHARGE,
    STATION_FIELDS,
    STATIONS,
    SUBDIR,
    WEATHER,
    DatasetError,
    demo_dir,
    load_demo,
    load_files,
    validate_discharge,
)

ROOT = demo_dir()
BASE = ROOT / SUBDIR


def test_loads_offline_with_expected_shape() -> None:
    d = load_demo()
    assert d.start == date(1997, 1, 1) and d.end == date(2023, 12, 31)
    assert {"indus-guddu", "indus-sukkur", "indus-kotri"} <= set(d.catalog.forecast_ids)
    n_days = (d.end - d.start).days + 1
    assert len(d.frames.discharge) == n_days * len(d.catalog.ids)
    assert len(d.frames.rain_points) == 4 and d.frames.temp_point


def test_dtypes_keys_no_gaps_no_negatives() -> None:
    d = load_demo()
    dis, wea = d.frames.discharge, d.frames.weather
    assert dis["discharge_m3s"].dtype == "float32"
    assert not dis.duplicated(["date", "station_id"]).any()
    assert not wea.duplicated(["date", "point_id"]).any()
    assert dis["discharge_m3s"].min() >= 0 and wea["precip_mm"].min() >= 0
    assert not dis.isna().any().any() and not wea.isna().any().any()


def test_includes_the_2022_season() -> None:
    dis = load_demo().frames.discharge
    season = dis[(dis["date"] >= date(2022, 6, 1)) & (dis["date"] <= date(2022, 10, 31))]
    assert len(season) == 153 * dis["station_id"].nunique()


def test_size_budget_under_2_mb() -> None:
    total = sum((BASE / n).stat().st_size for n in (DISCHARGE, WEATHER, STATIONS))
    assert total < 2_000_000


def test_stations_json_fields_complete_and_labelled_as_cells() -> None:
    import json

    meta = json.loads((BASE / STATIONS).read_text(encoding="utf-8"))
    assert meta["target_kind"] == "modeled_glofas"
    for s in meta["stations"]:
        assert all(f in s for f in STATION_FIELDS)
        assert s["label"].startswith("GloFAS grid cell nearest to ")
        assert abs(s["cell_lat"] - s["requested_lat"]) <= 0.2
        assert abs(s["cell_lon"] - s["requested_lon"]) <= 0.2
        assert s["threshold_method"] == "modeled_5yr_return_level"
    for sid, c in meta["continuity"].items():
        assert c["no_gaps_2022_06_to_2023_12"], sid


def test_manifest_records_cells_and_hashes() -> None:
    text = (BASE / "MANIFEST.md").read_text(encoding="utf-8")
    assert "CC BY 4.0" in text and "modeled" in text
    d = load_demo()
    for s in d.catalog.stations:
        assert f"{s.cell_lat}, {s.cell_lon}" in text


def test_rejects_negative_and_wrong_dtype() -> None:
    df = pd.DataFrame(
        {"date": [date(2020, 1, 1)], "station_id": ["x"], "discharge_m3s": [-1.0]}
    ).astype({"discharge_m3s": "float32"})
    with pytest.raises(DatasetError, match="negative"):
        validate_discharge(df)
    with pytest.raises(DatasetError, match="float32"):
        validate_discharge(df.astype({"discharge_m3s": "float64"}))


def test_rejects_gap(tmp_path: Path) -> None:
    import shutil

    target = tmp_path / SUBDIR
    shutil.copytree(BASE, target)
    dis = pd.read_parquet(target / DISCHARGE)
    dis = dis[dis["date"] != date(2022, 8, 1)]
    dis.to_parquet(target / DISCHARGE, index=False)
    with pytest.raises(DatasetError, match="contiguous"):
        load_files(tmp_path)


def test_missing_directory_is_a_dataset_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="missing"):
        load_files(tmp_path)
