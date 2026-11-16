"""Shared renderer helpers: the render context, slot constructors and claim building.

Text is a deterministic function of (pattern, slot values, language). Numbers are formatted by
``numbers.format_number``; patterns contain no digits, so every digit comes from a slot.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property
from typing import Any

from stitch_brain.config import I18n, ScenarioCfg
from stitch_brain.core.claims import ClaimDraft, DerivationCall, Fmt, Kind, SectionId, Slot
from stitch_brain.core.derive import DERIVATIONS
from stitch_brain.core.evidence import EvidenceEntry, EvidenceStore
from stitch_brain.core.numbers import UnitTable, format_number, to_decimal
from stitch_brain.core.pointer import pointer_for
from stitch_brain.core.textfmt import render
from stitch_common.types import EvidenceRef


@dataclass
class RenderCtx:
    store: EvidenceStore
    scenario: ScenarioCfg
    i18n: I18n
    lang: str = "en"
    digits: str = "ascii"
    #: node ids whose evidence entry should be read (``ledger.final`` alias is resolved by the
    #: store); filled by the runner
    node_status: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)  # renderer-level drops, for the critic notes

    def ok(self, node_id: str) -> EvidenceEntry | None:
        return self.store.ok_node(node_id)

    def any_entry(self, node_id: str) -> EvidenceEntry | None:
        return self.store.by_node(node_id)

    @cached_property
    def units(self) -> UnitTable:
        return UnitTable(self.i18n.unit_aliases())

    def pattern(self, template_id: str) -> str:
        return self.i18n.pattern(template_id, self.lang)

    def table(self, name: str) -> dict[str, str]:
        return self.i18n.pack(self.lang).tables.get(name, {})


def get_path(entry: EvidenceEntry, path: Sequence[str | int]) -> Any:
    cur: Any = entry.result
    for p in path:
        cur = cur[p]
    return cur


def leaf(
    name: str,
    entry: EvidenceEntry,
    path: Sequence[str | int],
    fmt: Fmt,
    *,
    decimals: int | None = None,
    unit: str | None = None,
) -> Slot:
    """A slot whose value is the resolved evidence leaf at ``path``."""
    raw = get_path(entry, path)
    value: Decimal | str
    if fmt in ("int", "dec", "pct"):
        value = to_decimal(raw)
    elif fmt == "date":
        value = str(raw)[:10]
    else:
        value = str(raw)
    return Slot(
        name=name,
        value=value,
        unit=unit,
        decimals=decimals if fmt != "int" else 0,
        fmt=fmt,
        refs=[entry.ref(pointer_for(list(path)))],
    )


def derived(
    name: str,
    refs: list[EvidenceRef],
    values: Sequence[Any],
    fn: str,
    fmt: Fmt,
    *,
    params: Mapping[str, str] | None = None,
    decimals: int | None = None,
    unit: str | None = None,
) -> Slot:
    """A slot computed by a named derivation over the values at ``refs`` (same order)."""
    p = dict(params or {})
    value = DERIVATIONS[fn](list(values), **p)
    return Slot(
        name=name,
        value=value,
        unit=unit,
        decimals=decimals if fmt != "int" else 0,
        fmt=fmt,
        refs=refs,
        derivation=DerivationCall(fn=fn, params=p),
    )


def lookup_slot(
    name: str, entry: EvidenceEntry, path: Sequence[str | int], table: str, lang: str
) -> Slot:
    raw = get_path(entry, path)
    return derived(
        name,
        [entry.ref(pointer_for(list(path)))],
        [raw],
        "lookup",
        "text",
        params={"table": table, "lang": lang},
    )


def sig_decimals(value: Decimal, sig: int = 3) -> int:
    """Display decimals for about ``sig`` significant figures (0 to 6)."""
    v = abs(float(value))
    if v == 0:
        return 0
    return max(0, min(6, sig - 1 - math.floor(math.log10(v))))


def display(slot: Slot, lang: str, digits: str = "ascii") -> str:
    if slot.fmt in ("int", "dec", "pct"):
        assert isinstance(slot.value, Decimal)
        return format_number(slot.value, slot.fmt, slot.decimals, lang, digits)  # type: ignore[arg-type]
    return str(slot.value)


def fill(ctx: RenderCtx, template_id: str, slots: Mapping[str, Slot], **extra: str) -> str:
    values = {k: display(s, ctx.lang, ctx.digits) for k, s in slots.items()}
    values.update(extra)
    return render(ctx.pattern(template_id), values)


def claim(
    ctx: RenderCtx,
    *,
    cid: str,
    section: SectionId,
    kind: Kind,
    template_id: str,
    slots: Mapping[str, Slot],
    order: int,
    extra_refs: Iterable[EvidenceRef] = (),
    text: str | None = None,
    verbatim: bool = False,
) -> ClaimDraft:
    rendered = text if text is not None else fill(ctx, template_id, slots)
    evidence: list[EvidenceRef] = [r for s in slots.values() for r in s.refs]
    evidence += list(extra_refs)
    return ClaimDraft(
        id=cid,
        section=section,
        kind=kind,
        template_id=template_id,
        slots=dict(slots),
        evidence=evidence,
        verbatim=verbatim,
        text={ctx.lang: rendered},
        final_text=rendered,
        text_source="verbatim" if verbatim else "template",
        order=order,
    )


def find_index(items: Sequence[Mapping[str, Any]], key: str, value: Any) -> int | None:
    for i, it in enumerate(items):
        if it.get(key) == value:
            return i
    return None
