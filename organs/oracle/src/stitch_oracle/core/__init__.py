"""Pure core logic for oracle-mcp: no network, no MCP imports, no global state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stitch_oracle.core.explain_forecast import run as explain_forecast
from stitch_oracle.core.forecast_river import run as forecast_river

CORES: dict[str, Callable[[Any], Any]] = {
    "forecast_river": forecast_river,
    "explain_forecast": explain_forecast,
}
