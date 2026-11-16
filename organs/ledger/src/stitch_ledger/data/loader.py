"""Load the committed district dataset (``data/demo/ledger/districts.parquet``), offline.

Schema and range checks run on every load, so a damaged file fails loudly instead of feeding the
solver. The data directory is ``$STITCH_DEMO_DIR`` if set, otherwise the first ``data/demo``
found above this file (the repository checkout).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stitch_common.provenance import DataSource

SCENARIOS: dict[str, str] = {"demo-sindh-2022": "ledger/districts.parquet"}
REQUIRED: dict[str, pa.DataType] = {
    "district_id": pa.string(),
    "name": pa.string(),
    "province": pa.string(),
    "population": pa.int64(),
    "road_access": pa.float64(),
    "alt_delivery_fraction": pa.float64(),
    "default_severity": pa.float64(),
}
UNIT_COLUMNS = ("road_access", "alt_delivery_fraction", "default_severity")


class UnknownScenario(KeyError):
    """No dataset for this ``scenario_id`` (maps to ``NOT_FOUND``)."""


class DatasetError(ValueError):
    """The committed dataset violates its schema (a build or packaging bug)."""


@dataclass(frozen=True, slots=True)
class DistrictRow:
    district_id: str
    name: str
    province: str
    population: int
    road_access: float
    alt_delivery_fraction: float
    default_severity: float


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    districts: tuple[DistrictRow, ...]
    data_sources: tuple[DataSource, ...]


def demo_dir() -> Path:
    env = os.environ.get("STITCH_DEMO_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "demo"
        if candidate.is_dir():
            return candidate
    return Path("data") / "demo"


def validate_table(table: pa.Table) -> None:
    """Raise ``DatasetError`` unless the table has the required columns, types and ranges."""
    names = set(table.column_names)
    missing = sorted(set(REQUIRED) - names)
    if missing:
        raise DatasetError(f"missing columns: {', '.join(missing)}")
    for name, kind in REQUIRED.items():
        if table.schema.field(name).type != kind:
            raise DatasetError(
                f"column {name} must be {kind}, found {table.schema.field(name).type}"
            )
        if table.column(name).null_count:
            raise DatasetError(f"column {name} has nulls")
    ids = table.column("district_id").to_pylist()
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        raise DatasetError("district_id must be unique and non-empty")
    for col in UNIT_COLUMNS:
        for v in table.column(col).to_pylist():
            if not (isinstance(v, float) and math.isfinite(v) and 0.0 <= v <= 1.0):
                raise DatasetError(f"column {col} must be within [0, 1]")
    if any(v < 0 for v in table.column("population").to_pylist()):
        raise DatasetError("population must be >= 0")


def _sources(meta: dict[str, str]) -> tuple[DataSource, ...]:
    osm_day: date | None = None
    stamp = meta.get("osm_timestamp_base", "")
    if len(stamp) >= 10:
        try:
            osm_day = date.fromisoformat(stamp[:10])
        except ValueError:
            osm_day = None
    return (
        DataSource(
            id="worldpop-pak-ppp-2020-1km",
            name="WorldPop Global 2000-2020 1 km, Pakistan, 2020 (modelled population)",
            license="CC BY 4.0",
            as_of=None,
        ),
        DataSource(
            id="osm-roads-sindh",
            name="OpenStreetMap roads, primary to tertiary (road_access density proxy)",
            license="ODbL 1.0",
            as_of=osm_day,
        ),
        DataSource(
            id="geoboundaries-pak-adm2-2019",
            name="geoBoundaries gbOpen PAK ADM2, boundary year 2019",
            license="CC BY 4.0",
            as_of=None,
        ),
        DataSource(
            id="ledger-demo-assumptions",
            name=(
                "Illustrative assumptions: default_severity prior and alt_delivery_fraction "
                "(not measured)"
            ),
            license="Project assumption (MIT repository)",
            as_of=None,
        ),
    )


def load_scenario(scenario_id: str, root: Path | None = None) -> Scenario:
    """Read and validate a scenario. Raises ``UnknownScenario`` or ``DatasetError``."""
    rel = SCENARIOS.get(scenario_id)
    if rel is None:
        raise UnknownScenario(scenario_id)
    path = (root or demo_dir()) / rel
    try:
        table = pq.read_table(path)
    except (OSError, pa.ArrowException) as exc:
        raise DatasetError(f"cannot read {path.name}: {exc}") from exc
    validate_table(table)
    raw_meta = table.schema.metadata or {}
    meta = {k.decode(): v.decode() for k, v in raw_meta.items()}
    rows = tuple(
        DistrictRow(**{k: r[k] for k in REQUIRED})
        for r in sorted(table.select(list(REQUIRED)).to_pylist(), key=lambda r: r["district_id"])
    )
    return Scenario(scenario_id, rows, _sources(meta))
