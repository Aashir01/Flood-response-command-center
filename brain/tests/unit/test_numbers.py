# ruff: noqa: RUF001
"""Number normalization, extraction, matching, units and formatting (task 4; BRN-R5.2, R6.1).
One named test per rejection class."""

from __future__ import annotations

from decimal import Decimal

from stitch_brain.core.numbers import (
    SlotSpec,
    UnitTable,
    check_text,
    extract_values,
    format_number,
    language_ok,
    normalize_digits,
    scan,
)
from stitch_brain.core.textfmt import PatternError, fields, render

UNITS = UnitTable(
    {
        "km2": ["km2", "km²", "square kilometres", "مربع کلومیٹر"],
        "m3/s": ["m3/s", "m³/s", "cubic metres per second", "مکعب میٹر فی سیکنڈ"],
        "people": ["people", "افراد"],
        "litre": ["litres", "لیٹر"],
    }
)
AREA = SlotSpec("area", Decimal("1234.4"), "km2", 0, "int")
FLOW = SlotSpec("flow", Decimal("8123.6"), "m3/s", 0, "int")
PEOPLE = SlotSpec("people", Decimal("720000"), "people", 0, "int")
PCT = SlotSpec("p", Decimal("0.8123"), None, 0, "pct")
COUNT = SlotSpec("n", Decimal("3"), None, 0, "int")


def _kinds(text: str, *slots: SlotSpec, **kw: object) -> list[str]:
    return [i.kind for i in check_text(text, list(slots), UNITS, **kw)]  # type: ignore[arg-type]


def test_template_text_passes() -> None:
    assert _kinds("New flood water covers 1,234 km2 in 3 districts.", AREA, COUNT) == []


def test_new_number_rejected() -> None:
    assert "new_number" in _kinds("Covers 1,234 km2 and 99 more.", AREA)


def test_scaled_number_rejected() -> None:
    assert "new_number" in _kinds("Covers 12,344 km2.", AREA)


def test_dropped_slot_rejected() -> None:
    assert _kinds("Covers a large area.", AREA) == ["dropped_slot"]


def test_unit_missing_rejected() -> None:
    assert _kinds("Covers 1,234 of land.", AREA) == ["unit_missing"]


def test_swapped_units_rejected() -> None:
    kinds = _kinds("Covers 1,234 m3/s and flows 8,124 km2.", AREA, FLOW)
    assert kinds.count("unit_swapped") == 2


def test_unit_after_count_rejected() -> None:
    assert _kinds("In 3 km2 districts.", COUNT) == ["unit_on_count"]


def test_extra_decimals_rejected() -> None:
    assert "new_number" in _kinds("Covers 1,234.40 km2.", AREA) or "new_number" in _kinds(
        "Covers 1,234.41 km2.", AREA
    )
    # more precise than displayed must equal the unrounded value exactly
    assert _kinds("Covers 1,234.4 km2.", AREA) == []


def test_number_words_and_scale_words_rejected() -> None:
    assert "new_number" in _kinds("Covers 1,234 km2 for seven days.", AREA)
    assert "scale_word" in _kinds("Send to 720000 people, about seven lakh.", PEOPLE)
    assert "scale_word" in _kinds("720000 افراد یعنی سات لاکھ", PEOPLE)


def test_arabic_indic_digits_are_the_same_numbers() -> None:
    assert _kinds("۷۲۰٬۰۰۰ افراد", PEOPLE) == []
    assert _kinds("٧٢٠٬٠٠٠ افراد", PEOPLE) == []
    assert "new_number" in _kinds("۷۲۱٬۰۰۰ افراد", PEOPLE)


def test_masks_quantiles_units_dates_terms_and_identifiers() -> None:
    text = "p10 8,124 m3/s on 2022-08-30 from Sentinel-1 scene S1A_20220830 in m³/s"
    s = scan(text, UNITS)
    assert [t.value for t in s.tokens] == [Decimal(8124)]
    assert s.dates == ["2022-08-30"]
    assert s.tokens[0].unit == "m3/s"


def test_new_date_and_new_identifier_rejected() -> None:
    assert "new_date" in _kinds("Covers 1,234 km2 on 2022-09-01.", AREA)
    assert "new_identifier" in _kinds("Covers 1,234 km2 water720.", AREA, known_idents=[])


def test_percent() -> None:
    assert _kinds("peaks at 81% on day", PCT) == []
    assert "dropped_slot" in _kinds("peaks at 0.81 on day", PCT)


def test_language_match() -> None:
    assert language_ok("Send 10 litres of water to Dadu.", "en", UNITS)
    assert not language_ok("دادو کو پانی بھیجیں۔", "en", UNITS)
    assert language_ok("دادو کو پانی کے 10 لیٹر بھیجیں۔", "ur", UNITS)
    assert not language_ok("Send water to Dadu now please.", "ur", UNITS)
    assert language_ok("Dadu کو پانی بھیجیں", "ur", UNITS, exempt=["Dadu"])


def test_format_number() -> None:
    assert format_number(Decimal("1234567.5"), "int", 0) == "1,234,568"
    assert format_number(Decimal("2.675"), "dec", 2) == "2.68"
    assert format_number(Decimal("0.805"), "pct", 0) == "81%"
    assert format_number(Decimal("1234"), "int", 0, "ur", "extended") == "۱٬۲۳۴"
    assert normalize_digits("۱٬۲۳۴٫۵٪") == "1,234.5%"
    assert extract_values("۱٬۲۳۴٫۵") == [Decimal("1234.5")]


def test_restricted_formatter() -> None:
    assert render("a {x} {{b}}", {"x": "1"}) == "a 1 {b}"
    for bad in ("{x.y}", "{x[0]}", "{x!r}", "{x:>3}", "{"):
        try:
            fields(bad)
        except PatternError:
            continue
        raise AssertionError(bad)
