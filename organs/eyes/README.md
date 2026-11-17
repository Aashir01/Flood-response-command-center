# eyes-mcp

The Eyes organ of Stitch: surface water in Sentinel-1 SAR (VV+VH) from a U-Net with a ResNet-18 encoder, run on CPU with ONNX Runtime. It separates new flood water from permanent water (JRC Global Surface Water), reports areas from the pixel grid, aggregates them by district and returns simplified polygons in WGS84.

Two facts are kept apart everywhere (EYE-R5.3):
- **Demo scene:** Sindh, 27 Aug 2022 (one committed Sentinel-1 RTC scene, 25.6 km x 25.6 km around Manchar Lake, 67.57 to 67.83 E, 26.40 to 26.64 N).
- **Validated on:** the Sen1Floods11 hand-labeled test split only. Sen1Floods11 has no Sindh 2022 chip, so the Sindh output is not a validated result. Every result says so in `validation` and in a `DEMO:` warning.

Spec: `.kiro/specs/eyes-mcp/`. Contract: `.kiro/steering/mcp-contracts.md` section 3. Model card with metrics: `models/model_card.md`.

## Tools and resource

| Name | What it returns |
|---|---|
| `segment_flood` | `flood_extent_km2` (new flood), `extent_geojson` (polygons, high/low confidence classes), `permanent_water_km2`, `confidence` (null when no flood pixels), `valid_fraction`, `model_variant`, `source_scene`, `validation`, and the UNOSAT reference overlay with its note |
| `compare_with_permanent_water` | total, permanent and new-flood km2 and `by_district` (flooded km2, fraction, district area in the window, flooded road km) |
| `eyes://scenes` | the committed scenes (`region_id`, `date`, `scene_id`, sensor, validated flag) |

Errors follow design section 11: bad bbox or `tile_size` is `INVALID_INPUT`; no scene for the date is `NOT_FOUND` with the nearest dates; a model hash mismatch is `INTERNAL`. Live mode falls back to the demo scene with a warning.

## How a call works

1. Look up the scene in `data/demo/eyes/catalog.json`, map the bbox to a pixel window.
2. Dequantize the uint8 codes to dB, fill nodata with the valid median (`core/preprocess.py`).
3. Tile with overlap `T/8`, run each tile through ONNX, and blend logits as **integers** (`core/grid.py`, `core/blend.py`). Integer sums are associative, so the mask is bit-identical for any tile order (EYE-P1); a float-accumulation negative control proves the test can fail.
4. Water minus dilated JRC permanent water gives new flood (`core/permwater.py`); areas use the UTM scale factor per column (`core/area.py`); districts are an exact pixel partition (`core/districts.py`).
5. Vectorize, simplify by 15 m, repair, transform to WGS84 (`core/vectorize.py`).

Results are cached by (scene SHA, model SHA, tile size, window), and the server warms the full demo scene at start (`STITCH_EYES_WARM=1`).

## Model

`models/eyes_unet_r18.onnx` with `export_check.json` (SHA-256, variant, PyTorch vs ONNX check), `preprocess.json` (normalization constants from the 252-chip train split) and `model_card.md`. Training code and the run log are in `training/` (see `training/README.md`). `STITCH_EYES_MODEL=threshold` switches to the documented VH-threshold fallback, which reports `model_variant = vh-threshold-baseline`.

## Run

```
uv run python -m stitch_eyes.server --stdio                       # stdio (Kiro, Brain)
uv run python -m stitch_eyes.server --http --port 8000            # streamable HTTP, GET /healthz
uv run pytest organs/eyes -q                                      # sockets blocked
uv run python -m evals.run --organ eyes --seed 0 --fast           # 8 committed test chips
STITCH_SEN1FLOODS11_DIR=data/raw/sen1floods11 uv run python -m evals.run --organ eyes --seed 0
uv run python scripts/bench_eyes.py --threads 2                   # full-scene latency
uv run python scripts/mcp_probe.py eyes-mcp --timeout 180
```

| Variable | Default | Meaning |
|---|---|---|
| `STITCH_DEMO_DIR` | `data/demo` | dataset root |
| `STITCH_EYES_MODEL_DIR` | `organs/eyes/models` | model directory |
| `STITCH_EYES_MODEL` | `auto` | `auto` (ONNX) or `threshold` |
| `STITCH_EYES_THREADS` | `2` | ONNX Runtime intra-op threads |
| `STITCH_EYES_DATE_TOLERANCE_DAYS` | `3` | nearest scene accepted within this many days |
| `STITCH_EYES_MAX_AREA_KM2` | `2000` | largest window |
| `STITCH_EYES_WARM` | `1` | warm the demo-scene cache at start |

## Data and licenses

Scene: contains modified Copernicus Sentinel data 2022, RTC by Catalyst via Microsoft Planetary Computer (CC BY 4.0). Permanent water: JRC Global Surface Water v1.4 (Pekel et al. 2016). Reference overlay: UNOSAT FL20220808PAK VIIRS water extent via HDX, **CC BY-SA**, qualitative only (cumulative July to August 2022 at about 375 m, not the scene date). Training data: Sen1Floods11 (Bonafilia et al. 2020). Details: `data/demo/MANIFEST.md` and `THIRD_PARTY.md`.

Stitch is a decision-support demo, not an operational flood warning system.
