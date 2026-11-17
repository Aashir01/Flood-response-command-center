"""Table-driven normalization tests (VOX-R2.3, R2.4; voice task 3)."""

from __future__ import annotations

import re

import pytest

from stitch_voice.core.normalize import normalize
from stitch_voice.core.numbers import en_int, en_ordinal, en_year, number_words, ur_int

LATIN = re.compile(r"[A-Za-z0-9]")


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"),
        (13, "thirteen"),
        (45, "forty-five"),
        (100, "one hundred"),
        (1001, "one thousand one"),
        (1_234_567, "one million two hundred thirty-four thousand five hundred sixty-seven"),
    ],
)
def test_en_int(n: int, words: str) -> None:
    assert en_int(n) == words


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "صفر"),
        (22, "بائیس"),
        (99, "ننانوے"),
        (105, "ایک سو پانچ"),
        (2022, "دو ہزار بائیس"),
        (150_000, "ایک لاکھ پچاس ہزار"),
        (1_200_000, "بارہ لاکھ"),
        (33_000_000, "تین کروڑ تیس لاکھ"),
        (2_000_000_000, "دو ارب"),
    ],
)
def test_ur_int_uses_lakh_and_crore(n: int, words: str) -> None:
    assert ur_int(n) == words


def test_years_ordinals_decimals() -> None:
    assert en_year(2022) == "twenty twenty-two"
    assert en_year(2005) == "two thousand five"
    assert en_year(1900) == "nineteen hundred"
    assert en_year(1905) == "nineteen oh five"
    assert en_ordinal(21) == "twenty-first"
    assert en_ordinal(12) == "twelfth"
    assert en_ordinal(40) == "fortieth"
    assert number_words("3.05", "en") == "three point zero five"
    assert number_words("-1,234", "en") == "minus one thousand two hundred thirty-four"
    assert number_words("2.5", "ur") == "دو اعشاریہ پانچ"


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("12,345 m3/s", "twelve thousand three hundred forty-five cubic metres per second."),
        ("12 m³/s", "twelve cubic metres per second."),
        ("1 km2", "one square kilometre."),
        ("4.5 km²", "four point five square kilometres."),
        ("30 mm", "thirty millimetres."),
        ("45%", "forty-five percent."),
        ("PKR 2500", "two thousand five hundred rupees."),
        ("2022-08-30", "thirty August twenty twenty-two."),
        ("2022-08-30T06:00:00Z", "thirty August twenty twenty-two."),
        ("3-5 days", "three to five days."),
        ("the 21st day", "the twenty-first day."),
        ("GloFAS and NDMA", "GloFAS and NDMA."),
        ("ERA5 data", "ERA5 data."),
        ("one mm of rain", "one mm of rain."),
    ],
)
def test_english_spoken_forms(text: str, spoken: str) -> None:
    assert normalize(text, "en") == spoken


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("12,345 m3/s", "بارہ ہزار تین سو پینتالیس کیوبک میٹر فی سیکنڈ۔"),
        ("2022-08-30", "تیس اگست دو ہزار بائیس۔"),
        ("1,200,000 افراد", "بارہ لاکھ افراد۔"),
        ("GloFAS", "گلوفاس۔"),
        ("NDMA", "این ڈی ایم اے۔"),
        ("XYZ", "ایکس وائی زیڈ۔"),
        ("۴۵%", "پینتالیس فیصد۔"),
    ],
)
def test_urdu_spoken_forms(text: str, spoken: str) -> None:
    assert normalize(text, "ur") == spoken


def test_unspeakables_are_stripped() -> None:
    text = (
        "See https://example.org/a?b=1 and a@b.org [1] [doc 12] run "
        "123e4567-e89b-12d3-a456-426614174000 /data/forecast/3/p50 deadbeef01 **bold**"
    )
    assert normalize(text, "en") == "See and run bold."


def test_no_latin_or_digits_remain_in_urdu() -> None:
    text = "Discharge 12 m3/s at Sukkur on 2022-08-30, Sen1Floods11 and ERA5 (Copernicus)."
    out = normalize(text, "ur")
    assert not LATIN.search(out)


def test_only_unspeakable_gives_empty() -> None:
    assert normalize("https://x.org [1]", "en") == ""
