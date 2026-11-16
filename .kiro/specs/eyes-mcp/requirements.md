# eyes-mcp: Requirements

Organ: computer-vision flood segmentation. Prefix `EYE`. Contract: `mcp-contracts.md` §3.

## Introduction
The Eyes segment flood water in satellite imagery with a U-Net or SegFormer-style model, fine-tuned in PyTorch on Sen1Floods11 and exported to ONNX for CPU inference. They separate new flooding from permanent water.

## Glossary
- **Scene**: a satellite image (Sentinel-1 SAR and/or Sentinel-2 optical) covering the region and date.
- **Tile**: a fixed-size window of a scene processed independently.
- **Permanent water**: reference water mask (e.g. JRC Global Surface Water or Sen1Floods11 permanent-water labels).

## Requirements

### EYE-R1 Model training
1. THE Eyes SHALL provide a reproducible PyTorch training script that fine-tunes a segmentation model on Sen1Floods11 with a fixed seed and the standard hand-labeled train/val/test splits (exact splits stated in design).
2. THE Eyes SHALL export the trained model to ONNX and verify that ONNX Runtime outputs match PyTorch within a stated tolerance on sample tiles.
3. THE Eyes SHALL commit a demo ONNX model of at most 50 MB with a model card (data, metrics, limitations).
4. THE Eyes SHALL record the model SHA-256 in every result's provenance.
5. THE training SHALL run on free Colab or on Modal (no local GPU is assumed). Notebooks, configs, pinned versions, seeds, and dataset download scripts SHALL be committed in `organs/eyes/training/` so the fine-tune is reproducible. Only the exported ONNX file, the model card, and small sample tiles are committed; checkpoints and raw datasets are not.

### EYE-R2 Inference
1. WHEN `segment_flood` is called, THE Eyes SHALL load the scene for `region_id` and `date` from the demo dataset (demo mode) or from a configured source (live mode), tile it, run ONNX inference on CPU, and stitch tiles into a full-extent mask.
2. THE Eyes SHALL produce the same mask regardless of the order in which tiles are processed.
3. THE Eyes SHALL handle edge tiles by padding, and overlapping tiles by a deterministic blending rule defined in design.
4. THE Eyes SHALL return `flood_extent_km2` computed from the mask and the pixel ground resolution, and `extent_geojson` as simplified polygons in WGS84.
5. THE Eyes SHALL return a `confidence` in [0,1] and mark pixels with low confidence in the GeoJSON properties.
6. IF no scene exists for the requested region and date, THEN THE Eyes SHALL return `NOT_FOUND` listing the nearest available dates.
7. IF a scene is mostly cloud-covered (optical only), THEN THE Eyes SHALL warn and, where SAR is available, rely on SAR.

### EYE-R3 Permanent water comparison
1. WHEN `compare_with_permanent_water` is called, THE Eyes SHALL return total water, permanent water, and new flood area, where `new_flood_km2 = total_water_km2 - permanent_water_km2` and is never negative.
2. THE Eyes SHALL aggregate flooded area by district using committed district boundaries.
3. THE sum of district `flooded_km2` SHALL equal `new_flood_km2` within a stated tolerance (area clipped at region boundary).

### EYE-R4 Input validation and limits
1. THE Eyes SHALL validate `bbox` (west < east, south < north, within WGS84 bounds) and `tile_size` (power of two between 64 and 1024).
2. IF the requested area exceeds a configured maximum, THEN THE Eyes SHALL return `INVALID_INPUT`.
3. THE Eyes SHALL complete a demo-region inference in under 20 s on 2 vCPU.

### EYE-R5 Honesty about the demo
1. THE Eyes SHALL ship one small committed Sentinel-1 scene of Sindh (Aug 2022), clipped and compressed (target under 25 MB, fixed in design), name it in `source_scene`, and set `mode = demo`.
2. THE Eyes SHALL return a `validation` object with `validated_for_region = false` for the Sindh scene and `eval_dataset = "sen1floods11_test"`, because the model is fine-tuned and evaluated on Sen1Floods11, which does not cover Sindh 2022.
3. THE model card, tool warnings, and UI SHALL label the two facts separately: "demo scene: Sindh, Aug 2022" and "model validated on the Sen1Floods11 test split". Sindh output SHALL NOT be presented as a validated result.
4. WHERE a labeled Sindh 2022 reference extent (UNOSAT or Copernicus EMS) is available and redistributable, THE Eyes SHALL return it as `reference_overlay_geojson` for qualitative visual comparison with the prediction.
5. IF no redistributable reference exists, THEN `reference_overlay_geojson` SHALL be null and the UI SHALL hide the overlay control.

### EYE-R6 Ops
1. THE Eyes SHALL expose `GET /healthz` including model-loaded status.
2. THE Eyes SHALL return a `Provenance` block with model name, version, hash, and data sources.

### EYE-R7 Eval
1. THE Eyes eval SHALL report IoU, F1, precision, and recall for the flood class on the Sen1Floods11 hand-labeled test split, with a baseline (Otsu or NDWI threshold) comparison. This is the only headline quantitative result.
2. WHERE a Sindh 2022 reference exists, THE eval SHALL report a separate single-scene overlap figure labeled "qualitative, single scene" and SHALL NOT merge it into the headline number.

### EYE-R8 Demo-first
1. THE Eyes SHALL run every tool from committed demo data with no network calls.
2. THE test suite SHALL enforce this by running demo-mode tests with network sockets disabled.
3. WHERE live mode exists, it is optional, and any upstream failure SHALL fall back to the demo scene with a warning.

## Correctness properties (formalized in design)
- EYE-P1: segmentation output is invariant to tile processing order.
- EYE-P2: mask values are in {0,1} and the extent geometry is valid (no self-intersection).
- EYE-P3: `new_flood_km2 >= 0` and `new_flood_km2 <= total_water_km2`.
- EYE-P4: `flood_extent_km2` is invariant to `tile_size` within a stated tolerance (boundary effects only).
- EYE-P5: ONNX output equals PyTorch output within tolerance (export check).
- EYE-P6: the same input yields the same output (determinism).
- EYE-P7: an all-zero (no-water) input yields zero flood area.

## Out of scope
Live satellite scene acquisition at scale. Cloud removal. Change detection across time series. Training from scratch.

## Decisions (resolved)
1. Demo scene: one committed Sentinel-1 scene of Sindh, Aug 2022. Quantitative eval: Sen1Floods11 test split only. Qualitative overlay against UNOSAT or Copernicus EMS if redistributable.
2. Compute: no local GPU (i5, 16 GB RAM). Train on Colab free; use Modal ($30 credit) for longer jobs. Commit only the exported ONNX model.
3. Architecture: U-Net with ResNet-18 encoder for CPU speed. SegFormer-B0 is a stretch comparison. Final choice is made in design.