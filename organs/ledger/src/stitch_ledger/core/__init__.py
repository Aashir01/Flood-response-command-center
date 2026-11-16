"""Pure core logic for ledger-mcp: no network, no MCP imports, no global state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stitch_ledger.core.optimize_allocation import run as optimize_allocation
from stitch_ledger.core.sensitivity_report import run as sensitivity_report

CORES: dict[str, Callable[[Any], Any]] = {
    "optimize_allocation": optimize_allocation,
    "sensitivity_report": sensitivity_report,
}
