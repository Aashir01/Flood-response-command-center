# eyes-mcp: Tasks

Tags: `core` (must ship), `stretch`. `MVP` marks the minimal viable path: train on the hand-labeled train split, export, tile inference, committed scene, both tools, test-split eval. Each task lists requirements and properties satisfied, tests, and "Done when". Commit after each task (`feat(eyes): ...`).

Blocked by the **bootstrap** spec for organ scaffolding (tasks 6 onward). Tasks 1 to 5 and 14 do not depend on bootstrap and start on **Nov 23**, in parallel with Oracle work, so training and the scene download run unattended.

## Schedule (Eyes window: Nov 25 to 27, training starts earlier)

| Day | Plan |
|---|---|
| Nov 23 (parallel with Oracle) | 1, 2, 3 (start job A on Colab and let it run), submit the scene job (task 14, step 1) |
| Nov 24 (parallel) | 4 (export and quantize), 5 (test-split eval and baselines), 14 (finish scene), 15 (JRC mask) |
| Nov 25 | 6 to 9 (scaffold, grid and blend, area, preprocess and scene reader) |
| Nov 26 | 10 to 13 (permanent water and districts, vectorization, ONNX inference, server) |
| Nov 27 | 16 to 20 (perf, evals wired in, overlay decision, docs, THIRD_PARTY), buffer |
| Cut first if late | 25 (live mode), 24 (SegFormer), 23 (weak-label pretraining), 22 (3 seeds), 21 (NDWI baseline), 17 (overlay), then simplification polish in 11. Never cut: 1 to 5, 7, 9, 10, 12, 13 |

- [x] **1. Sen1Floods11 fetch script and dataset loader** `core` `MVP`
  - `training/fetch_sen1floods11.sh`: `gsutil -m cp` only the needed prefixes from `gs://sen1floods11/v1.1/` (`S1Hand`, `LabelHand`, `JRCWaterHand`, and `splits/flood_handlabeled/*.csv`), skip existing files, list the split folder and fail if the four split CSVs (train, validation, test, Bolivia) or their counts (252 / 89 / 90 / 15) differ from the expected, and print dataset size. Record the repo LICENSE text and the bucket URL in `training/README.md`.
  - `training/data.py`: PyTorch `Dataset` with random 256 crops, flips and rotations, ±1.5 dB gain/bias, Gaussian noise, the demo-scene uint8 quantization applied to every input, label −1 masked. A pure function `quantize_db` / `dequantize_db` shared with the organ (copied into `core/preprocess.py` later; a test asserts the two copies agree).
  - Tests (run on CPU in the training env): dataset shapes and dtypes on a tiny synthetic fixture, ignore-index handling, crops never contain only −1, quantization round trip error at most 0.08 dB (EYE-X7).
  - Refs: EYE-R1.1, R1.5. Done when: the script downloads the subset on a clean Colab runtime in under 10 minutes and the split counts match.

- [x] **2. Training script, config, notebook** `core` `MVP`
  - `training/train.py` + `config.yaml`: U-Net/ResNet-18 (`segmentation_models_pytorch`, `decoder_channels=(128,64,32,16,16)`, 3-channel input built in the model wrapper, normalization constants computed from the train split and saved to `preprocess.json`), BCE + Dice with ignore mask, AdamW with two lr groups, cosine with warm-up, AMP, seed 0, deterministic flags. Metrics on validation each epoch (water-class IoU, F1). `--resume auto` with `last.pt` every 5 epochs and `best.pt` on improvement (two rotating files, Drive path from config). `--cpu-smoke` runs 2 epochs on 8 chips.
  - `training/eyes_train.ipynb`: first cell mounts Drive, installs pinned versions, clones the repo at a pinned commit; second cell runs the fetch script; third runs `train.py`. A cell at the end copies artifacts to Drive.
  - `training/modal_train.py` is stubbed only (task 23 fills it in).
  - Tests: one training step on the synthetic fixture lowers loss; loss ignores −1 pixels; resume reproduces the same next-epoch metrics from a saved checkpoint (same seed). Refs: EYE-R1.1, R1.5.
  - Done when: `--cpu-smoke` passes on the laptop and the notebook runs the first two epochs on Colab.

