"""Port audit for the Compose configuration (deploy design 12, DEP-P4, DEP-R4.2). Stdlib only.

    python deploy/bin/check_ports.py                         # base and prod combinations
    python deploy/bin/check_ports.py --config-json cfg.json  # a saved `compose config` JSON

Rules:
* only ``web`` publishes ports;
* ``web`` publishes 8080 only on a loopback host IP (dev and CI), or 80 and 443 (TCP, 443 also
  UDP) in production;
* every service except ``web`` is attached only to internal networks (no egress) in the default
  and production configurations;
* the ``core`` network is ``internal: true``.

Exit 0 when clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
PROD_ALLOWED = {("80", "tcp"), ("443", "tcp"), ("443", "udp")}

COMBINATIONS: dict[str, list[str]] = {
    "default": ["compose.yaml"],
    "prod": ["compose.yaml", "deploy/compose.prod.yaml"],
    "prod+lite": ["compose.yaml", "deploy/compose.lite.yaml", "deploy/compose.prod.yaml"],
}


def compose_config(files: list[str], root: Path) -> dict[str, Any]:
    cmd = ["docker", "compose", "--profile", "full", "--profile", "eyes"]
    for f in files:
        cmd += ["-f", f]
    cmd += ["config", "--format", "json"]
    env = {**os.environ, "ACME_EMAIL": os.environ.get("ACME_EMAIL", "ports-check@example.invalid")}
    res = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env, check=False)
    if res.returncode != 0:
        raise SystemExit(f"check_ports: docker compose config failed: {res.stderr.strip()}")
    doc: dict[str, Any] = json.loads(res.stdout)
    return doc


def audit(cfg: dict[str, Any], *, prod: bool) -> list[str]:
    problems: list[str] = []
    services: dict[str, Any] = cfg.get("services", {})
    networks: dict[str, Any] = cfg.get("networks", {})
    core = networks.get("core")
    if core is None or not core.get("internal"):
        problems.append("network core: must be internal: true (no internet route)")
    internal = {name for name, n in networks.items() if n and n.get("internal")}
    for name, svc in sorted(services.items()):
        ports = svc.get("ports") or []
        if name != "web":
            if ports:
                problems.append(f"service {name}: publishes {len(ports)} port(s); only web may")
            if svc.get("network_mode") not in (None, "none"):
                problems.append(f"service {name}: network_mode {svc['network_mode']} not allowed")
            nets = set((svc.get("networks") or {}).keys())
            egress = sorted(nets - internal)
            if egress:
                problems.append(f"service {name}: on non-internal network(s) {egress}")
            continue
        for p in ports:
            target = str(p.get("target"))
            published = str(p.get("published", ""))
            proto = str(p.get("protocol", "tcp"))
            host_ip = str(p.get("host_ip") or "0.0.0.0")
            if prod:
                if (published, proto) not in PROD_ALLOWED:
                    problems.append(
                        f"service web: prod publishes {host_ip}:{published}/{proto}; "
                        "only 80/tcp, 443/tcp, 443/udp"
                    )
            elif target != "8080" or host_ip not in LOOPBACK:
                problems.append(
                    f"service web: publishes {host_ip}:{published}->{target}; dev and CI bind "
                    "the gateway (8080) to a loopback address only"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose port and network audit (DEP-P4)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config-json", type=Path, help="audit a saved config instead")
    parser.add_argument("--prod", action="store_true", help="with --config-json: prod rules")
    args = parser.parse_args(argv)
    failures: list[str] = []
    if args.config_json:
        cfg = json.loads(args.config_json.read_text(encoding="utf-8"))
        failures += audit(cfg, prod=args.prod)
    else:
        for label, files in COMBINATIONS.items():
            cfg = compose_config(files, args.root)
            failures += [f"[{label}] {p}" for p in audit(cfg, prod=label.startswith("prod"))]
    for line in failures:
        print(f"FAIL: {line}")
    if failures:
        return 1
    print("check_ports: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
