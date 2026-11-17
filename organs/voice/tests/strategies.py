"""Shared Hypothesis strategies for voice tests."""

from __future__ import annotations

from hypothesis import strategies as st

_PIECES = [
    "12,345",
    "3.5",
    "-7",
    "m3/s",
    "m³/s",
    " km2",
    "%",
    "PKR ",
    "2022-08-30",
    "2022-08-30T06:00:00Z",
    "3-5",
    "21st",
    "GloFAS",
    "NDMA",
    "ERA5",
    "Sen1Floods11",
    "Dadu",
    "[1]",
    "https://example.org/x",
    "/data/forecast/3/p50",
    "سکھر",
    "۴۵",
    "پانی",
    "۔",
    "؟",
    ". ",
    ", ",
    "\n",
    "\t",
    "\x07",
    " ",
    "*",
    "mm",
    "1",
    "0.5",
]

mixed_text = st.lists(st.one_of(st.sampled_from(_PIECES), st.text(max_size=6)), max_size=14).map(
    "".join
)
langs = st.sampled_from(["en", "ur"])
