"""The committed demo dataset loads offline and satisfies its schema (LED-R2.3, LED-R11.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stitch_ledger.data.loader import (
    DatasetError,
    UnknownScenario,
    demo_dir,
    load_scenario,
    validate_table,
)


def test_committed_dataset_loads_with_expected_shape() -> None:
    s = load_scenario("demo-sindh-2022")
    assert len(s.districts) == 22
    ids = [d.district_id for d in s.districts]
    assert ids == sorted(ids) and len(set(ids)) == 22
    assert all(i.startswith("pk-sindh-") for i in ids)
    assert all(0.0 <= d.road_access <= 1.0 for d in s.districts)
    assert all(0.0 <= d.alt_delivery_fraction <= 1.0 for d in s.districts)
    assert all(0.0 <= d.default_severity <= 1.0 for d in s.districts)
    assert all(d.population > 0 for d in s.districts)
    assert 40e6 < sum(d.population for d in s.districts) < 60e6


def test_sources_name_the_licenses_and_label_the_assumptions() -> None:
    s = load_scenario("demo-sindh-2022")
    by_id = {src.id: src for src in s.data_sources}
    assert by_id["worldpop-pak-ppp-2020-1km"].license == "CC BY 4.0"
    assert by_id["osm-roads-sindh"].license.startswith("ODbL")
    assert by_id["osm-roads-sindh"].as_of is not None
    assert "not measured" in by_id["ledger-demo-assumptions"].name


def test_boundaries_file_matches_the_dataset_ids_and_is_small() -> None:
    path = demo_dir() / "boundaries" / "pk_districts.geojson"
    assert path.stat().st_size < 1_000_000
    gj = json.loads(path.read_text(encoding="utf-8"))
    ids = {f["properties"]["district_id"] for f in gj["features"]}
    assert ids == {d.district_id for d in load_scenario("demo-sindh-2022").districts}


def test_unknown_scenario_is_reported() -> None:
    with pytest.raises(UnknownScenario):
        load_scenario("nope")


def _table(**override: list[object]) -> pa.Table:
    cols: dict[str, list[object]] = {
        "district_id": ["a", "b"],
        "name": ["A", "B"],
        "province": ["P", "P"],
        "population": [10, 20],
        "road_access": [0.5, 1.0],
        "alt_delivery_fraction": [0.0, 0.1],
        "default_severity": [0.3, 0.9],
    }
    cols.update(override)
    schema = pa.schema(
        [
            ("district_id", pa.string()),
            ("name", pa.string()),
            ("province", pa.string()),
            ("population", pa.int64()),
            ("road_access", pa.float64()),
            ("alt_delivery_fraction", pa.float64()),
            ("default_severity", pa.float64()),
        ]
    )
    return pa.table(cols, schema=schema)


def test_validation_accepts_a_good_table() -> None:
    validate_table(_table())


@pytest.mark.parametrize(
    "override",
    [
        {"district_id": ["a", "a"]},
        {"district_id": ["a", ""]},
        {"road_access": [0.5, 1.5]},
        {"road_access": [0.5, -0.1]},
        {"default_severity": [0.5, float("nan")]},
        {"alt_delivery_fraction": [0.0, 2.0]},
        {"population": [10, -1]},
        {"name": ["A", None]},
    ],
)
def test_validation_rejects_bad_tables(override: dict[str, list[object]]) -> None:
    with pytest.raises(DatasetError):
        validate_table(_table(**override))


def test_validation_rejects_missing_columns_and_wrong_types() -> None:
    with pytest.raises(DatasetError, match="missing"):
        validate_table(_table().drop_columns(["road_access"]))
    wrong = _table().set_column(3, "population", pa.array([1.5, 2.5], type=pa.float64()))
    with pytest.raises(DatasetError, match="population"):
        validate_table(wrong)


def test_a_damaged_file_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / "ledger").mkdir()
    pq.write_table(_table(road_access=[0.5, 7.0]), tmp_path / "ledger" / "districts.parquet")
    with pytest.raises(DatasetError):
        load_scenario("demo-sindh-2022", root=tmp_path)
    with pytest.raises(DatasetError, match="cannot read"):
        load_scenario("demo-sindh-2022", root=tmp_path / "missing")
