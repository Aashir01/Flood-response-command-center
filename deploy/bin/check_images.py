"""Image checks (deploy design 4, 12; DEP-R2.1, R2.2). Needs Docker; stdlib only.

    python deploy/bin/check_images.py                       # every image in image-budgets.json
    python deploy/bin/check_images.py --tag <sha> ledger web

For each image (``${REGISTRY}/${GH_OWNER}/stitch-<name>:${TAG}``):
* the unpacked root filesystem size (``du -sx /`` in the image) is within
  ``deploy/image-budgets.json``;
* the configured user is set and is not root;
* Python images: ``torch`` is not importable, the service package imports with a read-only root
  filesystem, no network and all capabilities dropped;
* the gateway: ``caddy validate`` accepts both Caddyfiles.

Missing images are reported and fail unless ``--skip-missing``. Exit 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUDGETS = REPO_ROOT / "deploy" / "image-budgets.json"
HARDENED = [
    "--rm",
    "--read-only",
    "--tmpfs",
    "/tmp:size=64m",
    "--network",
    "none",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges:true",
]
NO_TORCH = "import importlib.util,sys; sys.exit(1 if importlib.util.find_spec('torch') else 0)"


def docker(*args: str, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def image_ref(name: str, tag: str) -> str:
    registry = os.environ.get("REGISTRY", "ghcr.io")
    owner = os.environ.get("GH_OWNER", "stitch-local")
    return f"{registry}/{owner}/stitch-{name}:{tag}"


def check(name: str, spec: dict[str, object], tag: str, skip_missing: bool) -> list[str]:
    ref = image_ref(name, tag)
    res = docker("image", "inspect", ref, "--format", "{{json .}}")
    if res.returncode != 0:
        return [] if skip_missing else [f"{name}: image {ref} not found"]
    info = json.loads(res.stdout)
    problems: list[str] = []
    # Unpacked root filesystem size. `docker image inspect .Size` is not comparable across
    # hosts: with the containerd image store it adds the compressed layers to the unpacked size.
    du = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "sh",
        ref,
        "-c",
        "du -sxk / 2>/dev/null | cut -f1",
    )
    try:
        size_mb = int(du.stdout.strip().splitlines()[-1]) * 1024 / 1e6
    except (ValueError, IndexError):
        size_mb = int(info.get("Size", 0)) / 1e6
    budget = float(spec["budget_mb"])  # type: ignore[arg-type]
    if size_mb > budget:
        problems.append(f"{name}: {size_mb:.0f} MB exceeds the budget of {budget:.0f} MB")
    user = str(info.get("Config", {}).get("User") or "")
    if user.split(":")[0] in ("", "0", "root"):
        problems.append(f"{name}: runs as root (Config.User={user!r})")
    module = spec.get("module")
    if module:
        r = docker("run", *HARDENED, ref, "python", "-c", NO_TORCH)
        if r.returncode != 0:
            problems.append(f"{name}: torch is importable (training dependency leaked)")
        r = docker("run", *HARDENED, ref, "python", "-c", f"import {module}")
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["?"]
            problems.append(f"{name}: `import {module}` fails read-only: {tail[0]}")
    if spec.get("caddyfiles"):
        for cf in spec["caddyfiles"]:  # type: ignore[attr-defined]
            r = docker(
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "ACME_EMAIL=ci@example.invalid",
                ref,
                "caddy",
                "validate",
                "--config",
                str(cf),
                "--adapter",
                "caddyfile",
            )
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["?"]
                problems.append(f"{name}: caddy validate {cf}: {tail[0]}")
    print(
        f"{name}: {size_mb:.0f} MB (budget {budget:.0f}), user {user}"
        + ("" if problems else ", ok")
    )
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stitch image checks")
    p.add_argument("names", nargs="*", help="image short names (default: all in the budget file)")
    p.add_argument("--tag", default=os.environ.get("TAG", "local"))
    p.add_argument("--skip-missing", action="store_true")
    args = p.parse_args(argv)
    doc = json.loads(BUDGETS.read_text(encoding="utf-8"))
    budgets: dict[str, dict[str, object]] = doc["images"]
    names = args.names or list(budgets)
    failures: list[str] = []
    for n in names:
        if n not in budgets:
            failures.append(f"{n}: no entry in {BUDGETS.name}")
            continue
        failures += check(n, budgets[n], args.tag, args.skip_missing)
    for f in failures:
        print(f"FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
