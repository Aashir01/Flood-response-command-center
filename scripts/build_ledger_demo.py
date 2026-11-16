"""Build the Ledger demo dataset for ``demo-sindh-2022`` (dev time only, needs the network once).

    uv run --with rasterio --with shapely python scripts/build_ledger_demo.py --fetch
    uv run --with rasterio --with shapely python scripts/build_ledger_demo.py        # from data/raw

Inputs (cached in ``data/raw/ledger/``, git-ignored):

* geoBoundaries gbOpen PAK ADM2, simplified geometry (boundary year 2019). 22 Sindh districts
  are selected by name. CC BY 4.0 (site statement; the per-boundary metadata says Public Domain).
* WorldPop Global 2000-2020 1 km "pak_ppp_2020_1km_Aggregated.tif" (people per pixel, 2020,
  census-adjusted). CC BY 4.0. Summed over the pixels whose centre lies inside each district.
* OpenStreetMap via the Overpass API: motorway, trunk, primary, secondary and tertiary ways in the
  Sindh bounding box. ODbL. Length is clipped to each district and divided by its area.

Outputs (committed):

* ``data/demo/boundaries/pk_districts.geojson`` (shared with the Eyes organ),
* ``data/demo/ledger/districts.parquet``.

Columns that are measured from the sources: ``population``, ``road_km``, ``area_km2`` and
``road_access`` (a documented proxy, see ``road_access`` below). Columns that are labelled
assumptions: ``alt_delivery_fraction`` and ``default_severity``. Nothing here is a measurement of
flood-time conditions.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import itertools
import json
import math
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "ledger"
BOUNDARIES_OUT = REPO / "data" / "demo" / "boundaries" / "pk_districts.geojson"
PARQUET_OUT = REPO / "data" / "demo" / "ledger" / "districts.parquet"

GEOBOUNDARIES_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/PAK/ADM2/"
    "geoBoundaries-PAK-ADM2_simplified.geojson"
)
WORLDPOP_URL = (
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2020/PAK/"
    "pak_ppp_2020_1km_Aggregated.tif"
)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = (
    '[out:json][timeout:600];way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]'
    "(23.6,66.6,28.5,71.2);out geom qt;"
)
USER_AGENT = "stitch-ledger-demo-build/0.1 (hackathon demo; non-commercial)"

BOUNDARY_FILE = RAW / "pak_adm2_simplified.geojson"
POP_FILE = RAW / "pak_ppp_2020_1km_Aggregated.tif"
ROADS_FILE = RAW / "osm_sindh_roads.json"

# geoBoundaries (2019 vintage) name -> (display name, slug). Larkana is not a separate unit in
# this boundary set and Sujawal (split from Thatta in 2013) is also absent.
SINDH: dict[str, tuple[str, str]] = {
    "Badin": ("Badin", "badin"),
    "Dadu": ("Dadu", "dadu"),
    "Ghotki": ("Ghotki", "ghotki"),
    "Hyderabad": ("Hyderabad", "hyderabad"),
    "Jacobabad": ("Jacobabad", "jacobabad"),
    "Jamshoro": ("Jamshoro", "jamshoro"),
    "Karachi": ("Karachi", "karachi"),
    "Kashmore": ("Kashmore", "kashmore"),
    "Khairpur": ("Khairpur", "khairpur"),
    "Matiari": ("Matiari", "matiari"),
    "Mirpurkhas": ("Mirpur Khas", "mirpur-khas"),
    "Nawabshah": ("Nawabshah (Shaheed Benazirabad)", "nawabshah"),
    "Naushehro Feroze": ("Naushahro Feroze", "naushahro-feroze"),
    "Qambar Shahdadkot": ("Qambar Shahdadkot", "qambar-shahdadkot"),
    "Sanghar": ("Sanghar", "sanghar"),
    "Shikarpur": ("Shikarpur", "shikarpur"),
    "Sukkur": ("Sukkur", "sukkur"),
    "Tando Allahyar": ("Tando Allahyar", "tando-allahyar"),
    "Tando Muhammad Khan": ("Tando Muhammad Khan", "tando-muhammad-khan"),
    "Tharparkar": ("Tharparkar", "tharparkar"),
    "Thatta": ("Thatta", "thatta"),
    "Umerkot": ("Umerkot", "umerkot"),
}

# ASSUMPTION (labelled): illustrative severity prior by analyst judgement, in tiers. Districts
# widely reported as hardest hit in the 2022 floods get the highest tier. This is NOT a measured
# or official figure; replace it with PDMA/NDMA district data when available.
SEVERITY_TIERS: dict[float, tuple[str, ...]] = {
    0.9: ("dadu", "jamshoro", "qambar-shahdadkot", "khairpur"),
    0.75: (
        "sanghar",
        "shikarpur",
        "jacobabad",
        "badin",
        "nawabshah",
        "naushahro-feroze",
        "mirpur-khas",
    ),
    0.5: (
        "sukkur",
        "kashmore",
        "ghotki",
        "tando-allahyar",
        "tando-muhammad-khan",
        "matiari",
        "umerkot",
        "hyderabad",
    ),
    0.3: ("tharparkar", "thatta"),
    0.1: ("karachi",),
}
# ASSUMPTION (labelled): share of a district's people that boats or helicopters could carry.
# Illustrative 5% for a few districts with large inundated areas, 0 elsewhere. Not measured.
ALT_DELIVERY: dict[str, float] = {
    "dadu": 0.05,
    "jamshoro": 0.05,
    "qambar-shahdadkot": 0.05,
    "badin": 0.05,
}
ROAD_ACCESS_PERCENTILE = 90.0


def _download(url: str, dest: Path, *, post: bytes | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url, data=post, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=900) as resp, dest.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)


def fetch() -> None:
    """Download the three inputs into ``data/raw/ledger`` (skips files that exist)."""
    import urllib.parse

    if not BOUNDARY_FILE.exists():
        _download(GEOBOUNDARIES_URL, BOUNDARY_FILE)
    if not POP_FILE.exists():
        _download(WORLDPOP_URL, POP_FILE)
    if not ROADS_FILE.exists():
        body = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode()
        _download(OVERPASS_URL, ROADS_FILE, post=body)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def line_km(coords: list[tuple[float, float]]) -> float:
    return sum(haversine_km(*a, *b) for a, b in itertools.pairwise(coords))


def area_km2(geom: Any) -> float:
    """Area of a lon/lat polygon with a Lambert cylindrical equal-area projection."""
    r = 6371.0088

    def ring_area(coords: Any) -> float:
        pts = [(math.radians(x), math.sin(math.radians(y))) for x, y in coords]
        return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in itertools.pairwise(pts))

    total = 0.0
    for poly in getattr(geom, "geoms", [geom]):
        total += abs(ring_area(poly.exterior.coords)) - sum(
            abs(ring_area(i.coords)) for i in poly.interiors
        )
    return total * r * r


def _round_coords(coords: Any, nd: int = 4) -> Any:
    if isinstance(coords[0], int | float):
        return [round(coords[0], nd), round(coords[1], nd)]
    return [_round_coords(c, nd) for c in coords]


def build(as_of: str) -> None:
    shapely_geometry = importlib.import_module("shapely.geometry")
    shapely_strtree = importlib.import_module("shapely.strtree")
    rasterio = importlib.import_module("rasterio")
    rio_mask = importlib.import_module("rasterio.mask")
    pa = importlib.import_module("pyarrow")
    pq = importlib.import_module("pyarrow.parquet")
    import numpy as np

    boundaries = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for feat in boundaries["features"]:
        src_name = feat["properties"]["shapeName"]
        if src_name not in SINDH:
            continue
        name, slug = SINDH[src_name]
        geom = shapely_geometry.shape(feat["geometry"]).buffer(0)
        rows.append(
            {
                "district_id": f"pk-sindh-{slug}",
                "slug": slug,
                "name": name,
                "geom": geom,
                "shape_id": feat["properties"]["shapeID"],
            }
        )
    if len(rows) != len(SINDH):
        raise SystemExit(f"expected {len(SINDH)} Sindh districts, found {len(rows)}")
    rows.sort(key=lambda r: r["district_id"])

    # --- population: WorldPop 1 km, pixel centres inside the polygon ---
    with rasterio.open(POP_FILE) as src:
        for r in rows:
            data, _ = rio_mask.mask(src, [shapely_geometry.mapping(r["geom"])], crop=True)
            arr = data[0].astype("float64")
            nodata = src.nodata
            valid = arr != nodata if nodata is not None else np.ones_like(arr, dtype=bool)
            valid &= np.isfinite(arr) & (arr >= 0)
            r["population"] = round(float(arr[valid].sum()))

    # --- roads: OSM length clipped to each district ---
    roads = json.loads(ROADS_FILE.read_text(encoding="utf-8"))
    osm_timestamp = roads.get("osm3s", {}).get("timestamp_osm_base", "")
    tree = shapely_strtree.STRtree([r["geom"] for r in rows])
    for r in rows:
        r["road_km"] = 0.0
    n_ways = 0
    for el in roads["elements"]:
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(pts) < 2:
            continue
        n_ways += 1
        line = shapely_geometry.LineString(pts)
        for idx in tree.query(line, predicate="intersects"):
            clipped = line.intersection(rows[int(idx)]["geom"])
            for part in getattr(clipped, "geoms", [clipped]):
                if part.geom_type == "LineString":
                    rows[int(idx)]["road_km"] += line_km(list(part.coords))
    for r in rows:
        r["area_km2"] = area_km2(r["geom"])
        r["road_density"] = r["road_km"] / r["area_km2"]
    p90 = float(np.percentile([r["road_density"] for r in rows], ROAD_ACCESS_PERCENTILE))
    sev = {slug: tier for tier, slugs in SEVERITY_TIERS.items() for slug in slugs}
    for r in rows:
        r["road_access"] = round(min(1.0, max(0.0, r["road_density"] / p90)), 4)
        r["alt_delivery_fraction"] = ALT_DELIVERY.get(r["slug"], 0.0)
        r["default_severity"] = sev[r["slug"]]

    # --- outputs ---
    features = []
    for r in rows:
        geom = shapely_geometry.mapping(r["geom"].simplify(0.003, preserve_topology=True))
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "district_id": r["district_id"],
                    "name": r["name"],
                    "province": "Sindh",
                    "geoboundaries_shape_id": r["shape_id"],
                },
                "geometry": {
                    "type": geom["type"],
                    "coordinates": _round_coords(geom["coordinates"]),
                },
            }
        )
    BOUNDARIES_OUT.parent.mkdir(parents=True, exist_ok=True)
    BOUNDARIES_OUT.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "attribution": (
                    "geoBoundaries gbOpen PAK ADM2 (boundary year 2019), www.geoboundaries.org, "
                    "CC BY 4.0; simplified and clipped to Sindh by scripts/build_ledger_demo.py"
                ),
                "features": features,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    meta = {
        "built": as_of,
        "worldpop_file": POP_FILE.name,
        "worldpop_sha256": sha256(POP_FILE),
        "geoboundaries_sha256": sha256(BOUNDARY_FILE),
        "osm_timestamp_base": osm_timestamp,
        "osm_ways": str(n_ways),
        "road_density_p90_km_per_km2": f"{p90:.6f}",
    }
    table = pa.table(
        {
            "district_id": [r["district_id"] for r in rows],
            "name": [r["name"] for r in rows],
            "province": ["Sindh"] * len(rows),
            "population": pa.array([r["population"] for r in rows], type=pa.int64()),
            "road_access": [r["road_access"] for r in rows],
            "alt_delivery_fraction": [r["alt_delivery_fraction"] for r in rows],
            "default_severity": [r["default_severity"] for r in rows],
            "area_km2": [round(r["area_km2"], 1) for r in rows],
            "road_km": [round(r["road_km"], 1) for r in rows],
        }
    ).replace_schema_metadata({k: v for k, v in meta.items()})
    PARQUET_OUT.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, PARQUET_OUT, compression="zstd")
    print(json.dumps(meta, indent=2))
    for r in rows:
        print(
            f"{r['district_id']:34s} pop={r['population']:>9,d} area={r['area_km2']:>8.0f} "
            f"road_km={r['road_km']:>7.0f} access={r['road_access']:.3f}"
        )
    print(f"total population {sum(r['population'] for r in rows):,d}")
    print(
        f"boundaries {BOUNDARIES_OUT.stat().st_size:,d} bytes, parquet {PARQUET_OUT.stat().st_size}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--fetch", action="store_true", help="download the inputs first")
    parser.add_argument("--as-of", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args(argv)
    if args.fetch:
        fetch()
    missing = [p for p in (BOUNDARY_FILE, POP_FILE, ROADS_FILE) if not p.exists()]
    if missing:
        print("missing inputs (run with --fetch):", *map(str, missing), file=sys.stderr)
        return 2
    build(args.as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
