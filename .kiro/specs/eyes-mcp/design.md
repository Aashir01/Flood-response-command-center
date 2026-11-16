# eyes-mcp: Design

Implements `requirements.md` (EYE-R1..R8, EYE-P1..P7). Contract: `mcp-contracts.md` §3 (v0.3).

## 1. Overview

The Eyes segment surface water in Sentinel-1 SAR imagery with a U-Net (ResNet-18 encoder) fine-tuned on Sen1Floods11, exported to ONNX, and run on CPU. They separate new flood water from permanent water (JRC Global Surface Water), report areas from the pixel grid, aggregate by district, and label honestly that the Sindh demo scene is not a validated result.

All logic is in `core/` as pure functions on NumPy arrays and small dataclasses. The model is behind a `TileModel` protocol (`predict_logits(tile) -> logits`), so tests use deterministic stub models and only a few tests touch ONNX Runtime. The MCP layer is thin.

```
organs/eyes/
  src/stitch_eyes/
    core/
      grid.py         tile grid from (height, width, tile_size): positions, padding, integer weights
      preprocess.py   dequantize scene, nodata fill, shape checks (normalization is inside the ONNX graph)
      blend.py        integer logit accumulation, order-independent; mask and confidence from the accumulators
      infer.py        TileModel protocol, OnnxTileModel (ORT session), ThresholdTileModel (fallback), StubTileModel (tests)
      area.py         per-pixel ground area (UTM scale factor, geographic grids), area sums
      permwater.py    permanent-water mask, new-flood mask, area identities
      vectorize.py    raster to polygons, simplification, validity repair, WGS84 transform, GeoJSON properties
      districts.py    district id raster (partition), per-district areas, fractions
      baseline.py     Otsu and fixed-threshold baselines (eval)
      metrics.py      IoU, F1, precision, recall with ignore index, bootstrap CI
    data/scene.py     committed COG window reader, scene catalog, JRC reference, district boundaries
    store.py          result cache (in-process LRU) + RunStore (run_id -> summary)
    server.py         MCP tools, envelope, error mapping
    http.py           /healthz (model loaded, scene catalog loaded)
    settings.py       env config
  models/             eyes_unet_r18.onnx, export_check.json, model_card.md, preprocess.json
  training/           fetch_sen1floods11.sh, train.py, config.yaml, eyes_train.ipynb, export_onnx.py, quantize_onnx.py, modal_train.py (stretch), README.md
  tests/{unit,property,contract}/   strategies.py holds shared Hypothesis strategies
data/demo/eyes/       scenes/<scene>.tif (COG), catalog.json, jrc_perm_water_pk-sindh.tif, reference_extent_pk-sindh.geojson (optional), MANIFEST.md
data/demo/boundaries/ pk_districts.geojson (shared; see §9)
scripts/build_eyes_scene.py, scripts/build_jrc_perm_water.py, scripts/fetch_reference_extent.py   (network, dev-time only)
evals/eyes/           eval harness, sample chips (committed, small)
```

## 2. Verified external facts

