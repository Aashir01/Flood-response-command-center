"""ORA-X4 (SHAP additivity), narrative snapshot and label rules, run store (task 8)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from stitch_oracle.core.bundle import ModelBundle
from stitch_oracle.core.explain import LABELS, allocate, explain, narrative
from stitch_oracle.data.loader import load_demo
from stitch_oracle.store import RunStore

MODELS = Path(__file__).resolve().parents[2] / "models"


# ---------------------------------------------------------------- explain core (ORA-X4)
def test_ora_x4_shap_additivity_on_real_bundle() -> None:
    from stitch_oracle.core.features import build_features

    b = ModelBundle.load(MODELS)
    d = load_demo()
    st = d.catalog.get("indus-guddu")
    assert st is not None
    row = build_features(d.frames, st, date(2022, 8, 20), d.catalog, dict(b.station_codes))
    for lead in (1, 7, 14):
        phi = b.contrib(row.values[None, :], lead)[0]
        raw = b.predict(row.values[None, :])[0, lead - 1, 1]
        assert float(np.sum(phi)) == pytest.approx(raw, abs=1e-6)
        c, base, raw_m3s = allocate(phi, row.q_t)
        assert float(np.sum(c)) == pytest.approx(raw_m3s - base, rel=1e-9, abs=1e-6)
        assert raw_m3s == pytest.approx((row.q_t + 1) * np.exp(raw) - 1, rel=1e-9)


def test_allocate_handles_zero_sum() -> None:
    phi = np.array([0.1, -0.1, 0.0, 0.3])
    c, base, raw = allocate(phi, 99.0)
    assert float(np.sum(c)) == pytest.approx(raw - base, abs=1e-9)
    assert base == pytest.approx(100 * np.exp(0.3) - 1)


def test_narrative_snapshot_and_labels() -> None:
    phi = np.zeros(29)
    phi[8], phi[16], phi[-1] = 0.05, -0.02, 0.01  # up1_rel, rain_1, bias
    from stitch_oracle.core.features import FEATURES

    e = explain(phi, 1000.0, FEATURES, ["Indus near Guddu"])
    text = narrative(
        station_label="GloFAS grid cell nearest to Indus near Sukkur",
        peak_date=date(2022, 8, 20),
        peak_lead=5,
        p50=1040.0,
        lo=900.0,
        hi=1200.0,
        coverage=0.8,
        expl=e,
    )
    assert text.startswith(
        "Modeled river discharge (GloFAS via Open-Meteo) at the GloFAS grid cell nearest to "
        "Indus near Sukkur peaks at lead day 5 (2022-08-20) with a median of 1,040 m3/s "
        "(80% interval 900 to 1,200 m3/s)."
    )
    assert "modeled discharge upstream (Indus near Guddu) relative to this point (+" in text
    assert e.drivers[0].feature == "up1_rel" and e.drivers[0].direction == "up"
    assert e.top_group == "upstream"
    for name, label in LABELS.items():
        if "discharge" in label:
            assert "modeled" in label, name


# ---------------------------------------------------------------- store
def test_store_round_trip_expiry_and_cap() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    s = RunStore(clock=lambda: now[0], max_rows=3)
    s.put("a", "{}", "{}", "{}")
    got = s.get("a")
    assert got is not None and got.extra_json == "{}"
    now[0] += timedelta(hours=47)
    assert s.get("a") is not None
    now[0] += timedelta(hours=2)
    assert s.get("a") is None
    for k in "bcde":
        s.put(k, "{}", "{}", "{}")
    assert s.count() == 3 and s.get("b") is None and s.get("e") is not None
    assert s.writable()
    with pytest.raises(ValueError):
        RunStore(purge_after=timedelta(hours=1))
