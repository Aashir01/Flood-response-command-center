"""Numbers to spoken words. English (Western grouping) and Urdu (hazaar, lakh, crore, arab).

The Urdu 0..99 table is irregular and needs a native speaker's review (voice task 3, owner step).
"""

from __future__ import annotations

_EN_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_EN_SCALES = ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand"))

UR_0_99 = [
    "صفر",
    "ایک",
    "دو",
    "تین",
    "چار",
    "پانچ",
    "چھ",
    "سات",
    "آٹھ",
    "نو",
    "دس",
    "گیارہ",
    "بارہ",
    "تیرہ",
    "چودہ",
    "پندرہ",
    "سولہ",
    "سترہ",
    "اٹھارہ",
    "انیس",
    "بیس",
    "اکیس",
    "بائیس",
    "تئیس",
    "چوبیس",
    "پچیس",
    "چھبیس",
    "ستائیس",
    "اٹھائیس",
    "انتیس",
    "تیس",
    "اکتیس",
    "بتیس",
    "تینتیس",
    "چونتیس",
    "پینتیس",
    "چھتیس",
    "سینتیس",
    "اڑتیس",
    "انتالیس",
    "چالیس",
    "اکتالیس",
    "بیالیس",
    "تینتالیس",
    "چوالیس",
    "پینتالیس",
    "چھیالیس",
    "سینتالیس",
    "اڑتالیس",
    "انچاس",
    "پچاس",
    "اکیاون",
    "باون",
    "ترپن",
    "چون",
    "پچپن",
    "چھپن",
    "ستاون",
    "اٹھاون",
    "انسٹھ",
    "ساٹھ",
    "اکسٹھ",
    "باسٹھ",
    "تریسٹھ",
    "چونسٹھ",
    "پینسٹھ",
    "چھیاسٹھ",
    "سڑسٹھ",
    "اڑسٹھ",
    "انہتر",
    "ستر",
    "اکہتر",
    "بہتر",
    "تہتر",
    "چوہتر",
    "پچھتر",
    "چھہتر",
    "ستتر",
    "اٹھہتر",
    "اناسی",
    "اسی",
    "اکیاسی",
    "بیاسی",
    "تراسی",
    "چوراسی",
    "پچاسی",
    "چھیاسی",
    "ستاسی",
    "اٹھاسی",
    "نواسی",
    "نوے",
    "اکانوے",
    "بانوے",
    "ترانوے",
    "چورانوے",
    "پچانوے",
    "چھیانوے",
    "ستانوے",
    "اٹھانوے",
    "ننانوے",
]
assert len(UR_0_99) == 100

UR_HUNDRED = "سو"
UR_THOUSAND = "ہزار"
UR_LAKH = "لاکھ"
UR_CRORE = "کروڑ"
UR_ARAB = "ارب"
UR_POINT = "اعشاریہ"
UR_MINUS = "منفی"


def en_int(n: int) -> str:
    if n < 0:
        return "minus " + en_int(-n)
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _EN_TENS[tens] + (f"-{_EN_ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_EN_ONES[hundreds]} hundred" + (f" {en_int(rest)}" if rest else "")
    for scale, name in _EN_SCALES:
        if n >= scale:
            head, rest = divmod(n, scale)
            return f"{en_int(head)} {name}" + (f" {en_int(rest)}" if rest else "")
    raise AssertionError("unreachable")


def ur_int(n: int) -> str:
    if n < 0:
        return f"{UR_MINUS} {ur_int(-n)}"
    if n < 100:
        return UR_0_99[n]
    parts: list[str] = []
    arab, n = divmod(n, 10**9)
    if arab:
        parts.append(f"{ur_int(arab)} {UR_ARAB}")
    for size, name in ((10**7, UR_CRORE), (10**5, UR_LAKH), (1000, UR_THOUSAND)):
        head, n = divmod(n, size)
        if head:
            parts.append(f"{UR_0_99[head]} {name}")
    hundreds, n = divmod(n, 100)
    if hundreds:
        parts.append(f"{UR_0_99[hundreds]} {UR_HUNDRED}")
    if n:
        parts.append(UR_0_99[n])
    return " ".join(parts)


def number_words(text: str, lang: str) -> str:
    """``text`` is an ASCII number: optional ``-``, digits with optional ``,`` grouping, and an
    optional ``.`` fraction. Fraction digits are read one by one."""
    negative = text.startswith("-")
    body = text.lstrip("-").replace(",", "")
    whole, _, frac = body.partition(".")
    to_words = ur_int if lang == "ur" else en_int
    words = to_words(int(whole or "0"))
    if frac:
        point = UR_POINT if lang == "ur" else "point"
        words += f" {point} " + " ".join(to_words(int(d)) for d in frac)
    if negative:
        words = (UR_MINUS if lang == "ur" else "minus") + " " + words
    return words


def en_year(year: int) -> str:
    """English year reading: 2022 -> twenty twenty-two, 2005 -> two thousand five,
    1900 -> nineteen hundred, 1905 -> nineteen oh five."""
    if not 1100 <= year <= 2099 or 2000 <= year <= 2009:
        return en_int(year)
    head, tail = divmod(year, 100)
    if tail == 0:
        return f"{en_int(head)} hundred"
    if tail < 10:
        return f"{en_int(head)} oh {en_int(tail)}"
    return f"{en_int(head)} {en_int(tail)}"


_IRREGULAR_ORDINALS = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}


def en_ordinal(n: int) -> str:
    words = en_int(n)
    cut = max(words.rfind(" "), words.rfind("-")) + 1
    head, last = words[:cut], words[cut:]
    if last in _IRREGULAR_ORDINALS:
        last = _IRREGULAR_ORDINALS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return head + last
