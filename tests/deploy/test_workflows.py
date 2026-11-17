"""DEP-R5, DEP-R6: CI and CD workflows parse, pin third-party actions by commit SHA, and carry
the deployment jobs (images, offline stack smoke, Playwright against the stack, GHCR publish,
forced-command deploy, post-deploy smoke, rollback)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    return doc


def _steps_text(job: dict[str, Any]) -> str:
    return "\n".join(
        f"{s.get('uses', '')}\n{s.get('run', '')}\n{s.get('with', '')}" for s in job["steps"]
    )


def test_every_action_is_pinned_by_sha() -> None:
    for name in ("ci.yml", "cd.yml"):
        for job_name, job in _load(name)["jobs"].items():
            for step in job["steps"]:
                uses = step.get("uses")
                if uses:
                    assert PINNED.match(uses), f"{name}:{job_name}: {uses} is not pinned"


def test_ci_has_deployment_jobs() -> None:
    jobs = _load("ci.yml")["jobs"]
    assert {"hygiene", "python", "frontend", "images", "stack-smoke", "evals-smoke"} <= set(jobs)
    hygiene = _steps_text(jobs["hygiene"])
    for needle in ("check_repo_hygiene.py", "config -q", "check_ports.py", "caddy validate"):
        assert needle in hygiene, needle
    images = _steps_text(jobs["images"])
    assert "docker-bake.hcl" in images and "check_images.py" in images
    stack = _steps_text(jobs["stack-smoke"])
    for needle in ("--wait", "offline_smoke.sh", "stack.config.ts", "--no-build"):
        assert needle in stack, needle


def test_cd_publishes_by_sha_and_rolls_back() -> None:
    doc = _load("cd.yml")
    trigger = doc[True]  # YAML 1.1 reads `on` as True
    assert trigger["workflow_run"]["workflows"] == ["ci"]
    jobs = doc["jobs"]
    assert jobs["publish"]["permissions"]["packages"] == "write"
    publish = _steps_text(jobs["publish"])
    assert "push: True" in publish or "'push': True" in publish
    deploy = jobs["deploy"]
    assert deploy["environment"] == "production"
    text = _steps_text(deploy)
    assert "StrictHostKeyChecking=yes" in text
    assert "deploy@$VPS_HOST" in text
    assert "smoke.py" in text
    assert "rollback" in text
