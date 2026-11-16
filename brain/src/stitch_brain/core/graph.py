"""Plan model and validation (design 7.2, BRN-P5). A plan is data: node arguments come from
argument builders registered by name, never from expressions in the plan."""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NodeKind = Literal["organ", "resource", "derive", "analysis", "synthesis", "llm"]
MAX_NODES = 24
MAX_DEPTH = 8  # edges on the longest path


class Dep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    need: Literal["hard", "soft"] = "hard"


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9_.]+$")
    kind: NodeKind
    organ: str | None = None
    tool: str | None = None
    builder: str
    params: dict[str, str] = Field(default_factory=dict)
    deps: list[Dep] = Field(default_factory=list)
    optional: bool = False
    timeout_s: float = Field(default=10.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=3)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    scenario: str
    revision: int = 1
    planner: Literal["default", "llm"] = "default"
    nodes: list[Node]

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def ids(self) -> list[str]:
        return [n.id for n in self.nodes]


class PlanError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def find_problems(
    plan: Plan,
    builders: Collection[str],
    available: Collection[tuple[str, str]] | None = None,
) -> list[str]:
    problems: list[str] = []
    ids = [n.id for n in plan.nodes]
    if len(ids) > MAX_NODES:
        problems.append(f"too many nodes ({len(ids)} > {MAX_NODES})")
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            problems.append(f"duplicate node id {i}")
        seen.add(i)
    for n in plan.nodes:
        if n.builder not in builders:
            problems.append(f"{n.id}: unregistered builder {n.builder}")
        for d in n.deps:
            if d.id == n.id:
                problems.append(f"{n.id}: depends on itself")
            elif d.id not in seen:
                problems.append(f"{n.id}: unknown dependency {d.id}")
        if n.kind in ("organ", "resource"):
            if not n.organ or not n.tool:
                problems.append(f"{n.id}: organ and tool are required")
            elif available is not None and (n.organ, n.tool) not in available:
                problems.append(f"{n.id}: {n.organ}.{n.tool} is not available")
    if problems:
        return problems
    levels = _levels(plan)
    if levels is None:
        return ["the graph has a cycle"]
    if len(levels) - 1 > MAX_DEPTH:
        problems.append(f"graph depth {len(levels) - 1} exceeds {MAX_DEPTH}")
    return problems


def validate_plan(
    plan: Plan,
    builders: Collection[str],
    available: Collection[tuple[str, str]] | None = None,
) -> Plan:
    problems = find_problems(plan, builders, available)
    if problems:
        raise PlanError(problems)
    return plan


def _levels(plan: Plan) -> list[list[str]] | None:
    """Kahn's algorithm by levels. ``None`` when there is a cycle."""
    indeg = {n.id: 0 for n in plan.nodes}
    children: dict[str, list[str]] = {n.id: [] for n in plan.nodes}
    for n in plan.nodes:
        for d in {d.id for d in n.deps}:
            indeg[n.id] += 1
            children[d].append(n.id)
    level = sorted(i for i, k in indeg.items() if k == 0)
    out: list[list[str]] = []
    done = 0
    while level:
        out.append(level)
        done += len(level)
        nxt: list[str] = []
        for i in level:
            for c in children[i]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    nxt.append(c)
        level = sorted(nxt)
    return out if done == len(plan.nodes) else None


def topological_levels(plan: Plan) -> list[list[str]]:
    levels = _levels(plan)
    if levels is None:
        raise PlanError(["the graph has a cycle"])
    return levels
