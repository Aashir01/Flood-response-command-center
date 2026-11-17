"""Build the committed Sindh demo scene for the Eyes (eyes design 6.1, task 14). Network, dev-time.

Source: Microsoft Planetary Computer STAC collection ``sentinel-1-rtc`` (Sentinel-1 IW GRD,
radiometrically terrain-corrected gamma0 by Catalyst, 10 m, UTM; license CC BY 4.0 on the
collection; contains modified Copernicus Sentinel data). Anonymous SAS tokens are used for read.

Steps: list candidates for the window and dates, read VV and VH for a 2,560 x 2,560 px window at
10 m in EPSG:32642 (UTM 42N), convert gamma0 to sigma0 with a flat-ground incidence angle
(``sigma0 = gamma0 * cos(theta)``; theta interpolated across the IW swath from the footprint,
30 deg near range to 46 deg far range, because the collection has no incidence-angle layer),
convert to dB, quantize to uint8 (``stitch_eyes.core.preprocess``), write a COG (DEFLATE,
predictor 2, 512 px tiles), the catalog entry, and a quick-look PNG.

    uv run python scripts/build_eyes_scene.py --list
    uv run python scripts/build_eyes_scene.py --item S1A_IW_GRDH_1SDV_20220827T133609_..._rtc
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "organs" / "eyes" / "src"))

from stitch_eyes.core.preprocess import QUANT_HI, QUANT_LO, quantize_db  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
DEFAULT_ITEM = "S1A_IW_GRDH_1SDV_20220827T133609_20220827T133634_044739_055782_rtc"
# Window centre: Manchar Lake and the flooded plain between the lake and Dadu (Sindh).
DEFAULT_CENTER = (67.70, 26.52)
SIZE = 2560
RES = 10.0
EPSG = 32642
NEAR_DEG, FAR_DEG = 30.0, 46.0
OUT_DIR = ROOT / "data" / "demo" / "eyes"


def _json(url: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def search(center: tuple[float, float], start: str, end: str) -> list[dict[str, Any]]:
    body = {
        "collections": ["sentinel-1-rtc"],
        "intersects": {"type": "Point", "coordinates": list(center)},
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 100,
    }
    feats: list[dict[str, Any]] = _json(f"{STAC}/search", body)["features"]
    return sorted(feats, key=lambda f: f["properties"]["datetime"])


def sign(href: str) -> str:
    p = urllib.parse.urlparse(href)
    account = p.netloc.split(".")[0]
    container = p.path.lstrip("/").split("/")[0]
    token = _json(f"{SAS}/{account}/{container}")["token"]
    return f"{href}?{token}"


def window_bounds(center: tuple[float, float]) -> tuple[float, float, float, float]:
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, EPSG, always_xy=True)
    cx, cy = tr.transform(*center)
    half = SIZE * RES / 2
    x0 = math.floor((cx - half) / RES) * RES
    y1 = math.floor((cy + half) / RES) * RES
    return (x0, y1 - SIZE * RES, x0 + SIZE * RES, y1)


def incidence_deg(item: dict[str, Any], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Flat-ground incidence angle from the across-track position in the footprint.

    The footprint's two long edges are near range and far range. For a right-looking sensor,
    near range is west on an ascending pass and east on a descending pass.
    """
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, EPSG, always_xy=True)
    ring = item["geometry"]["coordinates"][0][:-1]
    pts = np.array([tr.transform(lon, lat) for lon, lat in ring])
    order = np.argsort(pts[:, 0])
    west, east = pts[order[:2]], pts[order[-2:]]

    def dist(line: np.ndarray) -> np.ndarray:
        (x1, y1), (x2, y2) = line
        num = np.abs((y2 - y1) * xs - (x2 - x1) * ys + x2 * y1 - y2 * x1)
        return num / math.hypot(x2 - x1, y2 - y1)

    dw, de = dist(west), dist(east)
    frac_from_west = dw / (dw + de)
    ascending = item["properties"]["sat:orbit_state"] == "ascending"
    frac_near_to_far = frac_from_west if ascending else 1 - frac_from_west
    return NEAR_DEG + (FAR_DEG - NEAR_DEG) * frac_near_to_far


