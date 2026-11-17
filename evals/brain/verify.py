"""Independent claim verifier for the Brain eval (brain design 17).

This file deliberately shares no code with ``stitch_brain.core`` (no pointer resolver, no
number extractor, no checker). It reads the raw evidence documents of a run (``ToolResult``
JSON by call-level run id), resolves every ``EvidenceRef`` with its own RFC 6901 walk, pulls
numbers out of the claim text with its own small regex, and accepts a number only if it equals
an evidence value at the number's displayed precision. Evidence values are the cited leaves,
their x100 (percentages), and two derived values the Brain's templates use: the sum of the
cited numeric leaves that share a field name, and the count of cited items (``... across 14
other districts``).

A claim passes when every ref resolves, every number is accounted for, every number followed
by a unit is matched by an evidence value whose field or unit agrees, and, for rewritten
statements (``phrased``/``translated``), the judge says entailed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_DIGITS = str.maketrans(
    "".join(chr(c) for c in [*range(0x660, 0x66A), *range(0x6F0, 0x6FA), 0x66B, 0x66C, 0x66A]),
    "0123456789" + "0123456789" + ".,%",
)
# masked before extraction: ISO dates, identifiers containing digits, quantile labels and a few
# named products whose names carry digits
_MASKS = (
    re.compile(r"\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?"),
    re.compile(r"\b[A-Za-z][A-Za-z_]*[-_]?\d[\w-]*"),
    re.compile(r"\bp(?:10|50|90)\b", re.IGNORECASE),
)
#: units are swapped for one-character markers before masking, so ``m3`` is not an identifier
_UNITS = ((re.compile(r"m[³3]/s"), "\x01", "m3/s"), (re.compile(r"km[²2]"), "\x02", "km2"))
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?!\d)|\d+)(\.\d+)?(%?)")
#: unit words after a number -> field-name hints of evidence values that may carry that unit
UNIT_HINTS: dict[str, tuple[str, ...]] = {
    "km2": ("km2", "area"),
    "km²": ("km2", "area"),
    "m3/s": ("m3s", "discharge", "p10", "p50", "p90", "threshold"),
    "m³/s": ("m3s", "discharge", "p10", "p50", "p90", "threshold"),
}
_UNIT_AFTER = re.compile(r"\s?([\x01\x02])")
_MARK = {mark: name for _, mark, name in _UNITS}


@dataclass(frozen=True)
class Num:
    value: Decimal
    decimals: int
    percent: bool
    unit: str | None


def extract_numbers(text: str) -> list[Num]:
    t = text.translate(_DIGITS)
    for pat, mark, _ in _UNITS:
        t = pat.sub(mark, t)
    for mask in _MASKS:
        t = mask.sub(lambda mm: " " * len(mm.group(0)), t)
    out: list[Num] = []
    for m in _NUM.finditer(t):
        whole, frac, pct = m.group(1), m.group(2) or "", m.group(3)
        try:
            v = Decimal(whole.replace(",", "") + frac)
        except InvalidOperation:
            continue
        um = _UNIT_AFTER.match(t, m.end())
        unit = _MARK[um.group(1)] if um else None
        out.append(Num(v, len(frac) - 1 if frac else 0, pct == "%", unit))
    return out


# --- own RFC 6901 walk -------------------------------------------------------------------------
_MISSING = object()


def walk(doc: Any, pointer: str) -> Any:
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        return _MISSING
    cur = doc
    for raw in pointer[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            if tok not in cur:
                return _MISSING
            cur = cur[tok]
        elif isinstance(cur, list):
            if not re.fullmatch(r"0|[1-9]\d*", tok) or int(tok) >= len(cur):
                return _MISSING
            cur = cur[int(tok)]
        else:
            return _MISSING
    return cur


@dataclass(frozen=True)
class Val:
    value: Decimal
    hint: str  # field name, or "text" for numbers inside strings


def _leaves(obj: Any, key: str = "") -> Iterable[Val]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, int | float):
        yield Val(Decimal(repr(obj)), key.lower())
    elif isinstance(obj, str):
        for n in extract_numbers(obj):
            yield Val(n.value, f"text:{n.unit or ''}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v, key)


def allowed_values(values: Sequence[tuple[str, Any]]) -> list[Val]:
    """``values``: (pointer, resolved value) of every cited ref."""
    out: list[Val] = []
    sums: dict[str, Decimal] = {}
    for ptr, v in values:
        leaf_key = ptr.rsplit("/", 1)[-1]
        for lv in _leaves(v, leaf_key):
            out.append(lv)
            out.append(Val(lv.value * 100, lv.hint + ":pct"))
            if not lv.hint.startswith("text"):
                sums[lv.hint] = sums.get(lv.hint, Decimal(0)) + lv.value
    out += [Val(s, f"{k}:sum") for k, s in sums.items()]
    # counts of cited items: all refs, and refs per leaf name ("across 15 other districts")
    per_key: dict[str, int] = {}
    for ptr, _ in values:
        k = ptr.rsplit("/", 1)[-1]
        per_key[k] = per_key.get(k, 0) + 1
    for n in {len(values), *per_key.values()}:
        out.append(Val(Decimal(n), "count"))
    return out


def _matches(n: Num, a: Decimal) -> bool:
    q = Decimal(1).scaleb(-n.decimals)
    for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN):
        try:
            if a.quantize(q, rounding=mode) == n.value:
                return True
        except InvalidOperation:
            return False
    return False


def _unit_ok(n: Num, a: Val) -> bool:
    if n.unit is None:
        return True
    hints = UNIT_HINTS.get(n.unit, ())
    if a.hint.startswith("text:"):
        return a.hint[5:] in (n.unit, n.unit.replace("²", "2"), n.unit.replace("³", "3"), "")
    return any(h in a.hint.replace("/", "").replace("_", "") for h in hints) or a.hint in (
        "value",
        "flooded_km2:sum",
    )


@dataclass
class ClaimVerdict:
    claim_id: str
    kind: str
    provenance_ok: bool
    numbers_ok: bool
    units_ok: bool
    entailed: bool | None
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.provenance_ok and self.numbers_ok and self.units_ok and self.entailed is not False
        )


Judge = Callable[[str, list[str]], bool]


def verify_claim(
    claim: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    text_source: str = "template",
    judge: Judge | None = None,
    reference_texts: Sequence[str] = (),
) -> ClaimVerdict:
    """``reference_texts``: texts the judge may also read (the template rendering of a
    rewritten claim, which is itself verified by the number check)."""
    """``evidence``: run id -> stored ``{organ, tool, result}``."""
    v = ClaimVerdict(str(claim["id"]), str(claim.get("kind")), True, True, True, None)
    resolved: list[tuple[str, Any]] = []
    refs = claim.get("evidence") or []
    if not refs:
        v.provenance_ok = False
        v.problems.append("no evidence")
    for ref in refs:
        e = evidence.get(ref["run_id"])
        if e is None or e["organ"] != ref["organ"] or e["tool"] != ref["tool"]:
            v.provenance_ok = False
            v.problems.append(f"unknown ref {ref['run_id']}")
            continue
        val = walk(e["result"], ref["json_pointer"])
        if val is _MISSING:
            v.provenance_ok = False
            v.problems.append(f"unresolved {ref['json_pointer']}")
            continue
        resolved.append((ref["json_pointer"], val))
    allowed = allowed_values(resolved)
    text = str(claim["text"])
    for n in extract_numbers(text):
        cands = [a for a in allowed if _matches(n, a.value)]
        if n.percent:
            cands = [
                a for a in allowed if a.hint.endswith(":pct") and _matches(n, a.value)
            ] or cands
        if not cands:
            v.numbers_ok = False
            v.problems.append(f"number {n.value} not in evidence")
        elif not any(_unit_ok(n, a) for a in cands):
            v.units_ok = False
            v.problems.append(f"unit {n.unit} after {n.value} not supported")
    if text_source in ("phrased", "translated") and claim.get("kind") == "statement":
        strings = [
            x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for _, x in resolved
        ]
        v.entailed = judge(text, [*strings, *reference_texts]) if judge is not None else None
    return v


_TOK = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
#: function words a rewrite may add without adding meaning
_FUNCTION = frozenset(
    {"the", "and", "was", "were", "are", "with", "being", "been", "has", "have", "had", "for"}
    | {"from", "this", "that", "its", "into", "over", "across", "about", "per", "each"}
    | {"which", "while", "when", "there", "their", "than", "then", "also"}
)


def lexical_judge(text: str, sources: list[str], threshold: float = 0.6) -> bool:
    """Offline proxy (``judge=lexical_proxy``): share of the claim's content words that appear
    in the evidence strings."""
    toks = [t.lower() for t in _TOK.findall(text) if t.lower() not in _FUNCTION]
    if not toks:
        return True
    pool = {t.lower() for s in sources for t in _TOK.findall(s)}
    return sum(t in pool for t in toks) / len(toks) >= threshold


__all__ = [
    "ClaimVerdict",
    "Num",
    "allowed_values",
    "extract_numbers",
    "lexical_judge",
    "verify_claim",
    "walk",
]