- [x] **3. Run job A: fine-tune on Colab and select the checkpoint** `core` `MVP`
  - Run 60 epochs on a free T4 (expected 10 to 20 min plus download). If Colab denies a GPU, retry later the same day, then use Modal T4 (about $0.20 for this job), then the laptop reduced run (128×128 crops, 30 epochs, batch 8, 30 to 60 min).
  - Record the training log (loss, validation IoU by epoch), the seed, the git commit, package versions, the best epoch, and wall time in `training/runs/jobA.json` (small, committed).
  - Do **not** evaluate the test split here. Refs: EYE-R1.1, R1.5.
  - Done when: `best.pt` exists on Drive and the log shows validation water IoU. If validation IoU is below the threshold baseline from task 5, go to the fallback in task 4b.

- [x] **4. ONNX export, equivalence check, quantization decision** `core` `MVP`
  - `training/export_onnx.py`: wrapper module with preprocessing (clip, channel build, normalize from `preprocess.json`) inside the graph, opset 17, dynamic H and W (multiples of 32), batch 1. `training/quantize_onnx.py`: int8 static QDQ with per-channel weights calibrated on 200 training crops; an fp16-weights variant.
  - Choose the shipped file by the order in design §3.5: int8 if validation IoU drop ≤ 1.0 point and latency not worse than fp32; else fp16 weights; else fp32 if under 50,000,000 bytes. Benchmark all variants at tile 256 on 2 threads and record median latency per tile (gives the budget check for task 16).
  - Write `models/export_check.json`: 16 validation tiles, max and mean absolute logit difference vs PyTorch, mask agreement, IoU difference, SHA-256 of the shipped file, variant name, opset, versions.
  - Commit `models/eyes_unet_r18.onnx`, `export_check.json`, `preprocess.json`. Refs: EYE-R1.2, R1.3, R1.4. P5.
  - Tests: `export_check` hash matches the committed file; tolerances met (fp32: max abs logit diff ≤ 1e-4; fp16/int8: mask agreement ≥ 99.5%, IoU difference ≤ 1.0 point); file size under 50,000,000 bytes (EYE-X10).
  - Done when: the model loads in ORT on the laptop and the check file passes its tests.
  - **4b. Fallback** if training fails or underperforms the baseline: ship `ThresholdTileModel` (documented VH threshold fitted on the train split plus a small speckle filter) as `vh-threshold-baseline`, with the honest labels in design §10. The tools and tests work with either model through `TileModel`. Decide by the end of Nov 24.

- [x] **5. Test-split evaluation and baselines** `core` `MVP`
  - `core/metrics.py` (IoU, F1, precision, recall with ignore index, pooled and per-chip, bootstrap CI), `core/baseline.py` (per-chip Otsu on VH; fixed global VH threshold fitted on the train split).
  - `evals/eyes/`: `--full` loads the hand-labeled **test** (90) and Bolivia (15) chips from `data/raw/` (git-ignored), runs the shipped ONNX through the same tile pipeline used in serving (so the eval tests the artifact, not the PyTorch checkpoint), writes a result file to `evals/results/` in the dashboard schema, with the model SHA and the dataset split names. Eval run is a one-off on the laptop or Colab after the checkpoint is frozen. `--fast` uses 8 committed sample chips from the test split (about 3 MB, int16 dB × 100 plus uint8 labels, CC BY 4.0 attribution) and finishes in seconds.
  - Tests: metric unit tests on hand-computed masks (including ignore pixels), baseline tests on synthetic bimodal data, `--fast` smoke run. Refs: EYE-R7.1. Done when: the result file reports test-split IoU, F1, precision, recall for the model and both baselines, plus the Bolivia row.
  - The Sindh qualitative overlap (EYE-R7.2) is added by task 17 if the reference exists, under its own label "qualitative, single scene".

- [x] **6. Scaffold the organ with `surgeon`** `core` `MVP`
  - Generate `organs/eyes/` (pyproject, `src/stitch_eyes`, `tests/{unit,property,contract}`, `models/`, README). Dependencies: `onnxruntime`, `numpy`, `rasterio`, `shapely`, `pyproj`, `geopandas` (boundaries), `pillow` not needed.
  - Confirm `no_network`, Hypothesis profiles, ruff and mypy. Verify rasterio, shapely, ORT wheels import in the target Docker base image (GDAL wheel on slim images is a known snag).
  - Done when: `uv run pytest` passes on the skeleton and the geo imports pass in the image.

