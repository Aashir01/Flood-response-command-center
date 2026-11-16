"""BOOT-R6: hook JSON files match the Kiro v1 schema, and the hook scripts behave on odd input."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import hook_io
import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
HOOK_DIR = ROOT / ".kiro" / "hooks"
TRIGGERS = {
    "PostFileSave",
    "PostFileCreate",
    "PostFileDelete",
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SessionStart",
    "PreTaskExec",
    "PostTaskExec",
}
FILE_TRIGGERS = {"PostFileSave", "PostFileCreate", "PostFileDelete"}
REQUIRED = {
    "on-save-organ-tests",
    "on-save-contract-validate",
    "on-spec-change-tasks",
    "on-save-eval-dashboard",
    "pre-commit-lint-secrets",
}


def _hooks() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for f in sorted(HOOK_DIR.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["version"] == "v1", f.name
        assert isinstance(doc["hooks"], list) and doc["hooks"], f.name
        out.extend((f.stem, h) for h in doc["hooks"])
    return out


def test_required_hooks_exist() -> None:
    assert {stem for stem, _ in _hooks()} >= REQUIRED


@pytest.mark.parametrize(("stem", "hook"), _hooks())
def test_hook_schema(stem: str, hook: dict[str, Any]) -> None:
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", stem)
    assert hook["name"] == stem
    assert isinstance(hook["description"], str) and hook["description"]
    assert hook["trigger"] in TRIGGERS
    assert isinstance(hook["enabled"], bool)
    assert isinstance(hook["timeout"], int) and hook["timeout"] > 0
    re.compile(hook["matcher"])
    action = hook["action"]
    if action["type"] == "command":
        assert isinstance(action["command"], str) and action["command"]
        script = re.search(r"scripts/\S+\.py", action["command"])
        assert script and (ROOT / script.group(0)).is_file()
    else:
        assert action["type"] == "agent"
        assert isinstance(action["prompt"], str) and action["prompt"]
    assert set(action) <= {"type", "command", "prompt"}


def _by_name() -> dict[str, dict[str, Any]]:
    return dict(_hooks())


def test_matchers_select_expected_files() -> None:
    hooks = _by_name()

    def hit(name: str, path: str) -> bool:
        return re.search(hooks[name]["matcher"], path) is not None

    assert hit("on-save-organ-tests", "organs/ledger/src/stitch_ledger/core/x.py")
    assert hit("on-save-organ-tests", "organs\\ledger\\tests\\test_a.py")
    assert not hit("on-save-organ-tests", "packages/stitch_common/src/a.py")
    assert hit("on-save-contract-validate", "organs/eyes/src/stitch_eyes/server.py")
    assert hit("on-save-contract-validate", "packages/stitch_common/src/stitch_common/types.py")
    assert hit("on-save-contract-validate", ".kiro/steering/mcp-contracts.md")
    assert not hit("on-save-contract-validate", "organs/eyes/src/stitch_eyes/core/a.py")
    assert hit("on-spec-change-tasks", ".kiro/specs/ledger-mcp/design.md")
    assert not hit("on-spec-change-tasks", ".kiro/specs/ledger-mcp/tasks.md")
    assert hit("on-save-eval-dashboard", "evals/ledger.py")
    assert hit("on-save-eval-dashboard", "organs/ledger/src/x.py")
    assert not hit("on-save-eval-dashboard", "docs/a.py")


def test_trigger_matcher_pairing() -> None:
    for _, h in _hooks():
        if h["trigger"] == "PreToolUse":
            assert h["matcher"] == "shell"
        elif h["trigger"] in FILE_TRIGGERS:
            assert h["matcher"] != "shell"
    assert _by_name()["on-spec-change-tasks"]["action"]["type"] == "agent"


def test_no_kiro_in_gitignore() -> None:
    lines = [
        ln.strip()
        for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]
    assert not any(ln.strip("/*!") == ".kiro" for ln in lines)
    assert ".stitch-hook-debug/" in lines


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"file_path": "organs/ledger/src/a.py"}, ["organs/ledger/src/a.py"]),
        ({"tool_input": {"path": str(ROOT / "organs" / "x" / "a.py")}}, ["organs/x/a.py"]),
        ({"uri": "file:///" + (ROOT / "evals" / "run.py").as_posix()}, ["evals/run.py"]),
        ({"x": ["../../etc/passwd.txt", "C:/Windows/a.dll"]}, []),
        ({"k": "no path here"}, []),
        (None, []),
    ],
)
def test_find_paths(payload: Any, expected: list[str]) -> None:
    assert hook_io.find_paths(payload) == expected


def test_organs_from_paths(tmp_path: Path) -> None:
    (tmp_path / "organs" / "ledger").mkdir(parents=True)
    paths = ["organs/ledger/src/a.py", "evals/ledger.py", "evals/run.py", "organs/nope/a.py"]
    assert hook_io.organs_from_paths(paths, tmp_path) == ["ledger"]
    assert hook_io.organs_from_paths(["evals/ledger/x.py"], tmp_path) == ["ledger"]


def test_read_event_tolerates_bad_input() -> None:
    assert hook_io.read_event(io.StringIO(""))[0] is None
    parsed, raw = hook_io.read_event(io.StringIO("not json"))
    assert parsed is None and raw == "not json"
    assert hook_io.read_event(io.StringIO('{"a": 1}'))[0] == {"a": 1}


@given(
    st.recursive(
        st.none() | st.text(max_size=30),
        lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=8), c, max_size=3),
        max_leaves=12,
    )
)
def test_find_paths_never_raises(payload: Any) -> None:
    assert isinstance(hook_io.find_paths(payload), list)
    hook_io.find_command(payload)


def test_log_event_writes_debug_file(tmp_path: Path) -> None:
    hook_io.log_event("t", '{"a":1}', tmp_path)
    data = json.loads((tmp_path / hook_io.DEBUG_DIR / "t.last.json").read_text(encoding="utf-8"))
    assert data["raw"] == '{"a":1}'


def test_tail() -> None:
    assert hook_io.tail("\n".join(map(str, range(100))), 3) == "97\n98\n99"
