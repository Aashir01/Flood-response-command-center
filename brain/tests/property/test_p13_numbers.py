"""BRN-P13: number formatting and extraction round-trip in en, ur/ascii and ur/extended."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given
from hypothesis import strategies as st

from stitch_brain.core.numbers import extract_values, format_number, to_extended

values = st.decimals(min_value=-(10**9), max_value=10**9, allow_nan=False, places=4)


@given(values, st.integers(0, 3), st.sampled_from(["en", "ur-ascii", "ur-extended"]))
def test_brn_p13_round_trip(v: Decimal, k: int, variant: str) -> None:
    lang = "en" if variant == "en" else "ur"
    digits = "extended" if variant == "ur-extended" else "ascii"
    fmt = "int" if k == 0 else "dec"
    text = format_number(v, fmt, k, lang, digits)  # type: ignore[arg-type]
    expected = v.quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_UP)
    got = extract_values(f"x {text} y")
    assert got == [expected] or (expected == 0 and got == [Decimal(0)])


@given(st.integers(0, 10**9), st.integers(0, 3))
def test_brn_p13_digit_systems_extract_identically(n: int, k: int) -> None:
    text = format_number(Decimal(n) / 7, "dec" if k else "int", k)
    assert extract_values(text) == extract_values(to_extended(text))
