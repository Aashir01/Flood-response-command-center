"""Per-briefing evidence store (design section 4).

Every organ ``ToolResult`` (and every Brain-origin derived value) is stored as an
``EvidenceEntry`` before anything reads it. Claims cite entries with ``EvidenceRef``s whose
``run_id`` is the call-level id and whose ``json_pointer`` points into ``entry.result``.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from stitch_brain.core.pointer import Resolved, Unresolved, first_token, resolve
from stitch_common.provenance import canonical_json
from stitch_common.types import EvidenceRef

ServedBy = Literal["real", "recorded", "brain"]
FAILED_ROOTS = frozenset({"error", "provenance", "warnings", "ok"})
BRAIN_TOOL_VERSION = "0.1.0"


def det_uuid(*parts: str) -> str:
    """Deterministic id shaped like a uuid4 (version and variant bits set), so it also passes
    the contract ``Provenance.run_id`` pattern. Used for recorded and Brain-origin entries."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


class EvidenceError(ValueError):
    pass


class EvidenceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_run_id: str
    briefing_id: str
    node_id: str
    organ: str
    tool: str
    served_by: ServedBy
    attempt: int = 1
    started_at: datetime
    ended_at: datetime
    duration_ms: int = 0
    result: dict[str, Any]
    original_sha256: str
    source: str | None = None  # fixture path for recorded entries

    @property
    def ok(self) -> bool:
        return bool(self.result.get("ok"))

    @property
    def mode(self) -> str:
        prov = self.result.get("provenance") or {}
        mode = prov.get("mode")
        return mode if mode in ("demo", "live") else "demo"

    def data(self) -> dict[str, Any]:
        d = self.result.get("data")
        return d if isinstance(d, dict) else {}

    def ref(self, pointer: str) -> EvidenceRef:
        return EvidenceRef(
            run_id=self.call_run_id, organ=self.organ, tool=self.tool, json_pointer=pointer
        )


def canonical_key(e: EvidenceEntry) -> tuple[str, int, str]:
    return (e.node_id, e.attempt, e.call_run_id)


def _check_finite(obj: Any, path: str = "") -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise EvidenceError(f"non-finite number at {path or '/'}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_finite(v, f"{path}/{i}")


@dataclass(frozen=True, slots=True)
class ResolvedRef:
    value: Any
    entry: EvidenceEntry


class EvidenceStore:
    """In-memory store for one briefing. JSON round-trip safe (BRN-P8)."""

    def __init__(self, briefing_id: str = "") -> None:
        self.briefing_id = briefing_id
        self._entries: dict[str, EvidenceEntry] = {}
        self._order: list[str] = []
        self._aliases: dict[str, str] = {}

    # --- writes ------------------------------------------------------------------------------
    def put(self, entry: EvidenceEntry) -> EvidenceEntry:
        _check_finite(entry.result)
        if entry.call_run_id in self._entries:
            existing = self._entries[entry.call_run_id]
            if existing.node_id != entry.node_id or existing.result != entry.result:
                raise EvidenceError(f"duplicate call_run_id {entry.call_run_id}")
            return existing
        self._entries[entry.call_run_id] = entry
        self._order.append(entry.call_run_id)
        return entry

    def alias(self, name: str, call_run_id: str) -> None:
        if call_run_id not in self._entries:
            raise EvidenceError(f"unknown call_run_id {call_run_id}")
        self._aliases[name] = call_run_id

    # --- reads -------------------------------------------------------------------------------
    def get(self, call_run_id: str) -> EvidenceEntry | None:
        return self._entries.get(call_run_id)

    def by_node(self, node_id: str) -> EvidenceEntry | None:
        """Latest attempt of ``node_id`` (or the aliased entry)."""
        if node_id in self._aliases:
            return self._entries[self._aliases[node_id]]
        found: EvidenceEntry | None = None
        for rid in self._order:
            e = self._entries[rid]
            if e.node_id == node_id and (found is None or e.attempt >= found.attempt):
                found = e
        return found

    def ok_node(self, node_id: str) -> EvidenceEntry | None:
        e = self.by_node(node_id)
        return e if e is not None and e.ok else None

    def entries(self) -> Iterator[EvidenceEntry]:
        for rid in self._order:
            yield self._entries[rid]

    def canonical_entries(self) -> list[EvidenceEntry]:
        """Entries in a completion-order-independent order (node id, attempt, run id).

        ``entries()`` follows insertion order, which is the order calls *finished* in. Anything
        rendered into a briefing must use this order instead, or concurrent organ timing leaks
        into the output (BRN-P4)."""
        return sorted(self._entries.values(), key=canonical_key)

    def __len__(self) -> int:
        return len(self._entries)

    def resolve(self, ref: EvidenceRef) -> ResolvedRef | Unresolved:
        entry = self._entries.get(ref.run_id)
        if entry is None:
            return Unresolved("unknown run_id")
        if entry.organ != ref.organ or entry.tool != ref.tool:
            return Unresolved("organ or tool mismatch")
        if not entry.ok:
            root = first_token(ref.json_pointer)
            if root not in FAILED_ROOTS:
                return Unresolved(
                    "a failed entry resolves only into /error, /provenance, /warnings"
                )
        res = resolve(entry.result, ref.json_pointer)
        if isinstance(res, Resolved):
            return ResolvedRef(res.value, entry)
        return res

    def resolves(self, ref: EvidenceRef) -> bool:
        return isinstance(self.resolve(ref), ResolvedRef)

    def value(self, ref: EvidenceRef) -> Any:
        res = self.resolve(ref)
        if isinstance(res, Unresolved):
            raise EvidenceError(f"unresolved {ref.json_pointer}: {res.reason}")
        return res.value

    # --- serialization -----------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {
            "briefing_id": self.briefing_id,
            "entries": [self._entries[r].model_dump(mode="json") for r in self._order],
            "aliases": dict(self._aliases),
        }

    def dumps(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> EvidenceStore:
        store = cls(str(obj.get("briefing_id", "")))
        for raw in obj.get("entries", []):
            store.put(EvidenceEntry.model_validate(raw))
        for name, rid in (obj.get("aliases") or {}).items():
            store.alias(name, rid)
        return store

    @classmethod
    def loads(cls, text: str) -> EvidenceStore:
        return cls.from_json(json.loads(text))


def brain_entry(
    *,
    briefing_id: str,
    node_id: str,
    tool: str,
    data: dict[str, Any],
    at: datetime | None = None,
    warnings: Iterable[str] = (),
    mode: str = "demo",
) -> EvidenceEntry:
    """A Brain-origin entry (design 4.4): ``organ = served_by = "brain"``, deterministic id."""
    at = at or datetime.now(UTC)
    rid = det_uuid(briefing_id, node_id, tool)
    result = {
        "ok": True,
        "data": data,
        "error": None,
        "provenance": {
            "organ": "brain",
            "tool": tool,
            "tool_version": BRAIN_TOOL_VERSION,
            "run_id": rid,
            "mode": mode,
            "generated_at": at.isoformat(),
        },
        "warnings": list(warnings),
    }
    return EvidenceEntry(
        call_run_id=rid,
        briefing_id=briefing_id,
        node_id=node_id,
        organ="brain",
        tool=tool,
        served_by="brain",
        attempt=1,
        started_at=at,
        ended_at=at,
        duration_ms=0,
        result=result,
        original_sha256=sha256_json(result),
    )
