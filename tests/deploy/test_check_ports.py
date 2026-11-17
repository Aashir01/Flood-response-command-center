"""DEP-P4, DEP-R4.2: port and network audit (deploy/bin/check_ports.py) on synthetic configs."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "check_ports.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_ports", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_ports"] = mod
    spec.loader.exec_module(mod)
    return mod


cp = _load()


def _cfg(prod: bool = False) -> dict[str, Any]:
    web_ports = (
        [
            {"target": 80, "published": "80", "protocol": "tcp"},
            {"target": 443, "published": "443", "protocol": "tcp"},
            {"target": 443, "published": "443", "protocol": "udp"},
        ]
        if prod
        else [{"target": 8080, "published": "8080", "protocol": "tcp", "host_ip": "127.0.0.1"}]
    )
    return {
        "networks": {"core": {"internal": True}, "edge": {}},
        "services": {
            "init-secrets": {"network_mode": "none"},
            "postgres": {"networks": {"core": None}},
            "brain": {"networks": {"core": None}},
            "web": {"networks": {"core": None, "edge": None}, "ports": web_ports},
        },
    }


def test_clean_configs_pass() -> None:
    assert cp.audit(_cfg(), prod=False) == []
    assert cp.audit(_cfg(prod=True), prod=True) == []


def test_published_postgres_port_fails() -> None:
    cfg = _cfg(prod=True)
    cfg["services"]["postgres"]["ports"] = [{"target": 5432, "published": "5432"}]
    assert any("postgres" in p for p in cp.audit(cfg, prod=True))


def test_core_not_internal_fails() -> None:
    cfg = _cfg()
    cfg["networks"]["core"] = {}
    problems = cp.audit(cfg, prod=False)
    assert any("internal" in p for p in problems)


def test_organ_on_egress_network_fails() -> None:
    cfg = copy.deepcopy(_cfg())
    cfg["networks"]["egress"] = {}
    cfg["services"]["brain"]["networks"]["egress"] = None
    assert any("brain" in p and "egress" in p for p in cp.audit(cfg, prod=False))


def test_dev_gateway_on_public_interface_fails() -> None:
    cfg = _cfg()
    cfg["services"]["web"]["ports"][0]["host_ip"] = "0.0.0.0"
    assert cp.audit(cfg, prod=False)


def test_prod_extra_port_fails() -> None:
    cfg = _cfg(prod=True)
    cfg["services"]["web"]["ports"].append({"target": 8080, "published": "8080"})
    assert cp.audit(cfg, prod=True)
