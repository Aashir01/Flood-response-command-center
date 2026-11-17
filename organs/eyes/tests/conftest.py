"""Eyes test fixtures.

* ``tests/strategies.py`` is importable as ``eyes_strategies`` (pytest runs with
  ``--import-mode=importlib``).
* ``synthetic_demo``: a tiny offline demo dataset (catalog, 300 x 280 px COG in UTM 42N with a
  water blob, permanent-water raster, two district polygons) for fast service tests.
* ``real_service``: the service on the committed demo data and shipped model (module-scoped, the
  demo scene is segmented once per test module through the cache).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_path = Path(__file__).parent / "strategies.py"
if "eyes_strategies" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("eyes_strategies", _path)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["eyes_strategies"] = _module
    _spec.loader.exec_module(_module)

from stitch_eyes.settings import ORGAN_DIR, REPO, Settings  # noqa: E402

SYN_H, SYN_W = 300, 280
SYN_X0, SYN_Y1 = 370_000.0, 2_935_000.0


def _settings(demo: Path, model_dir: Path, choice: str) -> Settings:
    return Settings(
        demo_dir=demo,
        model_dir=model_dir,
        model_choice=choice,
        threads=2,
        date_tolerance_days=3,
        max_area_km2=2000.0,
        warm=False,
    )


@pytest.fixture(scope="session")
def synthetic_demo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    from stitch_eyes.core.preprocess import quantize_db

    root = tmp_path_factory.mktemp("demo")
    eyes = root / "eyes"
    (eyes / "scenes").mkdir(parents=True)
    rng = np.random.default_rng(0)
    db = np.stack([rng.normal(-9.0, 1.0, (SYN_H, SYN_W)), rng.normal(-15.0, 1.0, (SYN_H, SYN_W))])
    yy, xx = np.mgrid[0:SYN_H, 0:SYN_W]
    lake = (yy - 150) ** 2 + (xx - 80) ** 2 < 40**2  # permanent lake
    flood = (yy > 60) & (yy < 240) & (xx > 150) & (xx < 250)  # flooded field
    db[0][lake | flood] = -20.0 + rng.normal(0, 0.5, int((lake | flood).sum()))
    db[1][lake | flood] = -27.0 + rng.normal(0, 0.5, int((lake | flood).sum()))
    codes = quantize_db(db)
    codes[:, :5, :] = 0  # a nodata strip
    transform = from_origin(SYN_X0, SYN_Y1, 10.0, 10.0)
    scene = eyes / "scenes" / "syn.tif"
    prof = {
        "driver": "GTiff",
        "width": SYN_W,
        "height": SYN_H,
        "count": 2,
        "dtype": "uint8",
        "crs": "EPSG:32642",
        "transform": transform,
        "nodata": 0,
    }
    with rasterio.open(scene, "w", **prof) as dst:
        dst.write(codes)
    perm = eyes / "jrc_perm_water_pk-test.tif"
    with rasterio.open(perm, "w", **{**prof, "count": 1, "nodata": None}) as dst:
        dst.write(lake.astype(np.uint8), 1)
    x1, y0 = SYN_X0 + SYN_W * 10, SYN_Y1 - SYN_H * 10
    inv = Transformer.from_crs("EPSG:32642", "EPSG:4326", always_xy=True)
    lon0, lat0 = inv.transform(SYN_X0, y0)
    lon1, lat1 = inv.transform(x1, SYN_Y1)
    import hashlib

    catalog = {
        "scenes": [
            {
                "region_id": "pk-test",
                "scene_id": "syn-scene",
                "date": "2022-08-27",
                "acquired": "2022-08-27T13:36:21Z",
                "sensor": "synthetic S1",
                "file": "scenes/syn.tif",
                "sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
                "crs": "EPSG:32642",
                "resolution_m": 10.0,
                "shape": [SYN_H, SYN_W],
                "bounds_utm": [SYN_X0, y0, x1, SYN_Y1],
                "bbox": [lon0, lat0, lon1, lat1],
                "validated_region": False,
                "license": "test",
                "attribution": "synthetic",
                "source": {"provider": "test"},
                "perm_water": {"file": perm.name},
            },
            {
                "region_id": "pk-test",
                "scene_id": "syn-scene-b",
                "date": "2022-09-10",
                "acquired": "2022-09-10T13:36:21Z",
                "sensor": "synthetic S1",
                "file": "scenes/syn.tif",
                "sha256": "b" * 64,
                "crs": "EPSG:32642",
                "resolution_m": 10.0,
                "shape": [SYN_H, SYN_W],
                "bounds_utm": [SYN_X0, y0, x1, SYN_Y1],
                "bbox": [lon0, lat0, lon1, lat1],
                "validated_region": False,
                "license": "test",
                "attribution": "synthetic",
                "source": {"provider": "test"},
                "perm_water": {"file": perm.name},
            },
        ]
    }
    (eyes / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    # two districts split at the middle column, slightly larger than the scene
    xm = SYN_X0 + 140 * 10

    def poly(xa: float, xb: float) -> dict[str, object]:
        pts = [(xa, y0 - 50), (xb, y0 - 50), (xb, SYN_Y1 + 50), (xa, SYN_Y1 + 50), (xa, y0 - 50)]
        return {"type": "Polygon", "coordinates": [[list(inv.transform(x, y)) for x, y in pts]]}

    feats = [
        {
            "type": "Feature",
            "properties": {"district_id": "pk-test-a", "name": "A"},
            "geometry": poly(SYN_X0 - 50, xm),
        },
        {
            "type": "Feature",
            "properties": {"district_id": "pk-test-b", "name": "B"},
            "geometry": poly(xm, x1 + 50),
        },
    ]
    (root / "boundaries").mkdir()
    (root / "boundaries" / "pk_districts.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8"
    )
    return root


@pytest.fixture(scope="session")
def synthetic_settings(synthetic_demo: Path) -> Settings:
    return _settings(synthetic_demo, ORGAN_DIR / "models", "threshold")


@pytest.fixture(scope="session")
def demo_settings() -> Settings:
    return _settings(REPO / "data" / "demo", ORGAN_DIR / "models", "auto")


@pytest.fixture(scope="session")
def real_service(demo_settings: Settings) -> object:
    from stitch_eyes.service import EyesService

    return EyesService(demo_settings)
