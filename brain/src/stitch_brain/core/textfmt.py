"""Restricted formatter for i18n patterns: only ``{name}`` fields, ``{{`` and ``}}`` escapes.
No attribute access, indexing, conversions or format specs (so a pattern is data, not code)."""

from __future__ import annotations

import re
from collections.abc import Mapping

_FIELD = re.compile(r"\{\{|\}\}|\{([a-z][a-z0-9_]*)\}|\{|\}")


class PatternError(ValueError):
    pass


def fields(pattern: str) -> list[str]:
    out: list[str] = []
    for m in _FIELD.finditer(pattern):
        tok = m.group(0)
        if tok in ("{{", "}}"):
            continue
        if m.group(1) is None:
            raise PatternError(f"bad field syntax near {pattern[m.start() : m.start() + 12]!r}")
        out.append(m.group(1))
    return out


def render(pattern: str, values: Mapping[str, str]) -> str:
    fields(pattern)  # validates

    def sub(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        name = m.group(1)
        if name is None or name not in values:
            raise PatternError(f"missing value for field {name!r}")
        return values[name]

    return _FIELD.sub(sub, pattern)


def literal_text(pattern: str) -> str:
    """The pattern with every field removed (used by the pattern linter)."""
    return _FIELD.sub(" ", pattern)
