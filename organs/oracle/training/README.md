# Oracle training

The core model needs no GPU. 42 LightGBM quantile boosters (3 quantiles x 14 lead days) train in
about 4 minutes on the dev laptop (i5, 16 GB, CPU only), single-threaded with seed 0, so Colab
and Modal are not needed for the core path. `oracle_train.ipynb` runs the same script on the free
Colab CPU runtime if wanted.

| File | Purpose |
|---|---|
| `train_gbm.py` | design matrix from the committed demo Parquet, fit with early stopping on train_val, refit on 1997-2011, CQR conformity scores on 2012-2016, write `models/` and `manifest.json` |
| `config.yaml` | hyperparameters (design section 4.2), seed, leads, quantiles |
| `oracle_train.ipynb` | Colab/laptop notebook: pins versions, clones at a commit, runs `train_gbm.py --resume`, verifies the manifest, copies to Drive |

```
uv run python scripts/build_oracle_demo.py --offline   # only if data/raw/oracle/ is populated
uv run python organs/oracle/training/train_gbm.py        # about 4 min
uv run python organs/oracle/training/train_gbm.py --resume
```

Only exported artifacts are committed: `models/lgbm/*.txt.gz` (LightGBM text models, gzip with
mtime 0), `models/conformity.parquet`, `models/manifest.json`. No checkpoints, no pickle, no raw
downloads. A rerun on the same data writes byte-identical model files (tested on a small fixture
in `tests/unit/test_training.py`; the full rerun was checked by hand, see the model card).

The target is modeled river discharge (GloFAS via Open-Meteo), never a gauge record.
