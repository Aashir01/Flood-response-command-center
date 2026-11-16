"""Build the int8 embedding model the Library loads, with a parity check (design section 6.6).

Runs ONNX Runtime dynamic int8 quantization on ``e5-small/model_fp32.onnx`` (fetched by
``scripts/fetch_models.py``) and writes ``e5-small/model_int8.onnx``. Dynamic quantization runs on
any AVX2 x86 CPU, unlike the repo's prebuilt AVX-512 VNNI file. Parity: mean cosine between fp32
and int8 embeddings of up to 200 committed chunks must be at least 0.99; otherwise the int8 file
is removed and the server uses fp32 (a log line says so). The reranker ships a prebuilt
AVX2 uint8 file and needs no export.

    uv run --extra export python scripts/export_models.py [--dir DIR]   # needs the `onnx` package
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
PARITY_MIN = 0.99


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_dir = Path(os.environ.get("STITCH_MODEL_DIR") or REPO_ROOT / "data" / "raw" / "models")
    parser.add_argument("--dir", type=Path, default=default_dir)
    parser.add_argument("--sample", type=int, default=200)
    args = parser.parse_args(argv)

    from onnxruntime.quantization import QuantType, quantize_dynamic

    from stitch_library.ml.embedder import DEFAULT_EMBED_MODEL, EMBEDDERS, OnnxEmbedder
    from stitch_library.pack import load_pack_chunks

    spec = EMBEDDERS[DEFAULT_EMBED_MODEL]
    base = args.dir / spec.key
    fp32, int8 = base / "model_fp32.onnx", base / "model_int8.onnx"
    if not fp32.exists():
        print(f"missing {fp32}; run scripts/fetch_models.py first", file=sys.stderr)
        return 1
    tmp = int8.with_suffix(".onnx.tmp")
    quantize_dynamic(str(fp32), str(tmp), weight_type=QuantType.QInt8, per_channel=True)
    tmp.replace(int8)

    texts = [c.text for c in load_pack_chunks()][: args.sample] or [
        "Store at least one gallon of water per person per day.",
        "پانی کو کم از کم ایک منٹ تک ابالیں۔",  # noqa: RUF001
    ]
    q8 = OnnxEmbedder(spec, args.dir)
    int8.rename(int8.with_suffix(".onnx.hold"))
    try:
        f32 = OnnxEmbedder(spec, args.dir)
    finally:
        int8.with_suffix(".onnx.hold").rename(int8)
    a, b = q8.embed_passages(texts), f32.embed_passages(texts)
    parity = float(np.mean(np.sum(a * b, axis=1)))
    report = {"model": spec.repo, "revision": spec.revision, "n": len(texts), "mean_cosine": parity}
    print(json.dumps(report))
    if parity < PARITY_MIN:
        int8.unlink()
        print(f"parity {parity:.4f} < {PARITY_MIN}: int8 removed, the server will use fp32")
        return 0
    (base / "export_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {int8} ({int8.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
