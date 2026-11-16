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
1. WHERE the demo scene is a pre-cached Sentinel scene or a Sen1Floods11 chip, THE Eyes SHALL name it in `source_scene` and set `mode = demo`.
2. THE Eyes SHALL state in its model card and warnings that Sen1Floods11 chips do not cover Sindh 2022, and that Sindh demo inference runs on a separately cached scene (see open question 1).

### EYE-R6 Ops
1. THE Eyes SHALL expose `GET /healthz` including model-loaded status.
2. THE Eyes SHALL return a `Provenance` block with model name, version, hash, and data sources.

### EYE-R7 Eval
1. THE Eyes eval SHALL report IoU, F1, precision, and recall for the flood class on the Sen1Floods11 test split and on any available reference flood map for the demo region (e.g. UNOSAT/Copernicus EMS Sindh 2022 extent), with a baseline (Otsu or NDWI threshold) comparison.

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

## Open questions
1. Sen1Floods11 does not include Sindh 2022. Options: (a) commit a small Sentinel-1 scene of Sindh Aug 2022 (processed from Copernicus/Planetary Computer) and evaluate against a UNOSAT/Copernicus EMS reference extent, (b) demo on Sen1Floods11 Pakistan-adjacent events (it includes a Pakistan 2017 event). Proposal: (a) for the demo, (b) for the quantitative eval.
2. SegFormer-B0 or a small U-Net? Proposal: U-Net with ResNet-18 encoder for CPU speed; SegFormer-B0 as a stretch comparison.
3. Is a GPU available for training? If not, training uses Colab or Kaggle and only the exported ONNX file is committed.
