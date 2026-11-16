"""BOOT-R5.1 and R5.6: the surgeon agent file is well-formed and constrained.

This checks structure only. Whether the Kiro IDE accepts the file is verified by loading the
agent list in the IDE (see docs/kiro-writeup.md).
"""

from __future__ import annotations

from typing import Any

import yaml
from scaffold_organ import REPO_ROOT

AGENT = REPO_ROOT / ".kiro" / "agents" / "surgeon.md"
ALLOWED_FIELDS = {
    "name",
    "description",
    "prompt",
    "model",
    "tools",
    "excludedTools",
    "includeMcpJson",
    "resources",
    "permissions",
}


def load() -> tuple[dict[str, Any], str]:
    text = AGENT.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, front, body = text.split("---\n", 2)
    data = yaml.safe_load(front)
    assert isinstance(data, dict)
    return data, body


def test_front_matter_fields_are_known_and_hooks_are_absent() -> None:
    data, body = load()
    assert set(data) <= ALLOWED_FIELDS
    assert "hooks" not in data  # the hooks field is CLI-only
    assert data["name"] == "surgeon" and data["description"]
    assert body.strip(), "body is the system prompt"


def test_permissions_allow_only_the_scaffold_flow() -> None:
    data, _ = load()
    rules = data["permissions"]["rules"]
    assert all(set(r) == {"capability", "match", "effect"} for r in rules)
    assert all(r["effect"] in {"allow", "ask", "deny"} for r in rules)
    allow_shell = [
        m
        for r in rules
        if r["capability"] == "shell" and r["effect"] == "allow"
        for m in r["match"]
    ]
    assert "uv run python scripts/scaffold_organ.py *" in allow_shell
    assert not any(m.startswith(("rm", "del", "git")) for m in allow_shell)
    deny_shell = [
        m for r in rules if r["capability"] == "shell" and r["effect"] == "deny" for m in r["match"]
    ]
    for needle in ("rm *", "del *", "git push*", "git reset*"):
        assert needle in deny_shell
    write_allowed = [
        m
        for r in rules
        if r["capability"] == "fs_write" and r["effect"] == "allow"
        for m in r["match"]
    ]
    assert sorted(write_allowed) == sorted(
        ["organs/**", ".kiro/specs/**", ".kiro/settings/mcp.json"]
    )


def test_resources_point_at_existing_steering_and_template() -> None:
    data, _ = load()
    for res in data["resources"]:
        assert res.startswith("file://")
    assert (REPO_ROOT / ".kiro" / "steering" / "mcp-contracts.md").exists()
    assert (REPO_ROOT / ".kiro" / "templates" / "organ").is_dir()


def test_prompt_only_references_existing_scripts() -> None:
    _, body = load()
    for script in ("scripts/scaffold_organ.py", "scripts/check_contracts.py"):
        assert script in body and (REPO_ROOT / script).is_file()
