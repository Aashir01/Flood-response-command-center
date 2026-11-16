"""Fetch the Library's embedding and reranker models into the local model cache.

Build-time and dev-time only. The Library server never imports this module and never downloads
anything. Files come from pinned Hugging Face revisions and are checked against pinned sha256
values; a mismatch deletes the file and fails.

    uv run python scripts/fetch_models.py [--model e5-small|mmarco|all] [--dir DIR]

Default directory: ``STITCH_MODEL_DIR`` or ``data/raw/models`` (git-ignored). After fetching
e5-small, run ``scripts/export_models.py`` to build the int8 ONNX file the server loads.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HF = "https://huggingface.co"


@dataclass(frozen=True)
class RemoteFile:
    path: str  # path inside the HF repo
    sha256: str
    size: int
    local: str  # file name inside the model directory


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    revision: str
    license: str
    files: tuple[RemoteFile, ...]


MODELS: dict[str, ModelSpec] = {
    "e5-small": ModelSpec(
        key="e5-small",
        repo="intfloat/multilingual-e5-small",
        revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
        license="MIT",
        files=(
            RemoteFile(
                "onnx/model.onnx",
                "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665",
                470268510,
                "model_fp32.onnx",
            ),
            RemoteFile(
                "onnx/tokenizer.json",
                "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
                17082730,
                "tokenizer.json",
            ),
            RemoteFile(
                "onnx/config.json",
                "bbb7c1333fc4b3e27fbc9cd5d2070aabcc1d4dfb99917c3633e772f97545a6b6",
                653,
                "config.json",
            ),
        ),
    ),
    "mmarco": ModelSpec(
        key="mmarco",
        repo="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        revision="1427fd652930e4ba29e8149678df786c240d8825",
        license="Apache-2.0",
        files=(
            # Prebuilt dynamic uint8 quantization for AVX2 (runs on any AVX2 x86 CPU).
            RemoteFile(
                "onnx/model_quint8_avx2.onnx",
                "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b",
                118620016,
                "model_int8.onnx",
            ),
            RemoteFile(
                "tokenizer.json",
                "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
                17082660,
                "tokenizer.json",
            ),
            RemoteFile(
                "config.json",
                "cc2cfe51aa3fd759d21d21acf5dfd6994aa67a3c9210636d22e143699d336c77",
                891,
                "config.json",
            ),
        ),
    ),
}


def model_dir(base: Path, spec: ModelSpec) -> Path:
    return base / spec.key


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(spec: ModelSpec, base: Path) -> None:
    out = model_dir(base, spec)
    out.mkdir(parents=True, exist_ok=True)
    for f in spec.files:
        dest = out / f.local
        if dest.exists() and dest.stat().st_size == f.size and sha256_file(dest) == f.sha256:
            print(f"ok      {spec.key}/{f.local}")
            continue
        url = f"{HF}/{spec.repo}/resolve/{spec.revision}/{f.path}"
        tmp = dest.with_suffix(dest.suffix + ".part")
        print(f"fetch   {url}")
        with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as fh:
            while block := resp.read(1 << 20):
                fh.write(block)
        digest = sha256_file(tmp)
        if digest != f.sha256:
            tmp.unlink()
            raise SystemExit(f"sha256 mismatch for {f.path}: {digest} != {f.sha256}")
        tmp.replace(dest)
        print(f"saved   {dest} ({f.size} bytes)")
    (out / "REVISION").write_text(f"{spec.repo}@{spec.revision}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=[*MODELS, "all"], default="all")
    default_dir = Path(os.environ.get("STITCH_MODEL_DIR") or REPO_ROOT / "data" / "raw" / "models")
    parser.add_argument("--dir", type=Path, default=default_dir)
    args = parser.parse_args(argv)
    keys = list(MODELS) if args.model == "all" else [args.model]
    for key in keys:
        fetch(MODELS[key], args.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
