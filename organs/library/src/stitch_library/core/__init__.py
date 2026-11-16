"""Pure core logic for library-mcp: no network, no MCP imports, no global state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stitch_library.core.answer_with_citations import run as answer_with_citations
from stitch_library.core.search_guidance import run as search_guidance

CORES: dict[str, Callable[[Any], Any]] = {
    "search_guidance": search_guidance,
    "answer_with_citations": answer_with_citations,
}
