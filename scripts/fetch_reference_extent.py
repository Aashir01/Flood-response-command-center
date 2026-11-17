"""Fetch and clip the UNOSAT reference flood extent for the Sindh demo scene (eyes task 17).

    uv run --with pyogrio python scripts/fetch_reference_extent.py

Source: UNOSAT, activation FL20220808PAK, "Satellite detected water extents between 01 and 29
August 2022 over Pakistan" on HDX (dataset
``satellite-detected-water-extents-between-01-and-29-august-2022-over-pakistan``, resource
``VIIRS_20220701_20220831_FloodExtent_PAK.zip``). Cumulative VIIRS water (about 375 m pixels),
1 July to 31 August 2022. HDX licence: Creative Commons Attribution-ShareAlike (CC BY-SA),
read from the HDX ``package_show`` API (``license_id: cc-by-sa``). The clipped and simplified
extract is an adaptation and is therefore shared under the same licence, with attribution; the
file states this in its top-level ``properties``.

Steps: download the zip to ``data/raw/reference/`` (skipped if present), read the shapefile,
reproject to WGS84, clip to the demo scene bbox from ``data/demo/eyes/catalog.json``, keep the
flood-water classes, dissolve, simplify by 20 m in UTM 42N, repair validity, round to 5
decimals, and write ``data/demo/eyes/reference_extent_pk-sindh.geojson``. Network, dev-time
only; the organ never runs this.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
URL = (
    "https://data.humdata.org/dataset/f685e623-a539-4af0-92ff-19b737ec95b3/resource/"
    "fa89ec39-8dd0-4abe-b97e-0a3d9e9627a5/download/viirs_20220701_20220831_floodextent_pak.zip"
)
HDX_PAGE = (
    "https://data.humdata.org/dataset/"
    "satellite-detected-water-extents-between-01-and-29-august-2022-over-pakistan"
)
RAW = REPO / "data" / "raw" / "reference"
EYES = REPO / "data" / "demo" / "eyes"
SIMPLIFY_M = 20.0


def _round(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, 5)
    if isinstance(obj, list | tuple):
        return [_round(v) for v in obj]
    return obj


def _transform(t: Any, g: Any) -> Any:
    import numpy as np
    import shapely  # type: ignore[import-untyped]

    def f(xy: Any) -> Any:
        x, y = t.transform(xy[:, 0], xy[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(g, f)


def main(argv: list[str] | None = None) -> int:
    import pyogrio  # type: ignore[import-not-found]
    import shapely
    from pyproj import CRS, Transformer

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="pk-sindh")
    args = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    z = RAW / "viirs_20220701_20220831_floodextent_pak.zip"
    if not z.exists():
        urllib.request.urlretrieve(URL, z)
    out_dir = RAW / "viirs_pak"
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out_dir)
    shp = next(out_dir.rglob("*.shp"))
    meta, _fids, wkb, fields = pyogrio.raw.read(shp)
    names = list(meta["fields"])
    src_crs = CRS.from_user_input(meta["crs"])
    print(f"{shp.name}: {len(wkb)} features, crs {src_crs.to_epsg()}, fields {names}")

    cat = json.loads((EYES / "catalog.json").read_text(encoding="utf-8"))
    scene = next(s for s in cat["scenes"] if s["region_id"] == args.region)
    w, s, e, n = scene["bbox"]
    to_wgs = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    geoms = shapely.from_wkb(wkb)
    classes = fields[names.index("water_clas")] if "water_clas" in names else None
    dates = fields[names.index("sensor_dat")] if "sensor_dat" in names else None
    keep = []
    for i, g in enumerate(geoms):
        if g is None or g.is_empty:
            continue
        g = _transform(to_wgs, g) if src_crs.to_epsg() != 4326 else g
        c = shapely.clip_by_rect(g, w, s, e, n)
        if not c.is_empty:
            keep.append(c)
            if classes is not None:
                print("kept class", classes[i], "date", None if dates is None else dates[i])
    if not keep:
        print("no reference water inside the scene bbox; nothing written")
        return 1
    merged = shapely.union_all(keep)
    utm = Transformer.from_crs("EPSG:4326", scene["crs"], always_xy=True)
    back = Transformer.from_crs(scene["crs"], "EPSG:4326", always_xy=True)
    m_utm = _transform(utm, merged)
    area_km2 = m_utm.area / 1e6
    simp = shapely.make_valid(m_utm.simplify(SIMPLIFY_M, preserve_topology=True))
    polys = [
        p for p in getattr(simp, "geoms", [simp]) if p.geom_type in ("Polygon", "MultiPolygon")
    ]
    out_geom = _transform(back, shapely.union_all(polys))
    gj = shapely.geometry.mapping(out_geom)
    gj = {"type": gj["type"], "coordinates": _round(gj["coordinates"])}
    props = {
        "source": "UNOSAT (UNITAR), activation FL20220808PAK",
        "product_id": "VIIRS_20220701_20220831_FloodExtent_PAK",
        "product_date": "2022-08-31",
        "sensor": "VIIRS (NOAA-20, Suomi NPP), cumulative water 2022-07-01 to 2022-08-31",
        "license": "CC BY-SA (HDX dataset licence); this clipped, dissolved and simplified "
        "extract is shared under the same licence",
        "attribution": "Satellite detected water extents, UNOSAT/UNITAR, via HDX "
        "(FL20220808PAK). Modified: clipped to the demo scene, dissolved, simplified by 20 m.",
        "url": HDX_PAGE,
        "note": "Qualitative only. Cumulative VIIRS water at about 375 m, not the scene date "
        "or resolution; includes permanent water. Preliminary UNOSAT analysis, not "
        "validated in the field.",
        "area_km2_in_bbox": round(area_km2, 3),
    }
    fc = {
        "type": "FeatureCollection",
        "properties": props,
        "features": [
            {
                "type": "Feature",
                "properties": {"class": "reference_water", "source": "unosat_viirs"},
                "geometry": gj,
            }
        ],
    }
    dest = EYES / f"reference_extent_{args.region}.geojson"
    dest.write_bytes((json.dumps(fc, separators=(",", ":")) + "\n").encode("utf-8"))
    print(f"wrote {dest} ({dest.stat().st_size} bytes), reference water {area_km2:.1f} km2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
