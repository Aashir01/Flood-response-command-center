"""LightGBM import and predict check, run inside the Python base image (oracle task 1).

    docker run --rm -v "<repo>/scripts:/s:ro" <python image> \
        sh -c "pip install -q 'lightgbm>=4.5,<5' && python /s/check_lightgbm_image.py"

Trains a 5-tree quantile booster on random data and predicts one row. On a slim image without
the OpenMP runtime (``libgomp1``) the import fails, which is what this check is for.
"""

from __future__ import annotations

import lightgbm
import numpy as np


def main() -> int:
    rng = np.random.default_rng(0)
    params = {"objective": "quantile", "alpha": 0.5, "verbosity": -1, "num_threads": 1}
    data = lightgbm.Dataset(rng.random((200, 3)), rng.random(200))
    booster = lightgbm.train(params, data, num_boost_round=5)
    pred = booster.predict(np.zeros((1, 3)), pred_contrib=True)
    print(f"lightgbm {lightgbm.__version__} ok, contrib shape {np.shape(pred)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
