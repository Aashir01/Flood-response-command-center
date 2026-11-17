"""Record Open-Meteo responses for the Oracle live-mode tests (dev-time, needs the network).

    uv run python scripts/record_oracle_live_fixture.py

Calls ``OpenMeteoLive`` once for Indus near Sukkur and its upstream cells (2 requests) and writes
the raw JSON responses plus the recording date to
``organs/oracle/tests/fixtures/live_openmeteo.json``. Tests replay this file with sockets
disabled. Data: modeled GloFAS discharge (Open-Meteo Flood API) and forecast-model rain and
temperature (Open-Meteo Forecast API), CC BY 4.0, "Weather data by Open-Meteo.com".
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "organs" / "oracle" / "src"))

from stitch_oracle.data.loader import load_demo  # noqa: E402
from stitch_oracle.live import OpenMeteoLive, http_get_json  # noqa: E402

OUT = REPO / "organs" / "oracle" / "tests" / "fixtures" / "live_openmeteo.json"
STATIONS = ["indus-sukkur", "indus-guddu", "indus-taunsa"]


def main() -> int:
    calls: list[dict[str, Any]] = []

    def record(url: str, params: dict[str, str]) -> Any:
        resp = http_get_json(url, params)
        calls.append({"url": url, "params": params, "response": resp})
        return resp

    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory() as tmp:
        OpenMeteoLive(Path(tmp), fetch=record, now=lambda: now).frames(STATIONS, load_demo())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "recorded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stations": STATIONS,
        "attribution": "Weather data by Open-Meteo.com (CC BY 4.0); GloFAS (Copernicus/ECMWF)",
        "calls": calls,
    }
    OUT.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size} bytes, {len(calls)} calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
