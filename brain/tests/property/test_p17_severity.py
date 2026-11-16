"""Severity mapping and Ledger input (task 13; BRN-P17, BRN-R3.1, R3.3)."""

from __future__ import annotations

from decimal import Decimal

from brain_testkit import world_store
from hypothesis import given
from hypothesis import strategies as st

from stitch_brain.config import SeverityCfg, load_i18n, load_scenarios
from stitch_brain.core.severity import DistrictBase, build_ledger_input, severity_map
from stitch_common.types import EvidenceRef

P = SeverityCfg()


def _d(did: str, pop: int, ra: str, alt: str, ff: str, basin: bool = True) -> DistrictBase:
    return DistrictBase(did, pop, Decimal(ra), Decimal(alt), Decimal(ff), basin)


def test_worked_example_rows_d_and_e() -> None:
    rows = [_d("D", 1_200_000, "0.70", "0.05", "0.18"), _d("E", 500_000, "0.90", "0.00", "0.004")]
    d, e = severity_map(rows, P, Decimal("0.8"), "full")
    assert d.affected_share == Decimal("0.6")
    assert d.population_affected == 720_000
    assert d.severity == Decimal("0.6800") and d.road_access == Decimal("0.4900")
    assert e.affected_share == 0 and e.population_affected == 40_000
    assert e.severity == Decimal("0.2000") and e.road_access == Decimal("0.9000")
    d2, e2 = severity_map(rows, P, Decimal("0.8"), "eyes_only")
    assert e2.population_affected == 0 and e2.severity == 0
    assert d2.population_affected == 720_000


fractions = st.decimals(min_value=0, max_value=1, places=4)
probs = st.decimals(min_value=0, max_value=1, places=3)
districts = st.lists(
    st.tuples(
        st.integers(0, 5_000_000),
        st.decimals(0, 1, places=3),
        st.decimals(0, 1, places=2),
        fractions,
        st.booleans(),
    ),
    min_size=1,
    max_size=8,
)


def _bases(rows: list[tuple[int, Decimal, Decimal, Decimal, bool]]) -> list[DistrictBase]:
    return [DistrictBase(f"d{i}", p, ra, alt, ff, b) for i, (p, ra, alt, ff, b) in enumerate(rows)]


@given(districts, probs)
def test_brn_p17_bounds_and_zero(
    rows: list[tuple[int, Decimal, Decimal, Decimal, bool]], o: Decimal
) -> None:
    bases = _bases(rows)
    for b, m in zip(bases, severity_map(bases, P, o), strict=True):
        assert 0 <= m.severity <= 1 and 0 <= m.road_access <= b.road_access
        assert 0 <= m.population_affected <= b.population
    zero = [
        DistrictBase(
            b.district_id,
            b.population,
            b.road_access,
            b.alt_delivery_fraction,
            Decimal(0),
            b.in_basin,
        )
        for b in bases
    ]
    for m in severity_map(zero, P, Decimal(0)):
        assert m.severity == 0 and m.population_affected == 0


@given(districts, probs, probs, fractions)
def test_brn_p17_monotone_in_flooded_fraction_and_risk(
    rows: list[tuple[int, Decimal, Decimal, Decimal, bool]],
    o1: Decimal,
    o2: Decimal,
    bump: Decimal,
) -> None:
    bases = _bases(rows)
    lo, hi = sorted([o1, o2])
    for a, b in zip(severity_map(bases, P, lo), severity_map(bases, P, hi), strict=True):
        assert a.severity <= b.severity and a.population_affected <= b.population_affected
    more = [
        DistrictBase(
            b.district_id,
            b.population,
            b.road_access,
            b.alt_delivery_fraction,
            min(Decimal(1), b.flooded_fraction + bump),
            b.in_basin,
        )
        for b in bases
    ]
    for a, b in zip(severity_map(bases, P, lo), severity_map(more, P, lo), strict=True):
        assert a.severity <= b.severity and a.population_affected <= b.population_affected


@given(districts, probs, st.randoms(use_true_random=False))
def test_brn_p17_order_invariant(
    rows: list[tuple[int, Decimal, Decimal, Decimal, bool]], o: Decimal, rnd: object
) -> None:
    bases = _bases(rows)
    shuffled = list(bases)
    rnd.shuffle(shuffled)  # type: ignore[attr-defined]
    a = {m.district_id: m for m in severity_map(bases, P, o)}
    b = {m.district_id: m for m in severity_map(shuffled, P, o)}
    assert a == b


def test_lineage_walks_to_organ_entries() -> None:
    store = world_store()
    data = store.by_node("derive.ledger_input").data()
    assert data["severity_mode"] == "full" and data["args"]["districts"]
    organs = set()
    for raw in data["lineage"]:
        ref = EvidenceRef.model_validate(raw)
        assert store.resolves(ref), raw
        organs.add(ref.organ)
    assert organs == {"eyes", "oracle", "ledger"}


def test_missing_eyes_sends_no_override() -> None:
    store = world_store({"eyes.compare": None})
    data = store.by_node("derive.ledger_input").data()
    assert "districts" not in data["args"] and data["severity_mode"] == "defaults"
    assert any("not informed by satellite data" in a for a in data["assumptions"]["en"])


def test_missing_oracle_zeroes_the_forecast_term() -> None:
    sc = load_scenarios()["demo-sindh-2022"]
    store = world_store({"oracle.forecast": None})
    data = build_ledger_input(
        sc,
        eyes_compare=store.ok_node("eyes.compare"),
        oracle_forecast=None,
        districts=store.ok_node("ledger.districts"),
        packs=load_i18n().packs,
    )
    assert data["oracle_risk"] == 0.0
    karachi = next(r for r in data["districts"] if r["district_id"] == "pk-sindh-karachi")
    assert karachi["population_affected"] == 0
