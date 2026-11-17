# Eyes model: how it was built and what it can claim

Companion to `organs/eyes/models/model_card.md` (numbers) and `.kiro/specs/eyes-mcp/design.md` (decisions). This page explains the method.

## Two separate facts

- **Demo scene:** Sindh, 27 Aug 2022, one Sentinel-1A RTC scene around Manchar Lake. It is shown in the demo.
- **Validated on:** Sen1Floods11 hand-labeled test split (90 chips, 11 flood events worldwide, none in Pakistan). The headline numbers come only from there.

The Sindh output is never described as validated. The only Sindh comparison is a qualitative overlay of the UNOSAT VIIRS water extent, which differs in date (cumulative July to August), resolution (about 375 m vs 10 m) and content (it includes permanent water).

## Architecture

U-Net with a ResNet-18 encoder (`segmentation_models_pytorch`, ImageNet initialisation, decoder channels 128, 64, 32, 16, 16), about 12.5 M parameters. Input: Sentinel-1 sigma0 VV and VH in dB. The ONNX graph does the preprocessing itself: clip to [-35, 5] dB, build three channels (VV, VH, VV-VH) and normalize with the train-split mean and standard deviation from `preprocess.json`. Output: one water logit per pixel. Class 1 in Sen1Floods11 is water (flood and permanent), so the model detects all water and permanent water is removed afterwards.

## Training

Design section 3.2, run as profile `vultr` (`organs/eyes/training/config.yaml`): random 256 x 256 crops, 4 per chip per epoch from the 252 train chips; flips, 90-degree rotations, a per-band offset of up to 1.5 dB, Gaussian noise of 0.5 dB and the demo scene's uint8 quantization on every input. Loss: BCE plus soft Dice on pixels whose label is not -1. AdamW (encoder 1e-4, decoder 3e-4, weight decay 1e-4), 3 warm-up epochs then cosine, batch 16, seed 0. Model selection: best validation water IoU (89 chips). The test split was read once, by the eval, after the export.

Compute: CPU only, 2 threads of the Vultr VPS (2 vCPU, shared with the production stack) at `nice 10`. The model card has the wall time and epoch count.

## Export and precision

`export_onnx.py` writes fp32, fp16-weights and three int8 variants (static QDQ, per-channel weights, MinMax calibration on 200 train crops: all layers; stem and head in float; decoder in float). Each is checked against PyTorch on 16 validation tiles (EYE-P5: mask agreement at least 99.5% and validation IoU within 1 point; fp32 must match logits within 1e-4). The design's order is int8, then fp16, then fp32 if under 50 MB. On both the laptop and the VPS checkpoints the int8 variants agreed with PyTorch on 99.4% of pixels, just under the tolerance, so the shipped file is fp16 weights (25 MB). The contract label `unet-resnet18-s1-fp16` was added in contract v0.6.

## Tiling and order independence (EYE-P1)

The window is cut into tiles of size `T` with overlap `O = T/8` and reflect padding at the edge. Each tile's logits are clipped to +-30 and rounded to integers in units of 1/1024. Each tile pixel gets an integer weight `w(y)w(x)` with `w(i) = min(min(i, T-1-i)+1, O)`. Two int64 arrays accumulate `A += w q` and `W += w`.

Proof sketch: integer addition is associative and commutative and does not overflow (at most 4 tiles overlap a pixel, `|w q| <= O^2 * 30 * 1024 < 2^31`). So `A` and `W` are the same for every order and batching of the tiles, and the mask `A > 0` and probability `sigmoid(A / (1024 W))` (computed once in float64) are bit-identical. The property test checks this on random windows and permutations, and a negative control shows that float32 accumulation of the same tiles in two orders gives different bits, so the test can detect the failure it guards against.

What the integer blend does not remove: the network's output depends on the tile's context. A pixel seen inside a 128 px tile gets a different logit than inside a 512 px tile. That is the tile-size sensitivity measured for EYE-P4 (model card); it is a property of the model, not of the blending.

## Areas

All km2 numbers come from pixel counts. The scene is UTM 42N at 10 m; each column's pixel area is `100 / k^2` m2 with the UTM point scale factor `k = 0.9996 (1 + (E - 500000)^2 / (2 R^2))`, tested against `pyproj.Geod` to 0.2%. Permanent water is the JRC occurrence >= 50% mask dilated by 3 pixels. `new_flood = total_water - permanent_water` exactly, because both sides use the same pixels and areas, and the district sums are a partition of the same pixels (EYE-P3, X8). Polygons are for display; their area is checked against the raster area (X4).

## Limitations

- Domain shift: Sen1Floods11 sigma0 comes from Google Earth Engine GRD; the demo scene is RTC gamma0 converted to sigma0 with a flat-terrain incidence correction. The +-1.5 dB augmentation covers part of the offset, not all of it.
- Not validated for Sindh, the Indus plain or 2022.
- Permanent water is the 30 m JRC product on a 10 m grid; flood edges next to rivers can be hidden by the dilation.
- Smooth surfaces (tarmac, sand, radar shadow) look like water in SAR; flooded vegetation and towns can look dry.
- Tile-size sensitivity: smaller tiles than the 256 px training crop give less context and less detected water (model card).
