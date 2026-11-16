"""The envelope invariant (BOOT-P1) holds for any arguments, and every successful
``forecast_river`` result carries the modeled label (ORA-P8) for random valid requests."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_common.organs.oracle import TARGET_LABEL
from stitch_common.tooling import run_tool
from stitch_oracle.models import TOOL_NAMES
from stitch_oracle.service import OracleService
from stitch_oracle.store import RunStore

SVC = OracleService(store=RunStore())
CORES = SVC.cores()
STATIONS = ("chenab-trimmu", "indus-taunsa", "indus-guddu", "indus-sukkur", "indus-kotri")

arguments = st.dictionaries(
    st.text(max_size=8),
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    max_size=5,
)


@given(arguments)
def test_envelope_invariant_for_arbitrary_arguments(args: dict[str, Any]) -> None:
    for tool in TOOL_NAMES:
        result = asyncio.run(run_tool("oracle", tool, "0.2.0", CORES[tool], args))
        assert result.ok == (result.data is not None and result.error is None)
        assert result.ok or result.error is not None


@st.composite
def valid_requests(draw: st.DrawFn) -> dict[str, Any]:
    as_of = date(2017, 1, 1) + timedelta(days=draw(st.integers(0, 2555)))
    req: dict[str, Any] = {
        "station_id": draw(st.sampled_from(STATIONS)),
        "horizon_days": draw(st.integers(1, 14)),
        "as_of": as_of.isoformat(),
    }
    if draw(st.booleans()):
        req["coverage"] = draw(st.floats(0.5, 0.99))
    return req


@settings(deadline=None, max_examples=25)
@given(valid_requests())
def test_ora_p8_every_forecast_is_labelled_modeled(req: dict[str, Any]) -> None:
    r = asyncio.run(run_tool("oracle", "forecast_river", "0.2.0", CORES["forecast_river"], req))
    assert r.ok and r.data is not None
    assert r.data.target_kind == "modeled_glofas"
    assert r.data.target_label == TARGET_LABEL
    for p in r.data.forecast:
        assert 0 <= p.discharge.p10 <= p.discharge.p50 <= p.discharge.p90
    for w in r.warnings:
        assert "gauge" not in w.lower() and "observed" not in w.lower()