- [x] **7. Tile grid and order-independent blending** `core` `MVP`
  - `core/grid.py`, `core/blend.py`, `core/infer.py` (`TileModel` protocol, `StubTileModel`), per design §4.1 and §4.2 (integer weights, int64 accumulators, sign-based mask, float64 confidence from integers).
  - Property tests: **EYE-P1** (with the float-accumulation negative control), EYE-X1, EYE-X2; unit tests: hand-computed grid for 5×7 windows, edge padding, window smaller than a tile. Refs: EYE-R2.1 to R2.3.
  - Done when: P1 passes under `ci` and the negative control demonstrates a detectable failure.

- [x] **8. Per-pixel area** `core` `MVP`
  - `core/area.py` per design §5 (UTM scale factor by easting; authalic-sphere cells for geographic chips; zone selection and the cross-zone rejection).
  - Tests: EYE-X3 against `pyproj.Geod` (tolerance 0.2%); hand-computed 100 m² case at the central meridian. Refs: EYE-R2.4.
  - Done when: the area tests pass and the Sindh window gives total area within 0.2% of the geodesic area of its footprint.

- [x] **9. Preprocess and scene reader** `core` `MVP`
  - `core/preprocess.py` (dequantize, nodata fill with the median of valid pixels, forced no-water on nodata), `data/scene.py` (catalog, COG window read by bbox, bbox to window mapping, intersection checks, `max_area_km2`).
  - Tests: EYE-X7; window mapping round trip; invalid and non-intersecting bbox cases (EYE-X5); catalog `NOT_FOUND` with nearest dates (EYE-X6). Uses a small synthetic COG fixture. Refs: EYE-R2.1, R2.6, R4.1, R4.2.
  - Done when: a fixture COG reads back the expected window and the `NOT_FOUND` message lists nearest dates.

- [x] **10. Permanent water, districts, aggregation** `core` `MVP`
  - `core/permwater.py` (dilation setting, identities), `core/districts.py` (rasterize the boundaries into the district id raster with the smallest-id rule, partition, per-district areas and fractions, region clip).
  - Uses `data/demo/boundaries/pk_districts.geojson` from ledger-mcp task 11. If it does not exist yet, generate a temporary file with the same schema (about 30 Sindh districts from the same source) marked `TEMP` in its properties, and reconcile ids before integration (design §9).
  - Property tests: **EYE-P3**, EYE-X8; cross-check test of raster vs vector district areas (1%). Refs: EYE-R3.1 to R3.3.
  - Done when: P3 passes and the district sum equals `new_flood_km2` within 1e-9.

- [x] **11. Vectorization and confidence** `core` `MVP`
  - `core/vectorize.py` per design §8 (two confidence classes, `shapes`, minimum polygon area, simplify, `make_valid`, WGS84 transform, 5-decimal rounding, feature cap), confidence number (§4.4).
  - Property tests: **EYE-P2**, EYE-X4; unit tests: empty mask returns an empty FeatureCollection; a single-pixel blob is dropped with a warning. Refs: EYE-R2.4, R2.5.
  - Done when: P2 and X4 pass and the GeoJSON of the demo crop loads in a viewer.

- [x] **12. ONNX tile model and the segmentation pipeline** `core` `MVP`
  - `OnnxTileModel` (session options: 2 intra-op threads, batch 1, graph optimization on; SHA-256 check against the manifest at load, `INTERNAL` on mismatch), the pipeline function tying §10 steps 3 to 5 together (cache keyed by scene sha, model sha, tile size, window).
  - Tests: determinism and tile-order tests with the real model on a 512² crop (P1 real variant, P6); **P7** with the stub and with the real model on constant backscatter and all-nodata input; **P4** with the stub and with the real model (tolerance 3% on the demo crop; record the measured value). Refs: EYE-R2, R4.3. P4, P6, P7.
  - Done when: the real-model tests pass and the measured P4 difference is written to the model card.

