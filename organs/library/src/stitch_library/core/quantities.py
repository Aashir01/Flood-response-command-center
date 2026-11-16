"""Numbers and quantities in English and Urdu text. Pure.

* ``numbers_in(text)``: every number as a ``Decimal``: digit runs (Urdu digits folded, thousands
  separators removed, decimals, simple fractions such as ``1/8``) and number words (``one`` to
  ``hundred``, ``half``, ``three quarters``, Urdu ``ایک`` to ``بیس``). Used by the claim number
  check (design 7.3 step 3): a claim survives only if its numbers occur in its quotes.
* ``extract_quantities(text)``: ``(value, unit, per)`` triples where a number is followed by a
  known unit, with the unit's canonical name, dimension and factor to a base unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from stitch_library.core.normalize import search_text

_EN_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}  # fmt: skip
_EN_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_EN_SPECIAL = {"hundred": Decimal(100), "half": Decimal("0.5"), "dozen": Decimal(12)}
_UR_WORDS: dict[str, int | Decimal] = {
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9,
    "دس": 10, "گیارہ": 11, "بارہ": 12, "پندرہ": 15, "بیس": 20, "پچیس": 25, "تیس": 30,
    "آدھا": Decimal("0.5"), "آدھی": Decimal("0.5"),
}  # fmt: skip

_DIGIT = re.compile(r"(?<![\w.])(\d+)/(\d+)(?!\w)|(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
_WORD = re.compile(r"\w+(?:-\w+)?")


def _canon(d: Decimal) -> Decimal:
    n = d.normalize()
    return n.quantize(Decimal(1)) if n == n.to_integral() else n


@dataclass(frozen=True)
class NumberMatch:
    value: Decimal
    start: int
    end: int


def _word_value(w: str) -> Decimal | None:
    if w in _EN_UNITS:
        return Decimal(_EN_UNITS[w])
    if w in _EN_TENS:
        return Decimal(_EN_TENS[w])
    if w in _EN_SPECIAL:
        return _EN_SPECIAL[w]
    if "-" in w:
        a, _, b = w.partition("-")
        if a in _EN_TENS and b in _EN_UNITS and 0 < _EN_UNITS[b] < 10:
            return Decimal(_EN_TENS[a] + _EN_UNITS[b])
        if a in _EN_UNITS and b == "half":
            return Decimal(_EN_UNITS[a]) / 2 if a == "one" else None
    if w in _UR_WORDS:
        return Decimal(_UR_WORDS[w])  # int or Decimal
    return None


def number_matches(text: str) -> list[NumberMatch]:
    """Numbers with offsets into ``search_text(text)`` (lowercase, ASCII digits)."""
    s = search_text(text)
    out: list[NumberMatch] = []
    taken: list[tuple[int, int]] = []
    for m in _DIGIT.finditer(s):
        try:
            if m.group(1) is not None:
                den = Decimal(m.group(2))
                if den == 0:
                    continue
                num = Decimal(m.group(1)) / den
            else:
                whole = m.group(3).replace(",", "")
                num = Decimal(whole + ("." + m.group(4) if m.group(4) else ""))
        except InvalidOperation:
            continue
        out.append(NumberMatch(_canon(num), m.start(), m.end()))
        taken.append((m.start(), m.end()))
    words = list(_WORD.finditer(s))
    i = 0
    while i < len(words):
        m = words[i]
        w = m.group(0)
        found = _word_value(w)
        if found is None or any(a <= m.start() < b for a, b in taken):
            i += 1
            continue
        val: Decimal = found
        end = m.end()
        # "three quarters" -> 0.75; "twenty five" -> 25
        if i + 1 < len(words):
            nxt = words[i + 1].group(0)
            if nxt in ("quarter", "quarters") and val < 4:
                val, end, i = val / 4, words[i + 1].end(), i + 1
            elif w in _EN_TENS and nxt in _EN_UNITS and 0 < _EN_UNITS[nxt] < 10:
                val, end, i = val + _EN_UNITS[nxt], words[i + 1].end(), i + 1
        out.append(NumberMatch(_canon(val), m.start(), end))
        i += 1
    out.sort(key=lambda n: n.start)
    return out


def numbers_in(text: str) -> set[Decimal]:
    return {n.value for n in number_matches(text)}


@dataclass(frozen=True)
class UnitDef:
    unit: str
    dimension: str
    factor: float  # to the dimension's base unit
    implied_per: str | None = None  # "lpd" means litres per person per day


_UNIT_ALIASES: dict[str, UnitDef] = {}


def _add(aliases: str, unit: str, dim: str, factor: float, implied: str | None = None) -> None:
    for a in aliases.split("|"):
        _UNIT_ALIASES[a] = UnitDef(unit, dim, factor, implied)


_add("l|litre|litres|liter|liters|لیٹر", "L", "volume", 1.0)
_add("lpd", "L", "volume", 1.0, "person_day")
_add("ml|millilitre|millilitres|milliliter|milliliters", "mL", "volume", 0.001)
_add("gallon|gallons|گیلن", "gal_us", "volume", 3.78541)
_add("quart|quarts", "qt_us", "volume", 0.946353)
_add("pint|pints", "pt_us", "volume", 0.473176)
_add("teaspoon|teaspoons|tsp|چمچ", "tsp", "volume", 0.00492892)
_add("drop|drops|قطرے|قطرہ", "drop", "volume", 0.00005)
_add("m3|m³", "m3", "volume", 1000.0)
_add("kg|kilogram|kilograms|کلو|کلوگرام", "kg", "mass", 1.0)
_add("g|gram|grams|گرام", "g", "mass", 0.001)
_add("pound|pounds|lb|lbs", "lb", "mass", 0.453592)
_add("ounce|ounces|oz", "oz", "mass", 0.0283495)
_add("kcal|calories", "kcal", "energy", 1.0)
_add("day|days|دن|دنوں", "day", "time", 24.0)
_add("hour|hours|گھنٹے|گھنٹہ|گھنٹوں", "hour", "time", 1.0)
_add("minute|minutes|منٹ", "minute", "time", 1 / 60)
_add("week|weeks|ہفتے|ہفتہ", "week", "time", 168.0)
_add("month|months|مہینے", "month", "time", 730.0)
_add("percent|%|فیصد", "percent", "fraction", 1.0)
_add("inch|inches|انچ", "inch", "length", 0.0254)
_add("foot|feet|فٹ", "ft", "length", 0.3048)
_add("cm", "cm", "length", 0.01)
_add("mm", "mm", "length", 0.001)
_add("m2|m²", "m2", "area", 1.0)
_add("person|persons|people|افراد|شخص|فرد", "person", "count", 1.0)

_PER_PERSON = {"person", "persons", "people", "کس", "شخص", "فرد"}
_PER_DAY = {"day", "daily", "دن", "روزانہ", "یومیہ"}
_TOKEN = re.compile(r"%|\w+")


@dataclass(frozen=True)
class QuantityMatch:
    value: float
    unit: str
    dimension: str
    base_value: float
    per: str | None
    start: int


def _per(tokens: list[str]) -> str | None:
    person = day = False
    other: str | None = None
    for i, t in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        slash_day = i == 0 or (i == 1 and tokens[0] in _PER_PERSON)  # "litres/person/day"
        if t in _PER_DAY and (
            prev in ("per", "a", "each", "فی") or t in ("daily", "روزانہ", "یومیہ") or slash_day
        ):
            day = True
        elif t in _PER_PERSON and (prev in ("per", "each", "فی") or i == 0):
            person = True
        elif prev == "per" and t in _UNIT_ALIASES and other is None:
            other = _UNIT_ALIASES[t].unit
    if person and day:
        return "person_day"
    if person:
        return "person"
    if day:
        return "day"
    return other


def extract_quantities(text: str) -> list[QuantityMatch]:
    s = search_text(text)
    out: list[QuantityMatch] = []
    for n in number_matches(text):
        tail = [m.group(0) for m in _TOKEN.finditer(s, n.end, min(len(s), n.end + 120))]
        unit: UnitDef | None = None
        rest: list[str] = []
        for j, tok in enumerate(tail[:3]):
            if tok in _UNIT_ALIASES:
                unit = _UNIT_ALIASES[tok]
                rest = tail[j + 1 : j + 9]
                break
            if tok.isdigit():
                break
        if unit is None:
            continue
        value = float(n.value)
        per = unit.implied_per or _per(rest)
        out.append(
            QuantityMatch(value, unit.unit, unit.dimension, value * unit.factor, per, n.start)
        )
    return out
