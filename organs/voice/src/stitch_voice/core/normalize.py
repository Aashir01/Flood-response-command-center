"""Spoken-form normalization for TTS (VOX-R2.3, R2.4, VOX-P2; design section 4).

``normalize(text, lang)`` is pure, deterministic and idempotent. Order:
1. NFC, control characters removed, whitespace collapsed; Eastern Arabic digits mapped to ASCII.
2. Unspeakables removed: URLs, e-mail addresses, UUIDs, long hex strings, JSON pointers,
   markdown markers and bracketed citation markers.
3. (Urdu) known Latin names transliterated.
4. ISO dates read as day, month, year.
5. Units after a number, and currency before one.
6. Ordinals (English), ranges, then plain numbers.
7. (Urdu) remaining Latin tokens spelled letter by letter.
8. Tidy: spaces, punctuation, a final sentence mark.
Numbers touching a Latin letter (``ERA5``, ``Sen1Floods11``) are left for the English voice and,
in Urdu, spelled by step 7.
"""

from __future__ import annotations

import re
import unicodedata

from stitch_voice.core.latin import spell_latin, transliterate_known
from stitch_voice.core.numbers import en_int, en_ordinal, en_year, number_words, ur_int

MONTHS_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
MONTHS_UR = [
    "جنوری",
    "فروری",
    "مارچ",
    "اپریل",
    "مئی",
    "جون",
    "جولائی",
    "اگست",
    "ستمبر",
    "اکتوبر",
    "نومبر",
    "دسمبر",
]

# (english singular, english plural, urdu)
UNITS: dict[str, tuple[str, str, str]] = {
    "m3/s": ("cubic metre per second", "cubic metres per second", "کیوبک میٹر فی سیکنڈ"),
    "m³/s": ("cubic metre per second", "cubic metres per second", "کیوبک میٹر فی سیکنڈ"),
    "km2": ("square kilometre", "square kilometres", "مربع کلومیٹر"),
    "km²": ("square kilometre", "square kilometres", "مربع کلومیٹر"),
    "mm": ("millimetre", "millimetres", "ملی میٹر"),
    "km": ("kilometre", "kilometres", "کلومیٹر"),
    "kg": ("kilogram", "kilograms", "کلوگرام"),
    "ha": ("hectare", "hectares", "ہیکٹر"),
    "m": ("metre", "metres", "میٹر"),
    "t": ("tonne", "tonnes", "ٹن"),
    "%": ("percent", "percent", "فیصد"),
}
_CURRENCY = ("rupee", "rupees", "روپے")

_NUM = r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?"
_GUARD_L = r"(?<![A-Za-z0-9.,])"
_GUARD_R = r"(?![A-Za-z0-9]|[.,]\d)"

_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\ufeff]")
_SPACES_RE = re.compile(r"[ \t\u00a0]+")
_NEWLINES_RE = re.compile(r"\s*\n\s*")
_STRIP_PATTERNS = [
    re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{8,}\b"),
    re.compile(r"(?<!\S)(?:/[\w~-]+){2,}/?"),
    re.compile(r"\[[^\[\]\n]{0,40}\]"),
    re.compile(r"[*`_#>|]+"),
]
_DATE_RE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"(?!\d)"
)
_UNIT_KEYS = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
_UNIT_RE = re.compile(rf"{_GUARD_L}({_NUM})\s?({_UNIT_KEYS})(?![A-Za-z0-9²³/])")
_CURRENCY_RE = re.compile(rf"(?<![A-Za-z])(?:PKR|Rs\.?)\s?({_NUM.replace('-?', '')}){_GUARD_R}")
_ORDINAL_RE = re.compile(r"(?<![A-Za-z0-9.,])(\d+)(st|nd|rd|th)(?![A-Za-z0-9])")
_RANGE_RE = re.compile(rf"{_GUARD_L}(\d+(?:\.\d+)?)\s?[-–]\s?(\d+(?:\.\d+)?){_GUARD_R}")
_NUMBER_RE = re.compile(rf"{_GUARD_L}({_NUM}){_GUARD_R}")
# Leftover digit runs (odd grouping such as "12,34512"): read each run as an integer. English keeps
# digits that touch a Latin letter (ERA5); Urdu reads every run.
_LEFTOVER_EN_RE = re.compile(r"(?<![A-Za-z])\d+(?![A-Za-z])")
_LEFTOVER_UR_RE = re.compile(r"\d+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([,.;:!?۔؟،])")
_REPEATED_PUNCT_RE = re.compile(r"([,;:])(?:\s*[,;:])+")
_EASTERN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬", "01234567890123456789.,")
_SENTENCE_END = (".", "!", "?", "۔", "؟")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_EASTERN_DIGITS)
    text = _CONTROL_RE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _SPACES_RE.sub(" ", text)
    return _NEWLINES_RE.sub("\n", text).strip()


