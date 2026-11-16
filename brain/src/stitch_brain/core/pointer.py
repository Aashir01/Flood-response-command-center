"""RFC 6901 JSON Pointer: parse, escape, build and resolve (design 4.3). Never raises on bad
input: ``resolve`` returns ``Unresolved(reason)``."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_INDEX = re.compile(r"^(0|[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class Resolved:
    value: Any


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: str


class PointerError(ValueError):
    pass


def escape(token: str | int) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def unescape(token: str) -> str:
    # Order matters (RFC 6901 section 4): ~1 first, then ~0.
    return token.replace("~1", "/").replace("~0", "~")


def pointer_for(path: Sequence[str | int]) -> str:
    """Build a pointer from path segments. Code never concatenates pointers by hand."""
    return "".join("/" + escape(p) for p in path)


def parse(pointer: str) -> list[str]:
    """Return the unescaped tokens. ``""`` is the whole document. Raises ``PointerError``."""
    if not isinstance(pointer, str):
        raise PointerError("pointer must be a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PointerError("pointer must be empty or start with '/'")
    raw = pointer[1:].split("/")
    for tok in raw:
        # "~" must be followed by 0 or 1
        if re.search(r"~(?![01])", tok):
            raise PointerError(f"bad escape in token {tok!r}")
    return [unescape(t) for t in raw]


def resolve(doc: Any, pointer: str) -> Resolved | Unresolved:
    try:
        tokens = parse(pointer)
    except PointerError as exc:
        return Unresolved(str(exc))
    cur = doc
    for i, tok in enumerate(tokens):
        if isinstance(cur, dict):
            if tok not in cur:
                return Unresolved(f"missing key {tok!r} at token {i}")
            cur = cur[tok]
        elif isinstance(cur, list):
            if not _INDEX.match(tok):
                return Unresolved(f"bad array index {tok!r} at token {i}")
            idx = int(tok)
            if idx >= len(cur):
                return Unresolved(f"index {idx} out of range at token {i}")
            cur = cur[idx]
        else:
            return Unresolved(f"cannot traverse a scalar at token {i}")
    return Resolved(cur)


def first_token(pointer: str) -> str | None:
    try:
        toks = parse(pointer)
    except PointerError:
        return None
    return toks[0] if toks else None
