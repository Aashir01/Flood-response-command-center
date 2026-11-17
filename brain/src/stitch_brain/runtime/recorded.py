"""Recorded organs: replay committed ``ToolResult`` fixtures (design 3.3).

Fixture file ``data/demo/recorded/<organ>/<tool>/<name>.json``::

    {"match": {"scenario": "demo-sindh-2022", "args": {...}},
     "authoring": "captured" | "hand_authored",
     "captured_from": {...},
     "result": {...a complete ToolResult...}}

Matching: ``match.scenario`` (if present) must equal the call's fixture set; ``match.args`` is a
deep subset of the call arguments (objects match recursively, lists and scalars must be equal),
or equal to them when ``match.exact`` is true (captured fixtures: a fixture never answers a
call it was not computed for). ``match.run_id_of`` ties a follow-up call (``sensitivity_report``,
``explain_forecast``) to the fixture whose rewritten run id it cites.
The most specific match wins (more matched leaves); ties break by file name. No match returns a
``NOT_FOUND`` ToolResult: a recorded organ never invents a result.

Labelling is done here, from configuration, not from fixture content: ``served_by`` is always
``recorded``, the provenance run id is rewritten to a deterministic per-call id, and the warning
``RECORDED_FIXTURE: ...`` is appended to the stored result. The hash of the fixture's result
before these changes is kept as ``original_sha256``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from stitch_brain.core.evidence import det_uuid, sha256_json
from stitch_brain.paths import repo_root
from stitch_brain.runtime.organs import (
    CallContext,
    CallOutcome,
    OrganHealth,
    ServedBy,
    resource_tool,
)
from stitch_brain.runtime.validate import validate_tool_result
from stitch_common import CONTRACT_VERSION
from stitch_common.provenance import inputs_hash

RECORDED_PREFIX = "RECORDED_FIXTURE"


@dataclass(frozen=True)
class Fixture:
    path: str  # repo-relative, forward slashes
    organ: str
    tool: str
    match_scenario: str | None
    match_args: dict[str, Any]
    authoring: str
    result: dict[str, Any]
    run_id_of: str | None = None  # path of the fixture whose served run id this call cites
    exact: bool = False  # args must equal match.args (captured fixtures)


class FixtureSource(Protocol):
    def fixtures(self, organ: str, tool: str) -> list[Fixture]: ...


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_fixture(path: Path, organ: str, tool: str, rel_root: Path) -> Fixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    match = raw.get("match") or {}
    result = validate_tool_result(organ, tool, raw["result"])
    return Fixture(
        path=_rel(path, rel_root),
        organ=organ,
        tool=tool,
        match_scenario=match.get("scenario"),
        match_args=dict(match.get("args") or {}),
        authoring=str(raw.get("authoring", "hand_authored")),
        result=result,
        run_id_of=match.get("run_id_of"),
        exact=bool(match.get("exact", False)),
    )


class DirectoryFixtureSource:
    """``<root>/<organ>/<tool dir>/*.json``; resource tools use ``resource_<name>`` dirs."""

    def __init__(self, root: Path, rel_root: Path | None = None) -> None:
        self.root = root
        self.rel_root = rel_root if rel_root is not None else repo_root()
        self._cache: dict[tuple[str, str], list[Fixture]] = {}

    @staticmethod
    def tool_dir(tool: str) -> str:
        return tool.replace("resource:", "resource_")

    def fixtures(self, organ: str, tool: str) -> list[Fixture]:
        key = (organ, tool)
        if key not in self._cache:
            d = self.root / organ / self.tool_dir(tool)
            files = sorted(d.glob("*.json")) if d.is_dir() else []
            self._cache[key] = [load_fixture(f, organ, tool, self.rel_root) for f in files]
        return self._cache[key]

    def all_fixtures(self) -> Iterable[Fixture]:
        if not self.root.is_dir():
            return []
        out: list[Fixture] = []
        for organ_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            for tool_dir in sorted(p for p in organ_dir.iterdir() if p.is_dir()):
                tool = tool_dir.name.replace("resource_", "resource:")
                out.extend(self.fixtures(organ_dir.name, tool))
        return out


class TraceFixtureSource:
    """Replays the exact results stored in a trace (design 15). Matched by node and attempt."""

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for c in calls:
            self._by_key[(str(c["node_id"]), int(c["attempt"]))] = c

    def lookup(self, node_id: str, attempt: int) -> dict[str, Any] | None:
        return self._by_key.get((node_id, attempt))


def deep_subset(pattern: Any, value: Any) -> bool:
    if isinstance(pattern, dict):
        return isinstance(value, dict) and all(
            k in value and deep_subset(v, value[k]) for k, v in pattern.items()
        )
    return bool(pattern == value)


MODE_ARG = "mode"


def _leaves(pattern: Any) -> int:
    if isinstance(pattern, dict):
        return sum(_leaves(v) for v in pattern.values())
    return 1


def select(
    fixtures: Iterable[Fixture],
    scenario: str,
    args: dict[str, Any],
    cited_path: str | None = None,
) -> Fixture | None:
    # The requested ``mode`` never selects a fixture: fixtures are recorded demo data and keep
    # their own ``provenance.mode``, so a live request served from fixtures reports demo.
    args = {k: v for k, v in args.items() if k != MODE_ARG}
    best: tuple[int, str] | None = None
    chosen: Fixture | None = None
    for f in fixtures:
        pattern = {k: v for k, v in f.match_args.items() if k != MODE_ARG}
        if f.match_scenario is not None and f.match_scenario != scenario:
            continue
        if f.run_id_of is not None and f.run_id_of != cited_path:
            continue
        if f.exact and pattern != args:
            continue
        if not deep_subset(pattern, args):
            continue
        score = _leaves(pattern) + (1000 if f.match_scenario is not None else 0)
        key = (-score, f.path)
        if best is None or key < best:
            best, chosen = key, f
    return chosen


def label_result(fixture_result: dict[str, Any], source: str, ctx: CallContext) -> dict[str, Any]:
    """Copy, rewrite the run id and append the recorded warning (fixture content cannot remove
    the label: the warning is appended after any warnings the fixture carries)."""
    result = copy.deepcopy(fixture_result)
    prov = dict(result.get("provenance") or {})
    prov["run_id"] = det_uuid(ctx.briefing_id, ctx.node_id, str(ctx.attempt), "recorded")
    result["provenance"] = prov
    warnings = [w for w in result.get("warnings") or [] if isinstance(w, str)]
    warnings.append(f"{RECORDED_PREFIX}: served from {source}, not a live organ call")
    result["warnings"] = warnings
    return result


def not_found(organ: str, tool: str, args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": "NOT_FOUND",
            "message": f"no recorded fixture for {organ}.{tool}",
            "retryable": False,
        },
        "provenance": {
            "organ": organ,
            "tool": tool,
            "tool_version": "recorded",
            "contract_version": CONTRACT_VERSION,
            "run_id": det_uuid(ctx.briefing_id, ctx.node_id, str(ctx.attempt), "recorded"),
            "inputs_hash": inputs_hash(args),
            "mode": "demo",
            "data_sources": [],
            "model": None,
            "models": [],
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "warnings": [f"{RECORDED_PREFIX}: no fixture matched; nothing was invented"],
    }


class RecordedOrgan:
    """An ``OrganClient`` that replays fixtures. ``served_by`` is always ``recorded``."""

    served_by: ServedBy = "recorded"

    def __init__(self, organ: str, source: FixtureSource, tools: Iterable[str]) -> None:
        self.organ = organ
        self.source = source
        self._tools = sorted(tools)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._served: dict[str, str] = {}  # rewritten run id -> fixture path

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[str]:
        return list(self._tools)

    async def call_tool(
        self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: CallContext
    ) -> CallOutcome:
        self.calls.append((tool, args))
        cited = self._served.get(str(args.get("run_id", "")))
        fx = select(self.source.fixtures(self.organ, tool), ctx.scenario, args, cited)
        if fx is None:
            res = not_found(self.organ, tool, args, ctx)
            return CallOutcome(result=res, original_sha256=sha256_json(res), source=None)
        result = label_result(fx.result, fx.path, ctx)
        self._served[str(result["provenance"]["run_id"])] = fx.path
        return CallOutcome(result=result, original_sha256=sha256_json(fx.result), source=fx.path)

    async def read_resource(self, uri: str, *, timeout_s: float, ctx: CallContext) -> CallOutcome:
        return await self.call_tool(resource_tool(uri), {"uri": uri}, timeout_s=timeout_s, ctx=ctx)

    def health(self) -> OrganHealth:
        return OrganHealth(
            organ=self.organ,
            status="ready",
            compat="compatible",
            served_by="recorded",
            tools=list(self._tools),
            connected=True,
            reason="recorded fixtures (stub)",
            last_check=datetime.now(UTC),
        )
