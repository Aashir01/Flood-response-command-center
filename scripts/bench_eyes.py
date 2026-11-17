"""Benchmark full demo-scene inference with the shipped Eyes model (eyes task 16, EYE-R4.3).

    uv run python scripts/bench_eyes.py [--threads 2] [--tile 256] [--repeat 2]

Runs the organ's own pipeline (scene read, preprocess, tiling, ONNX, blending, permanent water,
districts) on the whole committed Sindh scene, cold (new service, empty cache) and warm (second
call, same session, cache bypassed by calling the pipeline directly). Prints JSON with the
seconds per run. The 20 s requirement is for 2 vCPU; the gate in the design is 18 s cold. For a
container limited to 2 vCPU run it inside the Eyes image with ``--cpus 2 --memory 4g``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--tile", type=int, default=256)
    ap.add_argument("--repeat", type=int, default=2)
    args = ap.parse_args(argv)
    os.environ["STITCH_EYES_THREADS"] = str(args.threads)
    os.environ["STITCH_EYES_WARM"] = "0"

    from stitch_eyes.data.scene import full_window
    from stitch_eyes.pipeline import segment
    from stitch_eyes.service import EyesService
    from stitch_eyes.settings import Settings

    t0 = time.perf_counter()
    svc = EyesService(Settings.from_env())
    scene = svc.catalog().scenes[0]
    model = svc.model()
    districts = svc.districts()
    load_s = time.perf_counter() - t0
    runs = []
    for _ in range(args.repeat):
        t = time.perf_counter()
        res = segment(
            scene, full_window(scene), args.tile, model, districts, svc.settings.perm_dilate_px
        )
        runs.append(round(time.perf_counter() - t, 2))
    out = {
        "scene": scene.scene_id,
        "pixels": list(scene.shape),
        "tile": args.tile,
        "threads": args.threads,
        "model_variant": model.variant,
        "model_load_s": round(load_s, 2),
        "runs_s": runs,
        "cold_s": round(load_s + runs[0], 2),
        "tiles": res.tiles_processed,
        "new_flood_km2": round(res.split.new_flood_km2, 3),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
