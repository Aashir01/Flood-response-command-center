# Model card: eyes_unet_r18.onnx

| Field | Value |
|---|---|
| Model | U-Net with a ResNet-18 encoder (segmentation_models_pytorch), ImageNet-initialised encoder |
| Variant shipped | `unet-resnet18-s1-int8` (ONNX, 12.7 MB), chosen by `training/export_onnx.py` |
| Input | Sentinel-1 sigma0 dB, channels VV, VH, VV-VH; clip [-35, 5] dB; normalised with train-split mean and std (`preprocess.json`) |
| Output | per-pixel water probability; blended over tiles with integer logit accumulation (exact tile-order invariance, EYE-P1) |
| Training data | Sen1Floods11 hand-labeled S1 chips: 252 train, 89 validation (test split held out) |
| Training run | profile `vultr` (256 px crops, 4 per chip, batch 16, up to 60 epochs, 3 warm-up), seed 0, 2 CPU threads on a Vultr VPS (2 vCPU, 16 GB), no GPU. Stopped by the 230-minute budget after epoch 57; best validation IoU 0.692 at epoch 41, which is the exported checkpoint. Log: `training/runs/vultr.json` |
| Export check | int8 vs PyTorch mask agreement 99.71% on validation tiles (threshold 99.5%); see `export_check.json` |

## Results on the Sen1Floods11 hand-labeled test split (89 scored chips)

| Method | IoU | F1 | Precision | Recall |
|---|---|---|---|---|
| **This model** | **0.674** (95% CI 0.556 to 0.769) | **0.805** | 0.852 | 0.763 |
| Global VH threshold (-23.6 dB) | 0.533 | 0.695 | 0.746 | 0.651 |
| Otsu per chip | 0.229 | 0.373 | 0.247 | 0.756 |

Pooled pixel IoU. Mean per-chip IoU is 0.413, lower because many test chips contain little water. Reproduce with `STITCH_SEN1FLOODS11_DIR=<data> python -m evals.run --organ eyes --seed 0`.

## What this is not

- **Not validated on Sindh.** The Sindh 2022 scene in the demo is not in Sen1Floods11. Outputs on it carry `validated_for_region: false` and are labelled unvalidated in the briefing and the UI.
- Sen1Floods11 labels mark water, not flood. New flood water is derived by subtracting the JRC permanent-water layer.
- Label 1 in Sen1Floods11 is water. Its license is not stated in the repository (the STAC catalog says "proprietary"); see `THIRD_PARTY.md` and `docs/decisions.md`.

## Known limits (measured)

- **Tile size matters.** On a 512 x 512 window of the Sindh scene, new-flood area is 5.8, 7.3 and 8.3 km2 at tile sizes 128, 256 and 512 (30% spread). Small tiles remove context the network uses. The organ uses 256 px tiles; EYE-P4 is checked with a 35% bound.
- **Flat dark fields.** A constant field at VV -11 dB, VH -17 dB (dark land, close to water backscatter) is marked about 10% water. Brighter dry-land values (VV -8 / VH -15, VV -5 / VH -12) give zero water.
- Trained on 256 px crops of 512 px chips from 11 countries; performance elsewhere is unknown.

## Reproduce

See `organs/eyes/training/README.md`: `fetch_sen1floods11.py`, `train.py --profile vultr`, `export_onnx.py --ckpt best.pt`. Training runs on CPU; the full profile takes about 3.75 hours on 2 threads. A Colab notebook path is documented there for GPU users.
