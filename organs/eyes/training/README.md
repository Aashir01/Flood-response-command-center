# Eyes training (job A)

Fine-tunes the U-Net/ResNet-18 of `.kiro/specs/eyes-mcp/design.md` section 3 on Sentinel-1 VV+VH and exports it to ONNX. Nothing here runs in the organ image; PyTorch is in the `train` extra only.

| File | Purpose |
|---|---|
| `fetch_sen1floods11.py` | downloads the hand-labeled subset over HTTPS (stdlib only) and checks the split counts |
| `data.py` | chip loading, random crops, flips, rotations, dB offset, noise, the demo-scene uint8 quantization |
| `model.py` | `RawDbUnet`: clip, channel build (VV, VH, VV-VH) and normalization inside the module, so the ONNX file takes raw dB |
| `train.py` | BCE + Dice with ignore index, AdamW (two learning rates), cosine with warm-up, `--resume auto`, time budget |
| `export_onnx.py` | fp32, fp16-weights and int8 (three calibrations) variants, P5 check, latency, choice per design 3.5 |
| `config.yaml` | seed, model, augmentation, optimizer and the profiles (`full`, `vultr`, `laptop`, `laptop256`, `cpu`, `smoke`) |
| `runs/<profile>.json` | committed run logs (per-epoch loss, validation IoU and F1, wall time, versions) |

## Data

Sen1Floods11 v1.1 (Cloud to Street; Bonafilia et al. 2020, "Sen1Floods11: a georeferenced dataset to train and test deep learning flood algorithms for Sentinel-1", CVPR Workshops), public bucket `gs://sen1floods11` (`https://storage.googleapis.com/sen1floods11/v1.1/`). The script fetches `S1Hand`, `LabelHand` and `JRCWaterHand` for the four hand-labeled splits in `splits/flood_handlabeled/` and fails unless the counts are 252 train, 89 validation, 90 test and 15 Bolivia. 1,338 files, 0.73 GB.

License: CC BY 4.0 per the owner's brief. The GitHub repository (`cloudtostreet/Sen1Floods11`) has no LICENSE file and the README states none, and the bucket's STAC catalog lists `"license": "proprietary"` (checked 2026-11-17). Credit Cloud to Street and cite the paper. Only an 8-chip test sample is committed (`evals/eyes/data/`).

## Run of record

```
python organs/eyes/training/fetch_sen1floods11.py --dest /srv/data/sen1floods11
OMP_NUM_THREADS=2 nice -n 10 python organs/eyes/training/train.py --profile vultr \
  --data-root /srv/data/sen1floods11 --out /srv/eyes-runs/vultr --resume auto
python organs/eyes/training/export_onnx.py --ckpt /srv/eyes-runs/vultr/best.pt \
  --data-root /srv/data/sen1floods11
STITCH_SEN1FLOODS11_DIR=/srv/data/sen1floods11 python -m evals.run --organ eyes --seed 0
```

Environment: `uv sync --package stitch-eyes --extra train --frozen` (PyTorch CPU wheels from the `pytorch-cpu` index in `organs/eyes/pyproject.toml`). The `vultr` profile is the design's full profile (256 px crops, 4 per chip, batch 16, 60 epochs, 3 warm-up epochs) on 2 CPU threads of the Vultr VPS with a 230-minute budget. No GPU was used. The test split is read only by the eval, after the checkpoint is frozen.
