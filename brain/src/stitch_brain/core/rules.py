"""Declarative conflict rules (design 9.2): a typed AST loaded from YAML and evaluated by a
recursive function. There is no dynamic code execution of any kind here: rules can only name
facts from ``facts.FACTS``, params from the rule file and numeric constants.

Grammar::

    when    := {all: [when]} | {any: [when]} | {not: when} | cmp
    cmp     := {lt|lte|gt|gte|eq|ne: [operand, operand]}
             | {rel_diff_gt: [operand, operand, operand]}
    operand := <fact alias> | {param: name} | {const: number}
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from stitch_brain.core.facts import FACTS, Fact, FactCtx, Unavailable
from stitch_common.types import EvidenceRef

CMP_OPS = ("lt", "lte", "gt", "gte", "eq", "ne")
ALL_OPS = (*CMP_OPS, "rel_diff_gt")


class RuleConfigError(ValueError):
    pass


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Param(_M):
    param: str


class Const(_M):
    const: float


Operand = Union[str, Param, Const]  # noqa: UP007 - pydantic recursive union


class Cmp(_M):
    lt: list[Operand] | None = None
    lte: list[Operand] | None = None
    gt: list[Operand] | None = None
    gte: list[Operand] | None = None
    eq: list[Operand] | None = None
    ne: list[Operand] | None = None
    rel_diff_gt: list[Operand] | None = None

    @model_validator(mode="after")
    def _one_op(self) -> Cmp:
        set_ops = [k for k in ALL_OPS if self.__dict__[k] is not None]
        if len(set_ops) != 1:
            raise ValueError("a comparison has exactly one operator")
        args = self.__dict__[set_ops[0]]
        arity = 3 if set_ops[0] == "rel_diff_gt" else 2
        if len(args) != arity:
            raise ValueError(f"{set_ops[0]} takes {arity} operands")
        return self

    @property
    def op(self) -> str:
        return next(k for k in ALL_OPS if self.__dict__[k] is not None)

    @property
    def args(self) -> list[Operand]:
        a: list[Operand] = self.__dict__[self.op]
        return a


class All(_M):
    all: list[When] = Field(min_length=1)


class AnyOf(_M):
    any: list[When] = Field(min_length=1)


class Not(_M):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    not_: When = Field(alias="not")


When = Union[All, AnyOf, Not, Cmp]  # noqa: UP007


class Reconcile(_M):
    action: Literal["rerun_ledger"]
    severity_source: Literal["eyes_only"]
    max_times: int = Field(default=1, ge=1, le=1)


class Rule(_M):
    id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    severity: Literal["low", "medium", "high"]
    organs: list[str]
    foreach: str | None = None
    facts: dict[str, str]
    when: When
    affects: list[str]
    describe: str
    display: dict[str, Literal["pct", "dec", "int"]] = Field(default_factory=dict)
    reconcile: Reconcile | None = None


class RuleSet(_M):
    version: Literal[1]
    params: dict[str, float]
    rules: list[Rule]


for _m in (All, AnyOf, Not):
    _m.model_rebuild()


def rules_json_schema() -> dict[str, Any]:
    return RuleSet.model_json_schema(by_alias=True)


# --- loading and static checks -----------------------------------------------------------------
def _operands(w: When) -> list[Operand]:
    if isinstance(w, All):
        return [o for x in w.all for o in _operands(x)]
    if isinstance(w, AnyOf):
        return [o for x in w.any for o in _operands(x)]
    if isinstance(w, Not):
        return _operands(w.not_)
    return list(w.args)


def check_ruleset(rs: RuleSet) -> RuleSet:
    ids = [r.id for r in rs.rules]
    if len(set(ids)) != len(ids):
        raise RuleConfigError("duplicate rule ids")
    for r in rs.rules:
        for alias, fact in r.facts.items():
            spec = FACTS.get(fact)
            if spec is None:
                raise RuleConfigError(f"{r.id}: unknown fact {fact}")
            if spec.kind == "keyed" and spec.key != r.foreach:
                raise RuleConfigError(f"{r.id}: keyed fact {alias} needs foreach: {spec.key}")
        if r.foreach is not None and not any(FACTS[f].kind == "keyed" for f in r.facts.values()):
            raise RuleConfigError(f"{r.id}: foreach without a keyed fact")
        for o in _operands(r.when):
            if isinstance(o, str) and o not in r.facts:
                raise RuleConfigError(f"{r.id}: operand {o!r} is not a fact alias")
            if isinstance(o, Param) and o.param not in rs.params:
                raise RuleConfigError(f"{r.id}: undefined param {o.param}")
    return rs


def parse_ruleset(raw: Any) -> RuleSet:
    try:
        rs = RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RuleConfigError(str(exc).splitlines()[0]) from exc
    return check_ruleset(rs)


def load_ruleset_text(text: str) -> RuleSet:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuleConfigError(f"invalid YAML: {type(exc).__name__}") from exc
    return parse_ruleset(raw)


# --- evaluation --------------------------------------------------------------------------------
def _value(o: Operand, env: Mapping[str, Decimal], params: Mapping[str, float]) -> Decimal:
    if isinstance(o, str):
        return env[o]
    if isinstance(o, Param):
        return Decimal(repr(params[o.param]))
    return Decimal(repr(o.const))


def eval_when(w: When, env: Mapping[str, Decimal], params: Mapping[str, float]) -> bool:
    if isinstance(w, All):
        return all(eval_when(x, env, params) for x in w.all)
    if isinstance(w, AnyOf):
        return any(eval_when(x, env, params) for x in w.any)
    if isinstance(w, Not):
        return not eval_when(w.not_, env, params)
    vals = [_value(o, env, params) for o in w.args]
    op = w.op
    if op == "rel_diff_gt":
        a, b, tol = vals
        m = max(abs(a), abs(b))
        return m != 0 and abs(a - b) / m > tol
    a, b = vals
    return {
        "lt": a < b,
        "lte": a <= b,
        "gt": a > b,
        "gte": a >= b,
        "eq": a == b,
        "ne": a != b,
    }[op]


@dataclass
class RuleOutcome:
    rule: Rule
    fired: bool = False
    skipped: str | None = None
    subjects: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    values: dict[str, dict[str, Decimal]] = field(default_factory=dict)  # subject -> alias -> v
    refs: list[EvidenceRef] = field(default_factory=list)


def evaluate_rule(rule: Rule, ctx: FactCtx, params: Mapping[str, float]) -> RuleOutcome:
    out = RuleOutcome(rule)
    resolved: dict[str, Any] = {}
    for alias, fact in rule.facts.items():
        v = FACTS[fact].fn(ctx)
        if isinstance(v, Unavailable):
            out.skipped = f"{alias} ({fact}): {v.reason}"
            return out
        resolved[alias] = v
    keyed = {a: v for a, v in resolved.items() if isinstance(v, dict)}
    if rule.foreach is None:
        keys: list[str | None] = [None]
    else:
        common = set.intersection(*(set(v) for v in keyed.values())) if keyed else set()
        keys = list(sorted(common))
    for k in keys:
        env: dict[str, Decimal] = {}
        facts_for_key: list[Fact] = []
        for alias, v in resolved.items():
            f = v[k] if isinstance(v, dict) and k is not None else v
            assert isinstance(f, Fact)
            env[alias] = f.value
            facts_for_key.append(f)
        if eval_when(rule.when, env, params):
            out.fired = True
            subject = k or rule.id
            out.subjects.append(subject)
            out.values[subject] = dict(env)
            label = next((f.label for f in facts_for_key if f.label), None)
            out.labels[subject] = label or subject
            for f in facts_for_key:
                for r in f.refs:
                    if r not in out.refs:
                        out.refs.append(r)
    return out


def evaluate(rs: RuleSet, ctx: FactCtx) -> list[RuleOutcome]:
    return [evaluate_rule(r, ctx, rs.params) for r in rs.rules]


__all__ = [
    "Cmp",
    "Const",
    "Param",
    "Rule",
    "RuleConfigError",
    "RuleOutcome",
    "RuleSet",
    "Unavailable",
    "eval_when",
    "evaluate",
    "load_ruleset_text",
    "parse_ruleset",
    "rules_json_schema",
]