- [x] **13. MCP server, envelope, health** `core` `MVP`
  - `server.py`: `segment_flood`, `compare_with_permanent_water`, error mapping (§11), provenance (model name, version, SHA-256, data sources, `mode="demo"`), honest-labelling constants (`validation`), `/healthz`, stdio and HTTP, cache warm-up at startup.
  - Contract tests against the JSON Schemas (`additionalProperties: false`), EYE-X9, EYE-X10. Smoke: start the server, list tools, call both on the demo scene. Refs: EYE-R2.1, R3, R5.2, R5.3, R6. 
  - Done when: the contract hook passes and the smoke test passes.

- [x] **14. Demo scene build and commit** `core` `MVP`
  - `scripts/build_eyes_scene.py`: search candidates for 2022-08-20 to 2022-09-05 (HyP3 RTC job first; Planetary Computer `sentinel-1-rtc` and CDSE GRD as alternatives), print the candidate list for the owner to choose, download, convert gamma0 to sigma0 dB with the incidence angle layer, clip 2,560×2,560 px at 10 m in EPSG:32642, quantize to uint8, write the COG (DEFLATE, predictor 2, 512 tiles), write the `catalog.json` entry, render a quick-look PNG for review.
  - **Submit the processing job on Nov 23** (it can take up to an hour or more) and finish the script while it runs.
  - Commit the COG (under 25 MB, enforced by a test), `catalog.json`, `MANIFEST.md` (source, product id, processing, license, attribution, SHA-256), and `THIRD_PARTY.md` rows (Sentinel-1/Copernicus, ASF HyP3 if used).
  - Refs: EYE-R5.1, R8.1. EYE-X10. Done when: the committed scene loads offline, the quick-look shows plausible water bodies and no swath-edge artifacts, and the owner has approved the date and area.

- [x] **15. Permanent water mask build** `core` `MVP`
  - `scripts/build_jrc_perm_water.py` per design §6.2 (tiles `60E_30N`, `70E_30N`, mosaic, window, reproject, threshold ≥ 50). Record the JRC license text in `MANIFEST.md` and a `THIRD_PARTY.md` row.
  - Test: committed mask has the scene grid, values in {0, 1}, and the Indus main channel is mostly marked. Refs: EYE-R3.1.
  - Done when: the committed file is under 1 MB and the check passes.

- [ ] **16. Performance and offline checks** `core` `MVP`
  - Benchmark the full demo-scene inference in a container limited to 2 vCPU and 4 GB; the gate fails above 18 s cold (20 s requirement) and records warm time. If it fails, apply in order: int8, smaller scene (2,048²), overlap `T/16`. Run the whole suite with sockets disabled. Refs: EYE-R4.3, R8.2.
  - Done when: under budget with margin and the suite passes offline.

- [x] **17. Reference overlay and the qualitative Sindh comparison** `stretch`
  - `scripts/fetch_reference_extent.py` (UNOSAT FL20220808PAK vectors from HDX, or Copernicus EMS rapid-mapping delineation for the Pakistan 2022 activation). The owner confirms the license text in `MANIFEST.md` before committing the clipped extract. If it cannot be redistributed, the overlay stays null and nothing is committed.
  - If present: `reference_overlay_geojson` and `reference_overlay_note` (if contract change C2 is approved), plus an eval row "Sindh scene vs reference, qualitative, single scene" (IoU/overlap) reported separately from the headline number (EYE-R7.2).
  - Tests: EYE-X9 overlay-null case; the overlay present case with a tiny fixture. Refs: EYE-R5.4, R5.5, R7.2.
  - Done when: either the overlay renders and is labeled qualitative, or the tool returns null and the UI hides the control.

- [x] **18. Model card and documentation** `core` `MVP`
  - `models/model_card.md` with two separately headed facts ("Demo scene: Sindh, Aug 2022" and "Validated on: Sen1Floods11 test split"), training data and license, metrics from task 5, quantization variant and check results, tile-size sensitivity measured in task 12, limitations (domain shift, sigma0 conversion, 30 m permanent water, flat-terrain assumption, not validated for Sindh).
  - `organs/eyes/README.md`; `docs/eyes-model.md` (architecture, training, compute, export, tile blending proof sketch of order independence, area method, honest labelling). Add the property-testing story (P1 float vs integer accumulation) to `docs/kiro-writeup.md`.
  - Done when: no document presents Sindh output as validated.

