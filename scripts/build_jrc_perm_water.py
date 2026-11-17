"""Build the permanent-water mask for the Eyes demo scene (eyes design 6.2, task 15). Network.

Source: JRC Global Surface Water v1.4 (1984-2021) ``occurrence`` 10 x 10 degree tile
``60E_30N`` (covers 60-70E, 20-30N; the demo scene lies inside it). v1.4 is used on purpose:
it ends in 2021, so the 2022 flood itself is not counted as "permanent" water (v1.5 includes
2022). License: produced under the Copernicus Programme, free of charge, without restriction of
use; cite Pekel et al. (2016), map attribution "Source: EC JRC/Google".

The tile (30 m, EPSG:4326) is read over HTTP for the scene window only, reprojected onto the
scene grid (10 m, EPSG:32642) with nearest neighbour, and thresholded at ``occurrence >= 50``
into a uint8 {0, 1} mask. Dilation by 3 px happens at serve time (setting), not here.

    uv run python scripts/build_jrc_perm_water.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EYES = ROOT / "data" / "demo" / "eyes"
TILE_URL = (
    "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/"
    "occurrence_60E_30Nv1_4_2021.tif"
)
THRESHOLD = 50


def main() -> int:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    catalog = json.loads((EYES / "catalog.json").read_text(encoding="utf-8"))
    for scene in catalog["scenes"]:
        x0, _y0, _x1, y1 = scene["bounds_utm"]
        h, w = scene["shape"]
        res = scene["resolution_m"]
        dst_transform = from_origin(x0, y1, res, res)
        occ = np.zeros((h, w), dtype=np.uint8)
        with rasterio.open(f"/vsicurl/{TILE_URL}") as src:
            lon0, lat0, lon1, lat1 = scene["bbox"]
            pad = 0.01
            win = src.window(lon0 - pad, lat0 - pad, lon1 + pad, lat1 + pad).round_offsets()
            win = win.round_lengths()
            data = src.read(1, window=win)
            reproject(
                data,
                occ,
                src_transform=src.window_transform(win),
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=scene["crs"],
                resampling=Resampling.nearest,
                src_nodata=255,
                dst_nodata=0,
            )
        mask = ((occ >= THRESHOLD) & (occ <= 100)).astype(np.uint8)
        out = EYES / f"jrc_perm_water_{scene['region_id']}.tif"
        with rasterio.open(
            out,
            "w",
            driver="GTiff",
            width=w,
            height=h,
            count=1,
            dtype="uint8",
            crs=scene["crs"],
            transform=dst_transform,
            compress="DEFLATE",
            tiled=True,
            blockxsize=512,
            blockysize=512,
            nbits=1,
        ) as dst:
            dst.write(mask, 1)
            dst.update_tags(
                source=TILE_URL,
                threshold=f"occurrence >= {THRESHOLD}",
                citation="Pekel et al. (2016) Nature 540, 418-422; Source: EC JRC/Google",
            )
        scene["perm_water"] = {
            "file": out.name,
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "source": "JRC Global Surface Water v1.4 (1984-2021) occurrence, tile 60E_30N",
            "threshold": THRESHOLD,
            "license": "Copernicus Programme, free of charge without restriction of use; "
            "cite Pekel et al. 2016",
        }
        print(f"{out}: {out.stat().st_size} bytes, permanent fraction {mask.mean():.4f}")
    (EYES / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