def _strip_unspeakable(text: str) -> str:
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def _date(m: re.Match[str], lang: str) -> str:
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return m.group(0).replace("-", " ")
    if lang == "ur":
        return f"{ur_int(day)} {MONTHS_UR[month - 1]} {ur_int(year)}"
    return f"{en_int(day)} {MONTHS_EN[month - 1]} {en_year(year)}"


def _unit(m: re.Match[str], lang: str) -> str:
    number, unit = m.group(1), m.group(2)
    singular, plural, urdu = UNITS[unit]
    if lang == "ur":
        return f"{number_words(number, 'ur')} {urdu}"
    word = singular if number.replace(",", "") in ("1", "1.0") else plural
    return f"{number_words(number, 'en')} {word}"


def _currency(m: re.Match[str], lang: str) -> str:
    number = m.group(1)
    if lang == "ur":
        return f"{number_words(number, 'ur')} {_CURRENCY[2]}"
    word = _CURRENCY[0] if number == "1" else _CURRENCY[1]
    return f"{number_words(number, 'en')} {word}"


def _range(m: re.Match[str], lang: str) -> str:
    joiner = "سے" if lang == "ur" else "to"
    return f"{number_words(m.group(1), lang)} {joiner} {number_words(m.group(2), lang)}"


def _tidy(text: str, lang: str) -> str:
    text = _SPACES_RE.sub(" ", text)
    text = _NEWLINES_RE.sub("\n", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _REPEATED_PUNCT_RE.sub(r"\1", text)
    lines = [line.strip(" ,;:-") for line in text.split("\n")]
    text = "\n".join(line for line in lines if any(ch.isalnum() for ch in line))
    if text and not text.endswith(_SENTENCE_END):
        text += "۔" if lang == "ur" else "."
    return text


def normalize(text: str, lang: str) -> str:
    """Spoken form of ``text`` for ``lang`` (``en`` or ``ur``). Empty when nothing is speakable."""
    text = _strip_unspeakable(_clean(text))
    if lang == "ur":
        text = transliterate_known(text)
    text = _DATE_RE.sub(lambda m: _date(m, lang), text)
    text = _CURRENCY_RE.sub(lambda m: _currency(m, lang), text)
    text = _UNIT_RE.sub(lambda m: _unit(m, lang), text)
    if lang == "en":
        text = _ORDINAL_RE.sub(lambda m: en_ordinal(int(m.group(1))), text)
    text = _RANGE_RE.sub(lambda m: _range(m, lang), text)
    text = _NUMBER_RE.sub(lambda m: number_words(m.group(1), lang), text)
    if lang == "ur":
        text = _LEFTOVER_UR_RE.sub(lambda m: " " + ur_int(int(m.group(0))) + " ", text)
        text = spell_latin(text)
    else:
        text = _LEFTOVER_EN_RE.sub(lambda m: en_int(int(m.group(0))), text)
    return _tidy(text, lang)
