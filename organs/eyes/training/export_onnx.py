"""Export the selected checkpoint to ONNX, quantize, pick the shipped variant (design 3.5, task 4).

    python organs/eyes/training/export_onnx.py --ckpt data/raw/eyes-runs/cpu2/best.pt

1. Export ``RawDbUnet`` (preprocessing inside the graph) at opset 17, batch 1, dynamic H and W.
2. Variants: fp32, fp16 weights (``keep_io_types``), int8 static QDQ with per-channel weights
   calibrated on 200 train-split crops.
3. For each variant: validation-split water IoU through ONNX Runtime and the median latency of a
   256 x 256 tile on 2 threads.
4. Choose: int8 if its validation IoU drop is at most 1.0 point and it is not slower than fp32;
   else fp16; else fp32 if under 50,000,000 bytes.
5. Write ``organs/eyes/models/eyes_unet_r18.onnx``, ``preprocess.json`` and
   ``export_check.json`` (16 validation tiles: PyTorch vs shipped ONNX logit differences, mask
   agreement, IoU difference, SHA-256, variant, opset, versions, all benchmark rows).

The test split is not read here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from model import build  # noqa: E402

from data import epoch_samples, load_split  # noqa: E402

REPO = HERE.parents[2]
MODELS = HERE.parent / "models"
OPSET = 17
SIZE_LIMIT = 50_000_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ort_session(path: Path, threads: int = 2) -> Any:
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def ort_logits(sess: Any, x: np.ndarray) -> np.ndarray:
    out: np.ndarray = sess.run(None, {"db": x[None].astype(np.float32)})[0][0, 0]
    return out


def val_iou(sess: Any, chips: list[Any]) -> float:
    tp = fp = fn = 0
    for c in chips:
        pred = ort_logits(sess, c.s1) > 0
        keep = c.label != -1
        t = c.label == 1
        tp += int((pred & t & keep).sum())
        fp += int((pred & ~t & keep).sum())
        fn += int((~pred & t & keep).sum())
    return tp / max(tp + fp + fn, 1)


def latency(sess: Any, n: int = 12) -> float:
    rng = np.random.default_rng(0)
    x = rng.uniform(-25, -5, size=(2, 256, 256)).astype(np.float32)
    ort_logits(sess, x)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        ort_logits(sess, x)
        ts.append(time.perf_counter() - t)
    return float(np.median(ts))


class CalibReader:
    def __init__(self, crops: list[np.ndarray]) -> None:
        self._it = iter(crops)

    def get_next(self) -> dict[str, np.ndarray] | None:
        x = next(self._it, None)
        return None if x is None else {"db": x[None].astype(np.float32)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=HERE / "config.yaml")
    ap.add_argument("--data-root", type=Path)
    ap.add_argument("--work", type=Path, default=REPO / "data" / "raw" / "eyes-export")
    ap.add_argument("--max-chips", type=int, default=0)
    ap.add_argument("--calib", type=int, default=200)
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(args.config.read_text())
    root = args.data_root or (REPO / cfg["data_root"])
    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)
    pre = json.loads((args.ckpt.parent / "preprocess.json").read_text())

    model = build(cfg, pre["mean"], pre["std"], pretrained=False)
    ck = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    model.load_state_dict(ck["model"])
    model.eval()

    fp32 = work / "fp32.onnx"
    dummy = torch.zeros(1, 2, 256, 256)
    torch.onnx.export(
        model,
        (dummy,),
        str(fp32),
        input_names=["db"],
        output_names=["logit"],
        dynamic_axes={"db": {2: "H", 3: "W"}, "logit": {2: "H", 3: "W"}},
        opset_version=OPSET,
        do_constant_folding=True,
        dynamo=False,
    )
    import onnx
    from onnxconverter_common import float16  # type: ignore[import-not-found]

    fp16 = work / "fp16.onnx"
    m16 = float16.convert_float_to_float16(onnx.load(str(fp32)), keep_io_types=True)
    onnx.save(m16, str(fp16))

    from onnxruntime.quantization import (
        CalibrationMethod,
        QuantFormat,
        QuantType,
        quantize_static,
    )
    from onnxruntime.quantization.shape_inference import quant_pre_process

    train = load_split(root, "train", args.max_chips)
    rng = np.random.default_rng(1)
    aug = {"bias_db": 0.0, "noise_db": 0.0, "flips": False, "rot90": False, "quantize": True}
    crops = [s[0] for s in epoch_samples(rng, train, 256, 1, aug)][: args.calib]
    pre_q = work / "fp32_pre.onnx"
    quant_pre_process(str(fp32), str(pre_q))
    int8 = work / "int8.onnx"
    quantize_static(
        str(pre_q),
        str(int8),
        CalibReader(crops),
        quant_format=QuantFormat.QDQ,
        per_channel=True,
        activation_type=QuantType.QUInt8,
        weight_type=QuantType.QInt8,
        calibrate_method=CalibrationMethod.MinMax,
    )
    del train

    valid = load_split(root, "valid", args.max_chips)
    with torch.no_grad():
        torch_iou_tp = [0, 0, 0]
        for c in valid:
            z = model(torch.from_numpy(c.s1)[None])[0, 0].numpy()
            pred = z > 0
            keep = c.label != -1
            t = c.label == 1
            torch_iou_tp[0] += int((pred & t & keep).sum())
            torch_iou_tp[1] += int((pred & ~t & keep).sum())
            torch_iou_tp[2] += int((~pred & t & keep).sum())
    torch_iou = torch_iou_tp[0] / max(sum(torch_iou_tp), 1)
    rows: dict[str, dict[str, Any]] = {}
    for name, path in (("fp32", fp32), ("fp16", fp16), ("int8", int8)):
        sess = ort_session(path)
        rows[name] = {
            "bytes": path.stat().st_size,
            "val_iou": val_iou(sess, valid),
            "latency_s_256_2threads": latency(sess),
        }
        print(name, rows[name], flush=True)

    base = rows["fp32"]
    if (
        base["val_iou"] - rows["int8"]["val_iou"] <= 0.01
        and rows["int8"]["latency_s_256_2threads"] <= base["latency_s_256_2threads"]
    ):
        chosen = "int8"
    elif rows["fp16"]["bytes"] < SIZE_LIMIT:
        chosen = "fp16"
    else:
        chosen = "fp32"
    if rows[chosen]["bytes"] >= SIZE_LIMIT:
        raise SystemExit("no variant fits the 50 MB limit")
    MODELS.mkdir(parents=True, exist_ok=True)
    shipped = MODELS / "eyes_unet_r18.onnx"
    src = {"fp32": fp32, "fp16": fp16, "int8": int8}[chosen]
    shutil.copyfile(src, shipped)
    (MODELS / "preprocess.json").write_text(json.dumps(pre, indent=2) + "\n")

    sess = ort_session(shipped)
    rng = np.random.default_rng(2)
    tiles = []
    for c in valid:
        if len(tiles) == 16:
            break
        y0, x0 = (int(v) for v in rng.integers(0, 512 - 256 + 1, 2))
        tiles.append(c.s1[:, y0 : y0 + 256, x0 : x0 + 256])
    max_d, mean_d, agree, tps = 0.0, [], [], [0, 0, 0]
    with torch.no_grad():
        for t in tiles:
            zt = model(torch.from_numpy(np.ascontiguousarray(t))[None])[0, 0].numpy()
            zo = ort_logits(sess, np.ascontiguousarray(t))
            d = np.abs(zt - zo)
            max_d = max(max_d, float(d.max()))
            mean_d.append(float(d.mean()))
            agree.append(float(((zt > 0) == (zo > 0)).mean()))
            pt, po = zt > 0, zo > 0
            tps[0] += int((pt & po).sum())
            tps[1] += int((pt ^ po).sum())
    check = {
        "variant": chosen,
        "model_variant": f"unet-resnet18-s1-{chosen}",
        "file": shipped.name,
        "sha256": sha256(shipped),
        "bytes": shipped.stat().st_size,
        "opset": OPSET,
        "n_tiles": len(tiles),
        "tile": 256,
        "tiles_from": "sen1floods11 hand-labeled validation split, random 256 crops, seed 2",
        "max_abs_logit_diff": max_d,
        "mean_abs_logit_diff": float(np.mean(mean_d)),
        "mask_agreement": float(np.mean(agree)),
        "torch_val_iou": torch_iou,
        "onnx_val_iou": rows[chosen]["val_iou"],
        "val_iou_diff_points": 100 * abs(torch_iou - rows[chosen]["val_iou"]),
        "variants": rows,
        "selection_rule": "int8 if val IoU drop <= 1.0 point and latency <= fp32; else fp16; "
        "else fp32 if < 50,000,000 bytes",
        "versions": {
            "torch": torch.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": __import__("onnxruntime").__version__,
        },
        "checkpoint_epoch": int(ck.get("epoch", -1)),
    }
    (MODELS / "export_check.json").write_text(json.dumps(check, indent=2) + "\n")
    print(json.dumps(check, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
