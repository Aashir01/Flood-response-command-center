"""Latin-script text inside Urdu speech (VOX-R2.4, design section 4 step 6).

Rule, in order:
1. A name in ``TRANSLITERATIONS`` (case-insensitive) is replaced by its Urdu-script reading.
2. Any other Latin token (acronym, code or word) is spelled letter by letter with Urdu letter
   names; digits inside it are read one by one.
After this step no Latin letter or ASCII digit is left, which keeps normalization idempotent.
The Urdu ``ur-PK`` voices are not multilingual, so switching voices mid-sentence is not an option.
"""

from __future__ import annotations

import re

from stitch_voice.core.numbers import UR_0_99

TRANSLITERATIONS: dict[str, str] = {
    "glofas": "گلوفاس",
    "open-meteo": "اوپن میٹیو",
    "sentinel-1": "سینٹینل ون",
    "sentinel-2": "سینٹینل ٹو",
    "unosat": "یونوسیٹ",
    "copernicus": "کوپرنیکس",
    "ndma": "این ڈی ایم اے",
    "pdma": "پی ڈی ایم اے",
    "worldpop": "ورلڈ پاپ",
    "openstreetmap": "اوپن اسٹریٹ میپ",
    "sen1floods11": "سین ون فلڈز الیون",
    "era5": "ای آر اے فائیو",
    "stitch": "اسٹچ",
    "pakistan": "پاکستان",
    "sindh": "سندھ",
    "indus": "دریائے سندھ",
    "karachi": "کراچی",
    "hyderabad": "حیدرآباد",
    "sukkur": "سکھر",
    "kotri": "کوٹری",
    "guddu": "گڈو",
    "dadu": "دادو",
    "jamshoro": "جامشورو",
    "larkana": "لاڑکانہ",
    "khairpur": "خیرپور",
    "thatta": "ٹھٹہ",
    "badin": "بدین",
    "sanghar": "سانگھڑ",
    "shikarpur": "شکارپور",
    "jacobabad": "جیکب آباد",
    "kashmore": "کشمور",
    "ghotki": "گھوٹکی",
    "mirpurkhas": "میرپورخاص",
    "umerkot": "عمرکوٹ",
    "tharparkar": "تھرپارکر",
    "matiari": "مٹیاری",
    "tando": "ٹنڈو",
    "qambar": "قمبر",
    "shahdadkot": "شہدادکوٹ",
    "naushahro": "نوشہرو",
    "feroze": "فیروز",
    "sujawal": "سجاول",
}

LETTERS: dict[str, str] = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        [
            "اے",
            "بی",
            "سی",
            "ڈی",
            "ای",
            "ایف",
            "جی",
            "ایچ",
            "آئی",
            "جے",
            "کے",
            "ایل",
            "ایم",
            "این",
            "او",
            "پی",
            "کیو",
            "آر",
            "ایس",
            "ٹی",
            "یو",
            "وی",
            "ڈبلیو",
            "ایکس",
            "وائی",
            "زیڈ",
        ],
        strict=True,
    )
)

_DICT_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(k) for k in sorted(TRANSLITERATIONS, key=len, reverse=True))
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")


def transliterate_known(text: str) -> str:
    return _DICT_RE.sub(lambda m: TRANSLITERATIONS[m.group(1).lower()], text)


def _spell(token: str) -> str:
    out = []
    for ch in token.lower():
        out.append(LETTERS[ch] if ch in LETTERS else UR_0_99[int(ch)])
    return " ".join(out)


def spell_latin(text: str) -> str:
    return _LATIN_TOKEN_RE.sub(lambda m: _spell(m.group(0)), text)
