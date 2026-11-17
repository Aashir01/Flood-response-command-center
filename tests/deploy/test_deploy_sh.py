"""DEP-R6.3: the SSH forced command (deploy/bin/deploy.sh) accepts only a 40-hex commit sha,
`rollback` or `status`, and refuses everything else before doing any work."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "deploy.sh"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


def _bash() -> str | None:
    if os.name == "nt":  # WSL's bash.exe would run a different distribution; use Git Bash
        return str(GIT_BASH) if GIT_BASH.is_file() else None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

VALID = ["0" * 40, "84e67ed" + "a" * 33, "rollback", "status"]
INVALID = [
    "",
    "; rm -rf /",
    "../../etc/passwd",
    "a" * 39,
    "a" * 41,
    "A" * 40,
    "rollback; id",
    "status && id",
    f"{'b' * 40} --force",
    "$(id)",
    "--validate",
]


def _run(
    args: list[str], env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    env = {k: v for k, v in os.environ.items() if k != "SSH_ORIGINAL_COMMAND"}
    env.update(env_extra or {})
    script = SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")
    return subprocess.run(
        [BASH, "-c", script, "stitch-deploy", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("arg", VALID)
def test_valid_arguments(arg: str) -> None:
    res = _run(["--validate", arg])
    assert res.returncode == 0 and res.stdout.strip() == "valid"


@pytest.mark.parametrize("arg", INVALID)
def test_invalid_arguments(arg: str) -> None:
    res = _run(["--validate", arg])
    assert res.returncode == 2 and res.stdout.strip() == "invalid"


@pytest.mark.parametrize(
    "cmd", ["; rm -rf /", "../", "", "bash -i", "rollback x", "c" * 40 + "\nrollback", "status\nid"]
)
def test_forced_command_refuses_before_any_work(cmd: str) -> None:
    res = _run([], {"SSH_ORIGINAL_COMMAND": cmd})
    assert res.returncode == 2
    assert "refused" in res.stderr
