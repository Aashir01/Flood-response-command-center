"""Fetch the Sen1Floods11 v1.1 hand-labeled Sentinel-1 subset over HTTPS (no gsutil needed).

Downloads only what the Eyes need (design 2, task 1): the four hand-labeled split CSVs and, for
every chip listed in them, ``S1Hand`` (VV, VH sigma0 dB), ``LabelHand`` (-1 no data, 0 not water,
1 water) and ``JRCWaterHand`` (permanent water). About 1.2 GB. Existing files with the right size
are skipped, so the script resumes. Fails if the split counts are not 252 / 89 / 90 / 15.

    python organs/eyes/training/fetch_sen1floods11.py --dest data/raw/sen1floods11

Source: public Google Cloud Storage bucket ``gs://sen1floods11`` (Cloud to Street), license
CC BY 4.0, cite Bonafilia et al. (2020), CVPR Workshops. Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "sen1floods11"
PREFIX = "v1.1"
API = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
MEDIA = f"https://storage.googleapis.com/{BUCKET}/"
SPLITS = {
    "train": "flood_train_data.csv",
    "valid": "flood_valid_data.csv",
    "test": "flood_test_data.csv",
    "bolivia": "flood_bolivia_data.csv",
}
EXPECTED = {"train": 252, "valid": 89, "test": 90, "bolivia": 15}
LAYERS = ("S1Hand", "LabelHand", "JRCWaterHand")


def _get(url: str, retries: int = 4) -> bytes:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data: bytes = r.read()
                return data
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def list_prefix(prefix: str) -> dict[str, int]:
    """Object name -> size for every object under ``prefix``."""
    out: dict[str, int] = {}
    token = ""
    while True:
        q = {"prefix": prefix, "maxResults": "1000", "fields": "items(name,size),nextPageToken"}
        if token:
            q["pageToken"] = token
        page = json.loads(_get(API + "?" + urllib.parse.urlencode(q)))
        for item in page.get("items", []):
            out[item["name"]] = int(item["size"])
        token = page.get("nextPageToken", "")
        if not token:
            return out


def chip_ids(csv_path: Path) -> list[str]:
    ids: list[str] = []
    with csv_path.open(newline="") as f:
        for row in csv.reader(f):
            if row and row[0].strip():
                ids.append(row[0].strip().replace("_S1Hand.tif", ""))
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", type=Path, default=Path("data/raw/sen1floods11"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    dest: Path = args.dest
    split_dir = dest / "splits"
    split_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, list[str]] = {}
    for split, name in SPLITS.items():
        target = split_dir / name
        if not target.exists():
            target.write_bytes(_get(MEDIA + f"{PREFIX}/splits/flood_handlabeled/{name}"))
        counts[split] = chip_ids(target)
    got = {k: len(v) for k, v in counts.items()}
    if got != EXPECTED:
        print(f"split counts differ from the expected {EXPECTED}: {got}", file=sys.stderr)
        return 2
    print(f"split counts OK: {got}")

    wanted = {cid for ids in counts.values() for cid in ids}
    jobs: list[tuple[str, Path, int]] = []
    for layer in LAYERS:
        listing = list_prefix(f"{PREFIX}/data/flood_events/HandLabeled/{layer}/")
        for name, size in listing.items():
            fname = name.rsplit("/", 1)[-1]
            cid = fname.replace(f"_{layer}.tif", "")
            if cid in wanted:
                jobs.append((name, dest / layer / fname, size))
    missing = len(wanted) * len(LAYERS) - len(jobs)
    if missing:
        print(f"{missing} expected objects are missing from the bucket listing", file=sys.stderr)
        return 3

    def fetch(job: tuple[str, Path, int]) -> int:
        name, path, size = job
        if path.exists() and path.stat().st_size == size:
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _get(MEDIA + urllib.parse.quote(name))
        if len(data) != size:
            raise RuntimeError(f"size mismatch for {name}")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return size

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        fetched = sum(pool.map(fetch, jobs))
    total = sum(s for _, _, s in jobs)
    print(
        f"{len(jobs)} files, {total / 1e9:.2f} GB total, {fetched / 1e9:.2f} GB fetched "
        f"in {time.time() - t0:.0f} s -> {dest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
