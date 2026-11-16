"""Model bundle (design section 4.1): LightGBM text models plus a SHA-256 manifest.

No pickle anywhere. Model files are LightGBM text, gzip-compressed with a fixed header (mtime 0)
so the committed bytes are reproducible and the bundle stays under the 10 MB budget (the plain text
is about 20 MB). ``ModelBundle.load`` reads each file's bytes once, checks its SHA-256 against
``manifest.json`` and only then parses it (``Booster(model_str=...)``), so the checked bytes are
the loaded bytes. The root hash (SHA-256 of the sorted ``name:sha256`` lines) is the
``model.sha256`` of the provenance block (ORA-R6.2). Any mismatch raises ``BundleError``.

``QuantileModel`` is the interface the forecast pipeline uses, so property tests can run on a
fast stub instead of LightGBM.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from stitch_oracle.core.conformal import ConformityTable

QUANTILES = (0.1, 0.5, 0.9)
MANIFEST = "manifest.json"
CONFORMITY = "conformity.parquet"


class BundleError(Exception):
    """The model bundle is missing, incomplete or fails its hash check."""


class QuantileModel(Protocol):
    name: str
    version: str
    sha256: str
    leads: tuple[int, ...]
    features: tuple[str, ...]
    feature_ranges: Mapping[str, tuple[float, float]]
    station_codes: Mapping[str, int]
    conformity: ConformityTable

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Raw quantiles in target space, shape ``(n, len(leads), 3)``."""
        ...

    def contrib(self, x: np.ndarray, lead: int) -> np.ndarray:
        """TreeSHAP contributions of the p50 model at ``lead``: shape ``(n, F + 1)``, the last
        column is the bias ``phi_0``."""
        ...


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root_hash(files: Mapping[str, str]) -> str:
    lines = "".join(f"{name}:{files[name]}\n" for name in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def model_file(q: float, lead: int) -> str:
    return f"lgbm/q{round(q * 100):02d}_l{lead:02d}.txt.gz"


@dataclass
class ModelBundle:
    name: str
    version: str
    sha256: str
    leads: tuple[int, ...]
    features: tuple[str, ...]
    feature_ranges: Mapping[str, tuple[float, float]]
    station_codes: Mapping[str, int]
    conformity: ConformityTable
    manifest: Mapping[str, Any]
    _boosters: Mapping[tuple[float, int], Any]

    @staticmethod
    def load(root: Path) -> ModelBundle:
        import lightgbm as lgb  # heavy import kept local
        import pandas as pd

        mpath = root / MANIFEST
        if not mpath.is_file():
            raise BundleError(f"manifest not found: {mpath}")
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            files: dict[str, str] = dict(manifest["files"])
        except (ValueError, KeyError, TypeError) as exc:
            raise BundleError("manifest unreadable") from exc
        if root_hash(files) != manifest.get("root_sha256"):
            raise BundleError("manifest root hash mismatch")
        blobs: dict[str, bytes] = {}
        for name, expected in files.items():
            path = (root / name).resolve()
            if root.resolve() not in path.parents:
                raise BundleError(f"manifest path escapes the bundle: {name}")
            if not path.is_file():
                raise BundleError(f"model file missing: {name}")
            data = path.read_bytes()
            if file_sha256(data) != expected:
                raise BundleError(f"hash mismatch: {name}")
            blobs[name] = data
        leads = tuple(int(h) for h in manifest["leads"])
        boosters: dict[tuple[float, int], Any] = {}
        for q in QUANTILES:
            for h in leads:
                name = model_file(q, h)
                if name not in blobs:
                    raise BundleError(f"model file not in manifest: {name}")
                text = gzip.decompress(blobs[name]).decode("utf-8")
                boosters[(q, h)] = lgb.Booster(model_str=text)
        if CONFORMITY not in blobs:
            raise BundleError("conformity scores not in manifest")
        cf = pd.read_parquet(io.BytesIO(blobs[CONFORMITY]))
        raw = {
            (str(sid), int(h)): g["score"].to_numpy("float64")
            for (sid, h), g in cf.groupby(["station_id", "lead"], sort=True)
        }
        conformity = ConformityTable.build(raw, int(manifest.get("min_cal", 500)))
        ranges = {k: (float(v[0]), float(v[1])) for k, v in manifest["feature_ranges"].items()}
        return ModelBundle(
            name=str(manifest["name"]),
            version=str(manifest["version"]),
            sha256=str(manifest["root_sha256"]),
            leads=leads,
            features=tuple(manifest["features"]),
            feature_ranges=ranges,
            station_codes={str(k): int(v) for k, v in manifest["station_codes"].items()},
            conformity=conformity,
            manifest=manifest,
            _boosters=boosters,
        )

    def predict(self, x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, dtype="float64"))
        out = np.empty((x.shape[0], len(self.leads), 3), dtype="float64")
        for j, h in enumerate(self.leads):
            for i, q in enumerate(QUANTILES):
                out[:, j, i] = self._boosters[(q, h)].predict(x, num_threads=1)
        return out

    def contrib(self, x: np.ndarray, lead: int) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, dtype="float64"))
        return np.asarray(
            self._boosters[(0.5, lead)].predict(x, pred_contrib=True, num_threads=1),
            dtype="float64",
        )