def read_band(href: str, bounds: tuple[float, float, float, float]) -> np.ndarray:
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(sign(href)) as src:
        if src.crs.to_epsg() != EPSG:
            raise SystemExit(f"source CRS {src.crs} is not EPSG:{EPSG}")
        win = from_bounds(*bounds, transform=src.transform)
        arr = src.read(1, window=win, boundless=True, fill_value=src.nodata or 0).astype(np.float64)
        nod = src.nodata
    if arr.shape != (SIZE, SIZE):
        raise SystemExit(f"unexpected window shape {arr.shape} (source grid not aligned)")
    bad = ~np.isfinite(arr) | (arr <= 0)
    if nod is not None:
        bad |= arr == nod
    arr[bad] = np.nan
    return arr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="only list candidate items")
    ap.add_argument("--item", default=DEFAULT_ITEM)
    ap.add_argument("--lon", type=float, default=DEFAULT_CENTER[0])
    ap.add_argument("--lat", type=float, default=DEFAULT_CENTER[1])
    ap.add_argument("--start", default="2022-08-20")
    ap.add_argument("--end", default="2022-09-05")
    ap.add_argument("--region", default="pk-sindh")
    args = ap.parse_args(argv)
    center = (args.lon, args.lat)

    cands = search(center, args.start, args.end)
    for f in cands:
        p = f["properties"]
        print(f"{f['id']}  {p['datetime']}  {p['sat:orbit_state']}  rel={p['sat:relative_orbit']}")
    if args.list:
        return 0
    item = next((f for f in cands if f["id"] == args.item), None)
    if item is None:
        item = _json(f"{STAC}/collections/sentinel-1-rtc/items/{args.item}")

    import rasterio
    from rasterio.transform import from_origin

    bounds = window_bounds(center)
    transform = from_origin(bounds[0], bounds[3], RES, RES)
    cols = bounds[0] + (np.arange(SIZE) + 0.5) * RES
    rows = bounds[3] - (np.arange(SIZE) + 0.5) * RES
    xs, ys = np.meshgrid(cols, rows)
    theta = incidence_deg(item, xs, ys)
    cos_t = np.cos(np.deg2rad(theta))
    bands = []
    for pol in ("vv", "vh"):
        g0 = read_band(item["assets"][pol]["href"], bounds)
        with np.errstate(divide="ignore", invalid="ignore"):
            bands.append(10.0 * np.log10(g0 * cos_t))
    db = np.stack(bands)
    codes = quantize_db(db)
    valid = np.all(codes != 0, axis=0)
    acquired = item["properties"]["datetime"]
    date = acquired[:10]
    scene_id = f"s1-rtc-{args.region}-{date}"
    OUT_DIR.joinpath("scenes").mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "scenes" / f"{scene_id}.tif"
    profile = {
        "driver": "COG",
        "width": SIZE,
        "height": SIZE,
        "count": 2,
        "dtype": "uint8",
        "crs": f"EPSG:{EPSG}",
        "transform": transform,
        "nodata": 0,
        "compress": "DEFLATE",
        "predictor": 2,
        "blocksize": 512,
        "overview_resampling": "nearest",
    }
    tmp = out.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(codes)
        dst.set_band_description(1, "VV sigma0 dB (uint8 quantized)")
        dst.set_band_description(2, "VH sigma0 dB (uint8 quantized)")
        dst.update_tags(
            source_item=item["id"],
            quantization=f"v = 1 + rint((clip(dB,{QUANT_LO},{QUANT_HI})-({QUANT_LO}))/40*254)",
            processing="PC sentinel-1-rtc gamma0 * cos(theta_flat) -> sigma0 dB",
            attribution="Contains modified Copernicus Sentinel data 2022, processed by "
            "Catalyst; hosted by Microsoft Planetary Computer",
        )
    tmp.replace(out)
    sha = hashlib.sha256(out.read_bytes()).hexdigest()

    # Quick-look PNG (VH, 4x decimated) for human review.
    ql = OUT_DIR / "scenes" / f"{scene_id}.quicklook.png"
    small = codes[1, ::4, ::4]
    with rasterio.open(
        ql,
        "w",
        driver="PNG",
        width=small.shape[1],
        height=small.shape[0],
        count=1,
        dtype="uint8",
    ) as dst:
        dst.write(small, 1)

    from pyproj import Transformer

    inv = Transformer.from_crs(EPSG, 4326, always_xy=True)
    lons, lats = inv.transform(
        [bounds[0], bounds[2], bounds[0], bounds[2]], [bounds[1], bounds[1], bounds[3], bounds[3]]
    )
    entry = {
        "region_id": args.region,
        "scene_id": scene_id,
        "date": date,
        "acquired": acquired,
        "sensor": "Sentinel-1A C-SAR IW (VV+VH), RTC gamma0 converted to sigma0",
        "orbit_state": item["properties"]["sat:orbit_state"],
        "relative_orbit": item["properties"]["sat:relative_orbit"],
        "file": f"scenes/{scene_id}.tif",
        "sha256": sha,
        "bytes": out.stat().st_size,
        "crs": f"EPSG:{EPSG}",
        "resolution_m": RES,
        "shape": [SIZE, SIZE],
        "bounds_utm": list(bounds),
        "bbox": [
            round(min(lons), 5),
            round(min(lats), 5),
            round(max(lons), 5),
            round(max(lats), 5),
        ],
        "incidence_deg": [round(float(theta.min()), 2), round(float(theta.max()), 2)],
        "valid_fraction": round(float(valid.mean()), 6),
        "quant": {"lo": QUANT_LO, "hi": QUANT_HI, "nodata": 0, "levels": 254},
        "validated_region": False,
        "source": {
            "provider": "Microsoft Planetary Computer, collection sentinel-1-rtc",
            "item_id": item["id"],
            "stac_url": f"{STAC}/collections/sentinel-1-rtc/items/{item['id']}",
            "processor": "Catalyst (RTC)",
        },
        "license": "CC-BY-4.0 (Planetary Computer sentinel-1-rtc); Copernicus Sentinel data "
        "terms (free, full and open)",
        "attribution": "Contains modified Copernicus Sentinel data 2022, processed by Catalyst; "
        "hosted by Microsoft Planetary Computer",
    }
    cat_path = OUT_DIR / "catalog.json"
    catalog = json.loads(cat_path.read_text()) if cat_path.exists() else {"scenes": []}
    catalog["scenes"] = [s for s in catalog["scenes"] if s["scene_id"] != scene_id] + [entry]
    cat_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(entry, indent=2))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB), quick-look {ql}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
