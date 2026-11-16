"""BOOT-R4: helpers of scripts/mcp_probe.py (the servers themselves are probed by hand)."""

from __future__ import annotations

import json
from pathlib import Path

import mcp_probe
import pytest

CONFIG = Path(__file__).resolve().parents[1] / ".kiro" / "settings" / "mcp.json"


def test_expand_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_TOKEN", "abc")
    assert mcp_probe.expand("Bearer ${X_TOKEN}") == "Bearer abc"
    assert mcp_probe.expand("${UNSET_VAR_FOR_TEST}") == ""


def test_select_defaults_to_enabled_stdio() -> None:
    servers = {
        "a": {"command": "x", "disabled": False},
        "b": {"command": "x", "disabled": True},
        "c": {"url": "https://example.test", "disabled": False},
    }
    assert list(mcp_probe.select(servers, [])) == ["a"]
    assert list(mcp_probe.select(servers, ["b"])) == ["b"]
    with pytest.raises(SystemExit):
        mcp_probe.select(servers, ["zzz"])


def test_committed_config_shape() -> None:
    """Checked only once .kiro/settings/mcp.json exists (task 10)."""
    if not CONFIG.exists():
        pytest.skip("mcp.json not written yet")
    servers = json.loads(CONFIG.read_text(encoding="utf-8"))["mcpServers"]
    assert {"eyes-mcp", "oracle-mcp", "library-mcp", "ledger-mcp", "voice-mcp"} <= set(servers)
    assert {"github", "filesystem", "fetch"} <= set(servers)
    text = CONFIG.read_text(encoding="utf-8")
    assert "ghp_" not in text and "github_pat_" not in text
    assert servers["github"]["headers"]["Authorization"] == "Bearer ${GITHUB_TOKEN}"
    for name, cfg in servers.items():
        assert isinstance(cfg["disabled"], bool)
        assert ("command" in cfg) != ("url" in cfg), name