| Topic | Finding | Source |
|---|---|---|
| Sen1Floods11 hosting | Google Cloud Storage bucket `gs://sen1floods11` (v1.1 layout, COG-compliant). The older v1.0 sits in `cnn_chips`. The README text writes the bucket as `senfloods11` in one place; the rsync example uses `sen1floods11`. Total about 14 GB. Public, `gsutil -m rsync -r` works | [repo README](https://github.com/cloudtostreet/Sen1Floods11) |
| Layers | `S1Hand` (Float32, 2 bands VV, VH, dB, GRD IW, 512×512, EPSG:4326, 10 m), `LabelHand` (Int16: −1 no data, 0 not water, 1 water), `S2Hand`, `JRCWaterHand`, `S1OtsuLabelHand` | same |
| Hand-labeled set | 446 chips under `data/flood_events/HandLabeled/` (`LabelHand`, `S1Hand`, `S2Hand`, `JRCWaterHand`, `S1OtsuLabelHand`). Weak labels: 4,385 chips (`S1Weak`, `S1OtsuLabelWeak`, `S2IndexLabelWeak`) | [bucket docs](https://github.com/cloudtostreet/Sen1Floods11/blob/master/docs/README.md) |
| Standard splits | Split CSVs under `splits/flood_handlabeled/`: train, validation, test, and Bolivia (held-out event). From the paper: 252 / 89 / 90 / 15 chips. The task that downloads them checks exact filenames and counts and fails if they differ | paper (CVPR-W 2020), verified by script |
| Size of what we need | Hand-labeled S1 (446 × 512×512×2×4 B ≈ 0.94 GB) + labels + JRC chips ≈ 1.2 GB. Weak-label S1 ≈ 9 GB | computed |
| License | CC BY 4.0 per the owner's brief; the task re-reads the repo LICENSE and records it in `THIRD_PARTY.md`. Citation required (Bonafilia et al. 2020) | brief; to re-check |
| Sindh geography | Sindh spans about 66.7°E to 71.1°E, which lies **entirely inside UTM zone 42N** (66°E to 72°E, EPSG:32642). Zone 43N starts at 72°E (eastern Punjab). The brief's "42N/43N" does not apply to Sindh | geometry |
| UNOSAT 2022 | UNOSAT published flood-extent products for activation `FL20220808PAK`, including a Sindh map of 31 Aug 2022 and weekly evolution reports (PDF maps on unosat.org). The vector layers are normally on HDX | [UNOSAT map](https://unosat.org/static/unosat_filesystem/3349/UNOSAT_A3_Natural_Landscape_FL20220808PAK_Sindh_31Aug2022_v2.pdf) |
| Copernicus EMS | Rapid Mapping activation for Pakistan 2022 (cited as EMSR631 by copernicus.eu); monitoring products also appear under EMSR838 in GDACS links (to be checked). Vector delineations are downloadable per product | [copernicus.eu](https://www.copernicus.eu/en/news/news/observer-shaping-eu-space-diplomacy-copernicus) |
| Context | TU Wien's S1 flood mapping for CEMS Global Flood Monitoring documented the 2022 flood from 10 Aug to 23 Sep, evaluated against CEMS rapid-mapping maps (CSI up to 80%). Useful as a comparator in docs | [NHESS 2023](https://nhess.copernicus.org/articles/23/3305/2023/) |

Not verified in this session (network pages did not render): Planetary Computer `sentinel-1-rtc` coverage of Pakistan in Aug 2022, JRC GSW license text, HDX license of the UNOSAT vectors. The tasks check each and record the result in `MANIFEST.md`.

## 3. Model

### 3.1 Architecture and modality

U-Net with a ResNet-18 encoder from `segmentation_models_pytorch` (MIT license; encoder weights initialised from ImageNet through torchvision). Hand-rolling a U-Net would cost a day for no gain.

| Choice | Decision | Why |
|---|---|---|
| Input modality | **Sentinel-1 only (VV, VH)** | Works through cloud (monsoon floods are cloudy), matches the demo scene, halves download and compute, and Sen1Floods11 has S1 for every hand-labeled chip. S2 would add an optical dependency that fails in the cases that matter. S1+S2 fusion is out of scope. |
| Channels into the network | 3: VV, VH, VV−VH (dB), built **inside the ONNX graph** | Matches the 3-channel ImageNet stem without re-initialising it, and the artifact takes raw dB, so preprocessing cannot drift between training and serving |
| Normalization | clip each band to [−35, +5] dB, then subtract the training mean and divide by the training std per channel; constants come from the train split, stored in `models/preprocess.json` and baked into the graph | determinism, one source of truth |
| Output | 1 channel water logit | binary water (flood plus permanent); permanent water is removed afterwards with JRC |
| Decoder | `decoder_channels=(128, 64, 32, 16, 16)` (lighter than the default 256-wide decoder) | CPU latency |
| Parameters | about 12.5 M (encoder 11.2 M) | see size note in §3.5 |

SegFormer-B0 is a stretch comparison only. The final choice is U-Net/ResNet-18.

### 3.2 Training setup

- Data: Sen1Floods11 hand-labeled train split (252 chips), validation split for model selection (89), **test split (90) used once** for the headline metrics, Bolivia (15) reported separately as an out-of-event check.
- Samples: random 256×256 crops from 512×512 chips, 4 crops per chip per epoch (1,008 samples per epoch), crops with no valid label pixels are skipped.
- Augmentation: flips, 90° rotations, random gain/bias of ±1.5 dB per band (covers the sigma0/gamma0 and processing offsets between Sen1Floods11 and the demo scene), mild Gaussian noise (σ 0.5 dB), and the same uint8 quantization as the demo scene applied to every input (§6.1) so the model sees the committed format.
- Loss: BCE + Dice on valid pixels. Label value −1 is masked out of both terms (ignore index). Class balance by Dice; no loss weighting.
- Optimiser: AdamW, lr 3e-4 for the decoder and head, 1e-4 for the encoder, weight decay 1e-4, cosine schedule with 3 warm-up epochs, batch 16, mixed precision, 60 epochs, seed 0, `torch.use_deterministic_algorithms(True, warn_only=True)`.
- Selection: best validation IoU of the water class; the test split is not touched until the final export.
- Pretrained weights: ImageNet-pretrained ResNet-18 from torchvision. Provenance of ImageNet-trained weights is noted in the model card; if the owner prefers no ImageNet-derived weights, the fallback is random init with 120 epochs (task 3 flags).

### 3.3 Compute plan (no local GPU)

Estimates below assume a T4 with AMP; the first epoch timing in the notebook replaces them.

| Job | What | Where | Duration | Cost | Tier |
|---|---|---|---|---|---|
| A | Fetch hand-labeled subset (~1.2 GB) + fine-tune 60 epochs + export | **Colab free T4** | download 5 to 10 min; training about 10 to 20 min (1,008 samples per epoch, 63 iterations at batch 16, roughly 10 to 15 s per epoch); export 2 min | $0 | core, **start early** |
| A-CPU | same, reduced (128×128 crops, 30 epochs, batch 8) | laptop (i5, 16 GB) | 30 to 60 min | $0 | emergency fallback |
| B | Quantization calibration and the ONNX/PyTorch checks | laptop CPU | 5 to 10 min | $0 | core |
| C | 3 seeds of job A for a mean ± std | Colab free (or Modal T4) | 3 × 20 min | $0 or about $0.60 | stretch |
| D | Weak-label pretraining (S1Weak + Otsu labels, 4,385 chips, 15 epochs) then fine-tune on hand-labeled | **Modal T4/L4**, volume holds the 9 GB | download 20 min + training about 60 to 90 min | about $1 to $2 | stretch |
| E | SegFormer-B0 comparison | Modal T4/L4 | 30 to 45 min | about $0.5 | stretch |

Modal spend plan: C + D + E ≈ $2 to $4 at about $0.6 to $1.1 per GPU-hour (verify current pricing on modal.com/pricing when scheduling). A hard stop is set in `modal_train.py` (`timeout`). Everything is well under the $30 credit.

Checkpoint and resume (Colab sessions disconnect): `train.py` saves `last.pt` (weights, optimizer, scheduler, scaler, RNG states, epoch, best IoU) to a Drive path every 5 epochs and `best.pt` whenever validation IoU improves, keeping two rotating files. `--resume auto` picks up `last.pt`. The notebook's first cell mounts Drive, installs pinned versions, and calls `fetch_sen1floods11.sh` which uses `gsutil -m cp` only for the needed prefixes (skips files that exist). Data goes to Colab local disk, not Drive.

Committed from training: `eyes_unet_r18.onnx`, `export_check.json`, `model_card.md`, `preprocess.json`, `training/config.yaml` with the git commit and seed. Not committed: checkpoints, raw data.

### 3.4 Evaluation protocol

- Sen1Floods11 hand-labeled **test split** (90 chips), pixels with label −1 ignored. Metrics for the water class: IoU, F1, precision, recall, pooled over chips, plus the mean per-chip IoU, with a 95% bootstrap CI over chips (1,000 resamples, seed 0).
- Baselines on the same chips and pixels: Otsu threshold on VH computed **per chip** (what the dataset's Otsu labels do) and a fixed global VH threshold fitted on the train split. NDWI from S2 is a stretch comparison (needs S2).
- Bolivia split reported separately ("held-out event").
- Headline number: test-split water IoU. Sindh output is never merged into it (EYE-R7.2).
- Note: the dataset's label class 1 is *water* (flood plus permanent). The metric is therefore "water-class IoU on flood-event chips", reported under that name (§13, issue 3).

### 3.5 Export, size, latency

- Export: `torch.onnx.export` through a wrapper module (raw dB in, preprocessing inside), opset 17, dynamic axes for H and W (multiples of 32; batch fixed at 1), `do_constant_folding=True`. Graph simplification through `onnxsim` is optional.
- **Size**: 12.5 M parameters × 4 B ≈ 50 MB in fp32, which sits right on the 50 MB limit (EYE-R1.3). Options, decided by measurement in task 5:
  1. **int8 static quantization** (ORT QDQ, per-channel weights, calibrated on 200 training crops): about 13 MB, expected speed-up 1.5 to 2.5× on AVX2/VNNI CPUs. Accept if water IoU on the validation split drops by at most 1.0 point and latency is not worse than fp32.
  2. **fp16 weights** with `convert_float_to_float16(keep_io_types=True)`: about 25 MB; ORT constant-folds the weight casts to fp32 at load (to be confirmed by a latency check).
  3. fp32 only if the file is under 50,000,000 bytes (a decoder trimmed further can get there).
  The shipped model is chosen by this order; the model card states which.
- **Equivalence checks (EYE-P5)**: `export_check.json` holds, for 16 sample tiles from the validation split, the max and mean absolute logit difference between PyTorch and the **shipped** ONNX file, the mask agreement fraction, and the ONNX SHA-256. Tolerances: fp32 max abs difference ≤ 1e-4 on logits; fp16 or int8: mask agreement ≥ 99.5% and IoU difference ≤ 1.0 point (stated in the card). A unit test in the organ reads the JSON and checks the hash matches the committed file; a second test, skipped when `torch` is absent, recomputes the check.
- **Latency budget (EYE-R4.3, 20 s on 2 vCPU)**: demo scene 2,560×2,560 px, tile 256, overlap 32 gives 12×12 = 144 tiles. A 256² tile costs about 3 to 4 GMACs with the light decoder. 144 tiles ≈ 0.5 TMACs, about 8 to 15 s at an effective 40 to 60 GMAC/s on two cores. Margin is thin, so: the ORT session uses `intra_op_num_threads=2`, graph optimizations on, batch 1; the result is cached by `(scene sha, model sha, tile_size, window)`; the server warms the cache for the demo scene at startup (health reports `warm`); and the benchmark gate in task 11 fails the build above 18 s on a 2 vCPU container limit. If it fails: shrink the committed scene (2,048²), use int8, or reduce overlap to `tile/16`.

## 4. Tile inference (EYE-R2, EYE-P1)

### 4.1 Tile grid
For a window of `H×W` pixels and `tile_size = T` (power of two, 64 to 1024), overlap `O = T/8`, stride `S = T − O`:
- `nY = ceil((H − T)/S) + 1` if `H > T` else 1; same for `nX`. Tile `(i, j)` starts at `(iS, jS)` in the **padded** window of size `((nY−1)S + T) × ((nX−1)S + T)`.
- The window is padded to that size with reflect padding (edge handling by padding, EYE-R2.3). Padded pixels never enter the result.
- The grid depends only on `(H, W, T)`, never on processing order.

### 4.2 Order-independent blending
Floating-point addition is not associative, so summing float logits in different orders can flip a pixel near zero. The blend therefore accumulates **integers**.

- Per tile, logits `z` (float32 from the model) are clipped to ±30 and quantized: `q = rint(z · 1024)` as int32 (round half to even, deterministic).
- 1-D weight for tile size T: `w(i) = min(min(i, T−1−i) + 1, O)` for `i` in 0..T−1 (integer ramp of height `O`, never zero). 2-D weight `w(y, x) = w(y)·w(x)` (at most `O² ≤ 2^14`).
- Two int64 arrays per window: `A += w·q` and `W += w`. Integer addition is exactly associative and commutative, so `A` and `W` are **bit-identical for any tile order and any thread schedule**.
- Mask: `water = A > 0` (decided on integers). Probability: `p = sigmoid(A / (W·1024))` computed once from the final integers in float64. Confidence per pixel: `max(p, 1 − p)`.
- The only remaining source of nondeterminism is the tile's own logits. Each tile is a pure function of its pixels and the position-based padding, and inference uses batch size 1, a fixed ORT thread count, and the same session, so identical inputs give identical logits (checked in tests). If ORT output ever varies between runs on a platform, the rounding step to 1/1024 absorbs differences below that level, and the property test reports the case.

### 4.3 Validity and nodata
Pixels with value 0 (reserved nodata) or non-finite values are filled with the median of valid pixels before inference (no cliff at the swath edge) and forced to "not water" afterwards. `valid_fraction` is reported in warnings when below 0.99. A window with no valid pixels returns `NOT_FOUND` ("no valid data").

### 4.4 Masks and the confidence number
- `water_mask` (uint8, values {0, 1}) = `(A > 0) & valid`.
- `perm_mask` from §7. `new_flood_mask = water_mask & ~perm_mask`.
- `confidence` (contract): mean per-pixel `max(p, 1 − p)` over `new_flood_mask` pixels. If there are none, the value is `0.0` and the warning says "no flood pixels, confidence undefined" (proposed change C1 makes it nullable).
- Low-confidence flood pixels: `new_flood_mask` pixels with `p < 0.75` (`low_conf_threshold`, setting).

## 5. Areas (EYE-R2.4, EYE-R3)

- The demo scene is stored in **UTM 42N (EPSG:32642) at 10 m**. The nominal pixel area is 100 m². Ground area is `100 / k²` m², where `k = 0.9996·(1 + (E − 500000)²/(2R²))` is the UTM scale factor at the pixel easting `E` (R = 6,371 km). Across Sindh `k` ranges from 0.9996 to about 1.0005, so using it matters at the 0.1% level. Per-pixel area varies by column only.
- For geographic chips (EPSG:4326, Sen1Floods11), area = `R_a²·Δλ·(sin φ2 − sin φ1)` on the authalic sphere. Used by eval only.
- For scenes outside one UTM zone (live mode, other regions), the loader selects the zone from the window centroid and rejects windows that cross zones (`INVALID_INPUT`), unless area is computed from the equal-area projection EPSG:6933 for the whole window. Sindh needs neither.
- All km² numbers come from **pixel counts** times per-pixel area. Polygons are for display and are checked against the raster areas (§8).
- `area.py` is tested against `pyproj.Geod` polygon areas of random pixel quads (tolerance 0.2%).

## 6. Demo scene and data

### 6.1 The Sindh scene (EYE-R5)

| Item | Decision |
|---|---|
| Product | Sentinel-1 IW, VV+VH, one acquisition, date chosen between 2022-08-20 and 2022-09-05 near the flood peak of about 30 Aug 2022 (the build script lists candidates and the owner picks) |
| Processing | Radiometrically terrain-corrected, then converted to **sigma0 dB**: `sigma0 = gamma0·cos(θ_i)` with θ_i from the product's incidence angle layer (a flat-ground approximation, adequate for the Indus plain). Sen1Floods11's S1 is sigma0 dB from Google Earth Engine GRD; gamma0 would be 1 to 2 dB higher. Training augmentation also covers ±1.5 dB |
| Source options, in order | (a) ASF HyP3 RTC (on-demand RTC, free with an Earthdata login; request `scale=power`, 10 m, include the incidence-angle layer; job takes under an hour); (b) Microsoft Planetary Computer `sentinel-1-rtc` if it covers the area and date; (c) Copernicus Data Space GRD with a simple terrain-flat geocoding via GCPs in rasterio (acceptable on flat terrain, documented as such) |
| Extent | 25.6 km × 25.6 km, 2,560×2,560 pixels, in an area of the Sindh floodplain that is flooded on the chosen date, away from the swath edge |
| Pixel type | uint8 with `0` = nodata; `v = 1 + rint((clip(dB, −35, 5) + 35)/40·254)`, step about 0.16 dB, below speckle noise. Same quantization is applied in training |
| Format | Cloud-Optimized GeoTIFF, 2 bands, DEFLATE with predictor 2, 512 internal tiles. Estimated 7 to 10 MB (budget 25 MB, hard test at 25 MB) |
| License | Contains modified Copernicus Sentinel data 2022, processed by ASF/NASA HyP3 (or the chosen provider); attribution lines in `MANIFEST.md`, `THIRD_PARTY.md`, and the UI |
| Catalog | `catalog.json`: `region_id, scene_id, acquired, sensor, orbit, relative_orbit, file, sha256, crs, bbox, quant{lo,hi,nodata}, source, license` |

`scripts/build_eyes_scene.py` (network, dev-time) searches, downloads, converts, clips, quantizes, writes the COG and catalog entry, and prints size and a quick-look PNG for human review. The scene file and the quick-look checksum are committed.

### 6.2 Permanent water
JRC Global Surface Water (Pekel et al. 2016; the JRC states it is free and open; the exact license text is recorded by the build task). `scripts/build_jrc_perm_water.py` downloads the 10°×10° `occurrence` tiles that cover Sindh (tiles named by their upper-left corner: `60E_30N` and `70E_30N`), mosaics, windows to the scene, reprojects to the scene grid (nearest), thresholds `occurrence ≥ 50` into a uint8 mask, and writes `jrc_perm_water_pk-sindh.tif` (a few hundred KB). At serve time the mask is dilated by `perm_dilate_px = 3` (30 m, the JRC pixel) to absorb the 30 m vs 10 m registration difference. Trade-off: this can hide a flood edge adjacent to a river. Both numbers are settings and appear in the tool's `warnings`.

Sen1Floods11's own `JRCWaterHand` chips are the permanent-water reference in evaluation.

### 6.3 Reference extent overlay (EYE-R5.4, R5.5)
Candidates: UNOSAT satellite-derived flood extent for `FL20220808PAK` (HDX vector layers), Copernicus EMS Rapid Mapping delineation for the Pakistan 2022 activation. Confidence that a clipped extract can be committed: **Copernicus EMS about 75%** (Copernicus data is free and open with attribution "© European Union, Copernicus EMS"; the per-product license text must be read); **UNOSAT about 60%** (UN products on HDX are commonly CC BY-IGO, but this was not verified here). Neither product date matches the S1 acquisition date exactly, so the overlay is qualitative.

Design: `scripts/fetch_reference_extent.py --source {unosat|cems} --url ...` downloads, clips to the scene window, simplifies to about 20 m, and writes `reference_extent_pk-sindh.geojson` with properties `source, product_id, product_date, license, attribution`. It commits nothing automatically. The owner confirms the license in `MANIFEST.md` before the file is committed. If the file is absent, `reference_overlay_geojson = null` and the UI hides the control (EYE-R5.5). The tool returns the key as null, with no other flag.

## 7. Permanent water comparison and districts

**Definitions** (inside the region clip of §7.1; EYE-R3.1 is ambiguous, see §13 issue 4):
- `total_water_km2 = area(water_mask)`
- `permanent_water_km2 = area(water_mask & perm_mask)`: the part of the *detected* water that coincides with JRC permanent water
- `new_flood_km2 = area(water_mask & ~perm_mask) = total_water_km2 − permanent_water_km2` exactly (same pixel areas), and it is never negative.
- `flood_extent_km2` (in `segment_flood`) = `new_flood_km2`; `extent_geojson` shows the same pixels.

### 7.1 Region clip and districts
`data/demo/boundaries/pk_districts.geojson` (properties `district_id, name, province`; simplified to about 100 m) is rasterized onto the scene window grid into an int16 **district id raster** (`-1` outside any district). Overlaps resolve with a fixed rule (smallest `district_id` wins). The union of districts is the region clip. Every statistic is computed on pixels inside the clip, so

`Σ_d flooded_km2(d) = new_flood_km2` **exactly** (a partition of the same pixels with the same per-pixel areas; float rounding only). The tolerance used in tests is 1e-9 relative. `flooded_fraction = flooded_km2 / district_area_in_window_km2`, in [0, 1]. Districts with no pixels in the window are omitted.

A cross-check test compares raster district areas with vector intersection areas in EPSG:6933 (tolerance 1% for districts larger than 10 km²).

## 8. Vectorization (EYE-R2.4, R2.5, EYE-P2)

1. Classes raster: 1 = new flood, high confidence; 2 = new flood, low confidence.
2. `rasterio.features.shapes` per class, 8-connectivity off (4-connected polygons), in the UTM grid.
3. Drop polygons under `min_polygon_km2 = 0.005` (50 pixels) and report the dropped area in a warning. Simplify with `shapely.simplify(15 m, preserve_topology=True)`. Repair invalid results with `make_valid` and keep only polygonal parts.
4. Transform to WGS84, round coordinates to 5 decimals.
5. Feature properties: `class: "new_flood"`, `confidence_class: "high"|"low"`, `area_km2`, `mean_confidence`.
6. Cap at 3,000 features by raising `min_polygon_km2` adaptively; a warning says so.
7. Tolerance: sum of polygon areas within 2% of `flood_extent_km2` when no features were dropped; the dropped area is reported otherwise.

## 9. District boundaries: shared file and ownership

The Ledger spec's dataset (`districts.parquet`) needs per-district zonal sums, so it needs polygons too. Proposal: **one shared file `data/demo/boundaries/pk_districts.geojson`**, produced by `scripts/build_boundaries.py` (source: a CC BY-compatible admin level 2 boundary set such as geoBoundaries ADM2 for Pakistan, license recorded in `MANIFEST.md`), with the **ledger-mcp task 11 owning the file and `district_id` values** (the Ledger is the system of record for district ids). Eyes reads it and never writes it. The same `district_id` strings appear in `districts.parquet` and in Eyes' `by_district`.

Dependency for scheduling: the Eyes district tasks need this file. If the Ledger work has not produced it, Eyes task 9 generates a temporary file with the same schema, and the ids are reconciled before integration. This is a cross-spec dependency to confirm with the owner (§12).

## 10. Algorithms and data flow

`segment_flood(in)`:
1. Validate (§11). Look up the scene by `region_id` and `date` in the catalog. No match: `NOT_FOUND` with the nearest available dates (up to 3) in the message.
2. Window: the scene, or the `bbox` window if given (must intersect; area ≤ `max_area_km2`, default 2,000 for demo).
3. Cache lookup by `(scene sha, model sha, tile_size, window)`. On a miss: preprocess, tile, infer, blend (§4), masks, areas.
4. Permanent water and new flood (§7), vectorization (§8), confidence, reference overlay (or null).
5. Assemble output, with `validation = {validated_for_region: false, eval_dataset: "sen1floods11_test", note}` for any scene whose catalog entry has `validated_region = false` (the Sindh scene), and `source_scene`.
6. Store `(run_id, summary)`. Return the envelope with provenance (`model = {name:"unet-resnet18-s1", version, sha256}`, data sources: Sentinel-1 scene, JRC GSW, Sen1Floods11 as training data, district boundaries; `mode="demo"`).

`compare_with_permanent_water(in)`: steps 1 to 3, then §7 and §7.1; returns totals and `by_district`, sorted by `flooded_km2` descending then `district_id`.

Honest-labelling strings (constants, tested):
- `validation.note`: "Demo scene: Sindh, Aug 2022. The model was fine-tuned and validated on the Sen1Floods11 test split only. Sen1Floods11 has no Sindh 2022 event, so this output is not a validated result for this region."
- `model_card.md` has two separate headed facts: "Demo scene" and "Validated on".

Fallback model: if training does not produce an acceptable model, `ThresholdTileModel` (a documented VH threshold with a small speckle filter) implements `TileModel`. Provenance reports `model.name = "vh-threshold-baseline"`, the `validation.note` says it is a threshold baseline and not the trained network, and the eval table shows it as the headline row.

## 11. Interfaces and errors

| Condition | Result | retryable |
|---|---|---|
| bbox not west < east, south < north, or outside WGS84 bounds | `INVALID_INPUT` | false |
| `tile_size` not a power of two in 64..1024 | `INVALID_INPUT` | false |
| window area above `max_area_km2` | `INVALID_INPUT` | false |
| bbox does not intersect the scene | `NOT_FOUND` | false |
| unknown `region_id` or no scene for the date | `NOT_FOUND` (nearest dates listed) | false |
| model file missing or hash mismatch | `INTERNAL` | false |
| live-mode upstream failure | demo scene plus a warning | n/a |
| any unexpected exception | `INTERNAL` | false |

SAR is unaffected by cloud, so the cloud-cover branch of EYE-R2.7 does not apply to this S1-only design; the tool adds the warning "SAR input: cloud cover does not affect this scene" only in docs. Live mode (optional, stretch) is not designed in detail: any failure falls back to the demo scene with a warning.

Server: MCP Python SDK (`FastMCP`), stdio and streamable HTTP, `GET /healthz` (model loaded, scene catalog loaded, cache warm).

## 12. Decisions needed from the owner

1. **Reference overlay license**: choose CEMS or UNOSAT and confirm the license text, or accept `reference_overlay_geojson = null`.
2. **Scene date and area**: pick from the candidate list printed by the build script (peak flood about 30 Aug 2022).
3. **Boundaries ownership**: ledger-mcp owns `data/demo/boundaries/pk_districts.geojson` and `district_id` (design §9).
4. **ImageNet-initialised encoder** is acceptable, or use random init (more epochs).
5. **Model size rule**: confirm that the shipped ONNX may be int8 or fp16-weights to stay under 50 MB.
6. Colab account and Drive space (about 1 GB for checkpoints) available from Nov 23.

## 13. Correctness properties and how they are tested

Strategies (`tests/strategies.py`): `windows()` (H, W in 1..400 incl. smaller than a tile and non-multiples), `tile_sizes()` (64, 128, 256), `scenes()` (uint8 arrays with random nodata blocks), `water_perm_masks()` (random boolean arrays with matching shapes and random per-column pixel areas), `bboxes()` (valid and invalid), `stub_models()` (deterministic functions of tile content: a local smoothing and threshold of VH, or a hash-seeded pseudo-random logit field keyed by tile content). Profile `ci`: 200 examples, deadline off.

| ID | Property | Test approach |
|---|---|---|
| EYE-P1 | output invariant to tile order | `windows() × tile_sizes() × stub_models()`; compute accumulators for the natural order and for random permutations (and random batching of the same tiles); require `A`, `W`, mask, and confidence **byte-identical**. Real-ONNX variant: demo crop 512², three permutations, byte-identical. **Negative control**: a float32 accumulation of the same tiles in two orders must differ on a crafted case, proving the test can detect the failure it guards against |
| EYE-P2 | mask values in {0, 1}; geometry valid | mask dtype and value set on all outputs; every polygon `is_valid`, non-empty, in WGS84 bounds; no self-intersection after repair |
| EYE-P3 | `0 ≤ new_flood ≤ total_water`, and `new = total − perm` | `water_perm_masks()` with random per-pixel areas; also `Σ_d flooded = new_flood` within 1e-9 on random district rasters |
| EYE-P4 | `flood_extent_km2` invariant to `tile_size` within tolerance | stub model with a bounded receptive field `r ≤ O` (local smoothing): relative difference between T = 64, 128, 256 at most 1%. Real model on the demo crop: at most 3% (stated tolerance, adjusted only with a documented measurement) |
| EYE-P5 | ONNX equals PyTorch within tolerance | `export_check.json` test (hash and tolerances); recompute test skipped without `torch` |
| EYE-P6 | determinism | run each tool twice, and with a different thread count where supported; `data` equal except `run_id` and `generated_at` |
| EYE-P7 | no-water input gives zero flood area | stub that returns strongly negative logits on any input, and the real model on constant land-like backscatter and on all-nodata input: `flood_extent_km2 = 0`, empty FeatureCollection, `confidence = 0.0` with the warning |

Extras:

| ID | Property | Test approach |
|---|---|---|
| EYE-X1 | tile grid covers every pixel and every pixel has total weight > 0 | `windows() × tile_sizes()` |
| EYE-X2 | blending a constant-logit field returns that logit exactly for every pixel | any window and tile size |
| EYE-X3 | per-pixel area: matches `pyproj.Geod` within 0.2%; area of a full window equals the sum of its tiles | random quads and windows |
| EYE-X4 | simplified polygon area within 2% of raster area (no dropped features) | masks with random blobs |
| EYE-X5 | bbox and `tile_size` validation | `bboxes()` valid and invalid classes |
| EYE-X6 | `NOT_FOUND` lists nearest dates in order of distance | catalog fixtures |
| EYE-X7 | dequantization error at most 0.08 dB; nodata preserved | random dB arrays |
| EYE-X8 | partition: every in-region pixel is in exactly one district | random district rasters |
| EYE-X9 | honest-labelling constants: `validated_for_region = false` for the Sindh scene; note text present; reference key is null when the file is absent | contract test |
| EYE-X10 | scene file size under 25 MB; model file under 50,000,000 bytes; model hash in provenance equals the file hash | unit |

Contract tests validate real tool output against the JSON Schemas generated from `stitch_common`. Demo-mode tests run with `no_network`.

## 14. Risks

| Risk | Mitigation |
|---|---|
| R1. Latency over 20 s on 2 vCPU | int8 or fp16 weights, smaller scene (2,048²), cache and startup warm-up, benchmark gate (§3.5) |
| R2. Domain shift from Sen1Floods11 (GEE sigma0, many regions) to the demo scene (RTC, Sindh) gives poor output | sigma0 conversion, gain/bias augmentation, quick-look review by a human, and honest labelling. The qualitative overlap is reported as it is |
| R3. Colab quota or disconnects | resume every 5 epochs, job A is only 10 to 20 min, laptop CPU fallback, Modal as second option |
| R4. int8 loses accuracy | fp16-weights option, then fp32 if under 50,000,000 bytes |
| R5. ORT logits not bitwise stable across runs | batch 1, fixed threads, 1/1024 rounding, property test on the real model |
| R6. HyP3 job slow or Earthdata login blocked | Planetary Computer or CDSE alternative (§6.1); start the build on Nov 23 |
| R7. No redistributable reference | overlay null by design |
| R8. Boundaries file late from the Ledger track | temporary file with the same schema (§9) |
| R9. JRC permanent mask misregistered with the 10 m mask | dilation setting, warning text |
| R10. Weak-label pretraining hurts | it is a stretch and ships only if validation IoU improves |

## 15. Requirement issues found (requirements.md is not edited)

1. **EYE-R1.3 (≤ 50 MB) vs EYE-R1.1/R4.3**: a U-Net/ResNet-18 in fp32 is about 50 MB, at the limit; the design ships int8 or fp16 weights, which affects R1.2's "match within tolerance" (a looser, stated tolerance).
2. **EYE-R2.7** (cloud cover) does not apply to an S1-only model.
3. **EYE-R7.1** says "flood class", but Sen1Floods11 labels class 1 as *water* (including permanent water). The metric is water-class IoU on flood-event chips.
4. **EYE-R3.1** does not define `permanent_water_km2` (reference area in the region vs the part of detected water that is permanent). The design uses the latter, which makes the identity exact.
5. **EYE-P4** has no tolerance; this design proposes 1% (stub) and 3% (real model).
6. **EYE-R3.3** needs a precise "clipped at region boundary" rule; the design uses a district-union clip and an exact pixel partition.
7. The brief's "UTM 42N/43N" does not match Sindh, which is entirely in 42N.
8. **EYE-R2.6** asks for exact date lookup; with one demo scene the tool will usually return `NOT_FOUND` for any other date. The UI should read the available date from the catalog.

## 16. Proposed contract changes (not applied; steering files are not edited)

- **C1** `segment_flood.confidence`: allow `null` when no flood pixels exist (currently forced into [0, 1]).
- **C2** `segment_flood`: add `reference_overlay_note: str | null` (source, product date, license, "qualitative only") so the UI labels the overlay honestly.
- **C3** Document `permanent_water_km2` as the permanent part of detected water (§7) in both tools.
- **C4** `compare_with_permanent_water.by_district`: add `district_area_km2` (area of the district inside the window) so the UI can explain `flooded_fraction`.
- **C5** `segment_flood` output: add `valid_fraction` (share of window pixels with valid data), and `model_variant: "unet-resnet18-s1-int8" | "vh-threshold-baseline"` for honest fallback reporting.
- **C6** New read-only resource `eyes://scenes` listing available `(region_id, date, scene_id)` so callers do not guess dates.
- **C7** Cross-spec: ledger-mcp owns `data/demo/boundaries/pk_districts.geojson` (not a contract change; recorded here for the owner).
