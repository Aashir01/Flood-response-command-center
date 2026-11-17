"""Tile models and tiled inference (design 4, 10).

``TileModel.predict_logits(tile)`` maps a (2, T, T) float32 dB tile (VV, VH) to (T, T) float32
water logits. Implementations: ``OnnxTileModel`` (the shipped network), ``ThresholdTileModel``
(documented VH threshold fallback, design 10), and deterministic stubs for tests.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from stitch_eyes.core.blend import Accumulator, Blended, finalize
from stitch_eyes.core.grid import TileGrid, make_grid, pad_window

F32 = npt.NDArray[np.float32]


class TileModel(Protocol):
    name: str
    version: str
    sha256: str
    variant: str

    def predict_logits(self, tile: F32) -> F32: ...


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ModelIntegrityError(RuntimeError):
    pass


class OnnxTileModel:
    """ONNX Runtime session: batch 1, fixed intra-op threads, sequential, all optimizations."""

    def __init__(
        self,
        path: Path,
        expected_sha256: str | None,
        variant: str,
        version: str,
        threads: int = 2,
    ) -> None:
        import onnxruntime as ort

        if not path.exists():
            raise ModelIntegrityError(f"model file missing: {path.name}")
        sha = file_sha256(path)
        if expected_sha256 and sha != expected_sha256:
            raise ModelIntegrityError("model hash does not match the export check")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._sess: Any = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.name = "unet-resnet18-s1"
        self.version = version
        self.sha256 = sha
        self.variant = variant

    def predict_logits(self, tile: F32) -> F32:
        x = np.ascontiguousarray(tile, dtype=np.float32)[None]
        out = self._sess.run(None, {"db": x})[0]
        res: F32 = np.asarray(out[0, 0], dtype=np.float32)
        return res


@dataclass
class ThresholdTileModel:
    """Fallback: VH below a threshold is water, after a 3 x 3 mean (speckle) filter.

    The logit is ``(threshold - mean3x3(VH)) / scale``. The 3 x 3 receptive field is smaller
    than any tile overlap, so tiled output equals untiled output away from the window edge.
    """

    threshold_db: float = -20.0
    scale_db: float = 1.5
    name: str = "vh-threshold-baseline"
    version: str = "1"
    sha256: str = hashlib.sha256(b"vh-threshold-baseline:-20.0:1.5").hexdigest()
    variant: str = "vh-threshold-baseline"

    def predict_logits(self, tile: F32) -> F32:
        vh = np.asarray(tile[1], dtype=np.float64)
        p = np.pad(vh, 1, mode="edge")
        h, w = vh.shape
        m = sum(p[dy : dy + h, dx : dx + w] for dy in range(3) for dx in range(3)) / 9.0
        out: F32 = ((self.threshold_db - m) / self.scale_db).astype(np.float32)
        return out


def run_tiles(
    db: F32,
    tile_size: int,
    model: TileModel,
    order: Sequence[int] | None = None,
) -> tuple[Blended, TileGrid]:
    """Tile, infer and blend a (2, H, W) dB window. ``order`` permutes the tile sequence."""
    _, h, w = db.shape
    grid = make_grid(h, w, tile_size)
    padded = pad_window(np.asarray(db, np.float32), grid)
    origins = grid.origins()
    idx = list(order) if order is not None else list(range(len(origins)))
    if sorted(idx) != list(range(len(origins))):
        raise ValueError("order must be a permutation of the tile indices")
    acc = Accumulator.empty(grid)
    t = grid.tile
    for k in idx:
        y, x = origins[k]
        tile = np.ascontiguousarray(padded[:, y : y + t, x : x + t])
        acc.add((y, x), model.predict_logits(tile))
    return finalize(acc), grid