- [x] **19. THIRD_PARTY and manifest check** `core` `MVP`
  - Rows: Sen1Floods11 (CC BY 4.0, citation), `segmentation_models_pytorch` (MIT), PyTorch, torchvision ImageNet weights note, onnxruntime, rasterio, shapely, pyproj, geopandas, JRC GSW, geoBoundaries (or the chosen source), Copernicus Sentinel-1.
  - Done when: no unlisted dependency or dataset remains.

- [x] **20. Contract change entries** `core`
  - If the owner approves the proposed changes C1 to C6 (design §16): update `mcp-contracts.md`, `stitch_common`, server, and consumers in one change. Otherwise: confidence is `0.0` with a warning when no flood, and the fallback model is flagged in `validation.note`.
  - Done when: the contract hook passes.

- [ ] **21. NDWI baseline from Sentinel-2** `stretch`
  - Add `S2Hand` to the fetch and an NDWI threshold baseline row in the eval. Refs: EYE-R7.1.

- [ ] **22. Three seeds for mean ± std** `stretch`
  - Run job A with seeds 0, 1, 2 (Colab or Modal; about $0.60 total on Modal). Report mean and spread on validation and test.

- [ ] **23. Weak-label pretraining** `stretch`
  - `training/modal_train.py`: Modal app with a Volume for the 9 GB `S1Weak` + `S1OtsuLabelWeak` download, T4 or L4, 15 epochs, then fine-tune on hand-labeled. Estimated 1 to 2 hours, about $1 to $2. Ship only if validation IoU improves over job A.

- [ ] **24. SegFormer-B0 comparison** `stretch`
  - Same protocol and splits; report in the eval table only unless it is both smaller and better. About $0.50 on Modal.

- [ ] **25. Live mode** `stretch`
  - Optional source loader. Any upstream failure falls back to the demo scene with a warning (EYE-R8.3). Recorded fixtures only; the live test is `@pytest.mark.live`.

## Traceability

| Requirement | Tasks |
|---|---|
| EYE-R1 | 1, 2, 3, 4, 18 |
| EYE-R2 | 7, 8, 9, 11, 12, 13 |
| EYE-R3 | 10, 15 |
| EYE-R4 | 9, 12, 16 |
| EYE-R5 | 13, 14, 17, 18 |
| EYE-R6 | 4, 13 |
| EYE-R7 | 5, 17, 21 |
| EYE-R8 | 14, 16, 25 |

| Property | Task | Property | Task |
|---|---|---|---|
| EYE-P1 | 7 (stub), 12 (real) | EYE-P5 | 4 |
| EYE-P2 | 11 | EYE-P6 | 12 |
| EYE-P3 | 10 | EYE-P7 | 12 |
| EYE-P4 | 12 | EYE-X1, X2 | 7 |
| EYE-X3 | 8 | EYE-X4 | 11 |
| EYE-X5, X6 | 9 | EYE-X7 | 1, 9 |
| EYE-X8 | 10 | EYE-X9 | 13, 17 |
| EYE-X10 | 4, 13, 14 | | |

## Status (final audit)

Ticked: 1 to 15, 17 to 20. Code and tests are in `organs/eyes/src`, `organs/eyes/tests` (EYE-P1 to P7 and X1 to X10 all have tests) and `organs/eyes/training`. Differences from the plan:
- 1 to 3: the fetch script is `training/fetch_sen1floods11.py`, and training ran on a Vultr VPS on CPU (profile `vultr`, log `training/runs/vultr.json`), not on Colab, so there is no notebook. Best validation IoU 0.692 at epoch 41.
- 4: the shipped file is int8 ONNX (12.7 MB), checked in `models/export_check.json`.
- 5: Sen1Floods11 hand-labeled test IoU 0.674 and F1 0.805, against the global VH threshold (0.533) and Otsu (0.229) (`models/MODEL_CARD.md`).
- 17: the UNOSAT reference extent is committed as a qualitative overlay (CC BY-SA).

Open:
- 16 (performance gate): `scripts/bench_eyes.py` exists, but the cold and warm times in a 2 vCPU / 4 GB container were not recorded.
- 21 to 24 (`stretch`): NDWI baseline, three seeds, weak-label pretraining and SegFormer were not done.
- 25 (live mode, `stretch`): a `live` request falls back to the demo scene with `MODE_FALLBACK`; there is no live scene source.
