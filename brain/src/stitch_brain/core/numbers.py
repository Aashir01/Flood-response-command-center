"""Numbers in claim text: normalization, masking, extraction, allowed-set matching, units,
language match and formatting (design section 6).

Every check here is a pure function of the text, the claim's slots and the evidence values the
claim cites. An LLM rewrite is accepted only if it passes ``check_text``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

# --- digit systems -------------------------------------------------------------------------------
_DIGIT_MAP: dict[int, str] = {}
for _i in range(10):
    _DIGIT_MAP[0x0660 + _i] = str(_i)  # Arabic-Indic
    _DIGIT_MAP[0x06F0 + _i] = str(_i)  # Extended Arabic-Indic (Urdu)
_DIGIT_MAP[0x066B] = "."  # Arabic decimal separator
_DIGIT_MAP[0x066C] = ","  # Arabic thousands separator
_DIGIT_MAP[0x066A] = "%"  # Arabic percent sign
_EXTENDED = {str(i): chr(0x06F0 + i) for i in range(10)} | {",": "\u066c", ".": "\u066b"}

DigitStyle = Literal["ascii", "extended"]


def normalize_digits(text: str) -> str:
    """Map Arabic-Indic and Extended Arabic-Indic digits and separators to ASCII. One char per
    char, so spans in the normalized text are spans in the original."""
    return text.translate(_DIGIT_MAP)


def to_extended(text: str) -> str:
    return "".join(_EXTENDED.get(ch, ch) for ch in text)


# --- number words ----------------------------------------------------------------------------
EN_NUMBER_WORDS: dict[str, int] = {
    w: i
    for i, w in enumerate(
        [
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
            "twenty",
        ]
    )
} | {"hundred": 100, "thousand": 1000, "million": 1_000_000, "lakh": 100_000, "crore": 10**7}
UR_NUMBER_WORDS: dict[str, int] = {
    w: i
    for i, w in enumerate(
        [
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
        ]
    )
} | {"سو": 100, "ہزار": 1000, "لاکھ": 100_000, "کروڑ": 10**7, "ملین": 1_000_000}
SCALE_WORDS = frozenset(
    {"hundred", "thousand", "million", "lakh", "crore", "سو", "ہزار", "لاکھ", "کروڑ", "ملین"}
)
_WORDS = {**EN_NUMBER_WORDS, **UR_NUMBER_WORDS}
_WORD_RE = re.compile(
    r"(?<!\w)(" + "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)

DEFAULT_TERMS = ("Sentinel-1", "Sentinel-2", "Sen1Floods11", "ERA5", "GloFAS")
_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?(?!\d)")
_QUANTILE_RE = re.compile(r"(?<!\w)p(?:10|50|90)(?!\w)", re.IGNORECASE)
_IDENT_RE = re.compile(r"(?<![\w])[A-Za-z][A-Za-z0-9_\-]*\d[\w\-]*")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_.,])(-?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)")


@dataclass(frozen=True)
class UnitTable:
    """Canonical unit key to accepted aliases (all languages)."""

    aliases: Mapping[str, Sequence[str]]

    def all_aliases(self) -> list[tuple[str, str]]:
        pairs = [(a, k) for k, al in self.aliases.items() for a in al]
        return sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    def regex(self) -> re.Pattern[str] | None:
        pairs = self.all_aliases()
        if not pairs:
            return None
        return re.compile(
            r"(?<![\w])(" + "|".join(re.escape(a) for a, _ in pairs) + r")(?![\w])", re.IGNORECASE
        )

    def canonical(self, alias: str) -> str | None:
        low = alias.lower()
        for a, k in self.all_aliases():
            if a.lower() == low:
                return k
        return None


@dataclass(frozen=True)
class Mask:
    start: int
    end: int
    kind: Literal["date", "unit", "quantile", "term", "ident", "exempt"]
    value: str  # date text or canonical unit key


@dataclass(frozen=True)
class NumToken:
    value: Decimal
    decimals: int
    percent: bool
    start: int
    end: int
    unit: str | None
    word: bool = False
    scale: bool = False
    text: str = ""


@dataclass
class Scan:
    normalized: str
    masks: list[Mask] = field(default_factory=list)
    tokens: list[NumToken] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)


def _overlaps(start: int, end: int, masks: Iterable[Mask]) -> bool:
    return any(start < m.end and m.start < end for m in masks)


def scan(
    text: str,
    units: UnitTable,
    *,
    terms: Sequence[str] = DEFAULT_TERMS,
    exempt: Sequence[str] = (),
) -> Scan:
    """Normalize, mask and extract number tokens (design 6.1, 6.2)."""
    norm = normalize_digits(text)
    masks: list[Mask] = []

    def add(m: re.Match[str], kind: Any, value: str) -> None:
        if not _overlaps(m.start(), m.end(), masks):
            masks.append(Mask(m.start(), m.end(), kind, value))

    for m in _DATE_RE.finditer(norm):
        add(m, "date", m.group(0)[:10])
    for t in terms:
        for m in re.finditer(r"(?<!\w)" + re.escape(t) + r"(?!\w)", norm, re.IGNORECASE):
            add(m, "term", t)
    unit_re = units.regex()
    if unit_re is not None:
        for m in unit_re.finditer(norm):
            key = units.canonical(m.group(0))
            if key is not None:
                add(m, "unit", key)
    for m in _QUANTILE_RE.finditer(norm):
        add(m, "quantile", m.group(0))
    for ex in sorted(set(exempt), key=len, reverse=True):
        if ex:
            for m in re.finditer(re.escape(normalize_digits(ex)), norm):
                add(m, "exempt", ex)
    for m in _IDENT_RE.finditer(norm):
        add(m, "ident", m.group(0))
    masks.sort(key=lambda m: m.start)

    def unit_after(end: int) -> str | None:
        for m in masks:
            if m.kind == "unit" and (m.start == end or (m.start == end + 1 and norm[end] == " ")):
                return m.value
        return None

    tokens: list[NumToken] = []
    for m in _NUM_RE.finditer(norm):
        if _overlaps(m.start(), m.end(), masks):
            continue
        sign, whole, frac, pct = m.group(1), m.group(2), m.group(3) or "", m.group(4)
        if (
            sign
            and m.start() > 0
            and not norm[m.start() - 1].isspace()
            and norm[m.start() - 1] != "("
        ):
            sign = ""
        raw = sign + whole.replace(",", "") + frac
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        start = m.start() if sign else m.start(2)
        tokens.append(
            NumToken(
                value=value,
                decimals=len(frac) - 1 if frac else 0,
                percent=bool(pct),
                start=start,
                end=m.end(),
                unit="pct" if pct else unit_after(m.end()),
                text=m.group(0),
            )
        )
    for m in _WORD_RE.finditer(norm):
        if _overlaps(m.start(), m.end(), masks):
            continue
        w = m.group(1)
        key = w.lower() if w.lower() in _WORDS else w
        tokens.append(
            NumToken(
                value=Decimal(_WORDS[key]),
                decimals=0,
                percent=False,
                start=m.start(),
                end=m.end(),
                unit=unit_after(m.end()),
                word=True,
                scale=key in SCALE_WORDS,
                text=w,
            )
        )
    tokens.sort(key=lambda t: t.start)
    dates = [m.value for m in masks if m.kind == "date"]
    return Scan(normalized=norm, masks=masks, tokens=tokens, dates=dates)


def extract_values(text: str, units: UnitTable | None = None) -> list[Decimal]:
    return [t.value for t in scan(text, units or UnitTable({})).tokens]


# --- allowed set and matching ------------------------------------------------------------------
def _q(value: Decimal, decimals: int, rounding: str) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=rounding)


def matches(
    token_value: Decimal, token_decimals: int, allowed: Decimal, max_decimals: int | None
) -> bool:
    """``allowed`` rounded to the token's decimals equals the token (HALF_UP or HALF_EVEN). A
    token more precise than the slot's display precision must equal the unrounded value."""
    if max_decimals is not None and token_decimals > max_decimals:
        return allowed == token_value
    try:
        return token_value in (
            _q(allowed, token_decimals, ROUND_HALF_UP),
            _q(allowed, token_decimals, ROUND_HALF_EVEN),
        )
    except InvalidOperation:
        return False


@dataclass(frozen=True)
class SlotSpec:
    """What the checker needs from a claim slot."""

    name: str
    value: Decimal
    unit: str | None
    decimals: int | None
    fmt: str


@dataclass(frozen=True)
class Issue:
    check: Literal["C2", "C3", "C5"]
    kind: str
    detail: str


def identifiers(text: str, units: UnitTable) -> list[str]:
    """Masked identifiers and configured terms (``Sentinel-1``, scene ids): a rewrite may only
    use ones that occur in the evidence or the template text, so ``Sentinel-1`` cannot become
    ``Sentinel-2`` behind the mask."""
    return [m.value for m in scan(text, units).masks if m.kind in ("ident", "term")]


def leaf_numbers(value: Any, units: UnitTable) -> tuple[list[Decimal], list[str]]:
    """Numbers and dates found in an evidence value (numeric leaves and string leaves)."""
    nums: list[Decimal] = []
    dates: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, int | float):
            nums.append(Decimal(repr(v)) if isinstance(v, float) else Decimal(v))
        elif isinstance(v, str):
            s = scan(v, units)
            nums.extend(t.value for t in s.tokens)
            dates.extend(s.dates)
            if _DATE_RE.fullmatch(v.strip()):
                dates.append(v.strip()[:10])
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return nums, dates


def check_text(
    text: str,
    slots: Sequence[SlotSpec],
    units: UnitTable,
    *,
    extra_numbers: Sequence[Decimal] = (),
    extra_dates: Sequence[str] = (),
    slot_dates: Sequence[str] = (),
    exempt: Sequence[str] = (),
    require_slots: bool = True,
    known_idents: Iterable[str] | None = None,
    required_idents: Iterable[str] = (),
) -> list[Issue]:
    """Checks C2 (numbers) and C3 (units) of design 6.3 and 6.4. Empty list means pass.

    Each numeric slot needs its own token (a bipartite match), so a rewrite cannot drop one of
    two equal numbers. ``required_idents`` (identifiers and terms of the template text) must
    all survive a rewrite."""
    s = scan(text, units, exempt=exempt)
    issues: list[Issue] = []
    seen: set[str] = set()
    edges: list[list[str]] = []
    for tok in s.tokens:
        if tok.scale and tok.word:
            issues.append(Issue("C2", "scale_word", f"scale word {tok.text!r}"))
            continue
        cands: list[SlotSpec] = []
        for sl in slots:
            target = sl.value * 100 if sl.fmt == "pct" else sl.value
            if tok.percent != (sl.fmt == "pct"):
                continue
            if matches(tok.value, tok.decimals, target, sl.decimals) and _keeps_precision(
                tok, target, sl.decimals
            ):
                cands.append(sl)
        if cands:
            good = [c for c in cands if _unit_ok(c, tok)]
            if good:
                edges.append([c.name for c in good])
                continue
            c = cands[0]
            if c.unit is None and tok.unit is not None:
                issues.append(Issue("C3", "unit_on_count", f"{tok.text} followed by {tok.unit}"))
            elif tok.unit is None:
                issues.append(Issue("C3", "unit_missing", f"{tok.text} needs unit {c.unit}"))
            else:
                issues.append(
                    Issue("C3", "unit_swapped", f"{tok.text} has {tok.unit}, not {c.unit}")
                )
            seen.add(c.name)
            continue
        if any(_evidence_match(tok, a) for a in extra_numbers) or (
            tok.percent and any(_evidence_match(tok, a * 100) for a in extra_numbers)
        ):
            continue
        issues.append(Issue("C2", "new_number", f"{tok.text} is not in the evidence"))
    if known_idents is not None:
        known = set(known_idents)
        for mk in s.masks:
            if mk.kind in ("ident", "term") and mk.value not in known:
                issues.append(Issue("C2", "new_identifier", f"{mk.value!r} is not in the evidence"))
    allowed_dates = set(slot_dates) | set(extra_dates)
    for d in s.dates:
        if d not in allowed_dates:
            issues.append(Issue("C2", "new_date", f"date {d} is not in the evidence"))
    if known_idents is not None:
        for ident in dict.fromkeys(required_idents):
            if ident not in s.normalized:  # substring: exempt spans hide masks, not text
                issues.append(Issue("C2", "dropped_identifier", f"{ident!r} missing from text"))
    seen |= _assign(edges)
    if require_slots:
        for sl in slots:
            if sl.fmt in ("int", "dec", "pct") and sl.name not in seen:
                issues.append(Issue("C2", "dropped_slot", f"slot {sl.name} missing from text"))
        for d in slot_dates:
            if d not in s.dates:
                issues.append(Issue("C2", "dropped_slot", f"date {d} missing from text"))
    return issues


def _assign(edges: Sequence[Sequence[str]]) -> set[str]:
    """Maximum bipartite matching of tokens to slot names (Kuhn's algorithm); returns the
    matched slot names. Slots per claim are few, so the quadratic cost is irrelevant."""
    owner: dict[str, int] = {}

    def augment(i: int, visited: set[str]) -> bool:
        for name in edges[i]:
            if name in visited:
                continue
            visited.add(name)
            if name not in owner or augment(owner[name], visited):
                owner[name] = i
                return True
        return False

    for i in range(len(edges)):
        augment(i, set())
    return set(owner)


def _keeps_precision(tok: NumToken, value: Decimal, decimals: int | None) -> bool:
    """A token with fewer decimals than the slot's display precision is accepted only when
    nothing is lost (``1.00`` as ``1``, ``0.0%`` as ``0%``), never ``0.20`` as ``0``."""
    if decimals is None or tok.decimals >= decimals:
        return True
    try:
        return _q(value, decimals, ROUND_HALF_UP) == _q(value, tok.decimals, ROUND_HALF_UP)
    except InvalidOperation:
        return False


def _evidence_match(tok: NumToken, value: Decimal) -> bool:
    """A number from an evidence leaf, rounded to the token's decimals, without losing the
    leaf's own precision below the token's (``0.2`` may not appear as ``0``)."""
    if not matches(tok.value, tok.decimals, value, None):
        return False
    exp = value.normalize().as_tuple().exponent
    own = max(0, -exp) if isinstance(exp, int) else 0
    return tok.decimals >= own or _keeps_precision(tok, value, own) or tok.value != 0


def _unit_ok(slot: SlotSpec, tok: NumToken) -> bool:
    if slot.fmt == "pct":
        return tok.percent
    return slot.unit == tok.unit


# --- language match (design 6.5) ----------------------------------------------------------------
def _is_arabic(ch: str) -> bool:
    o = ord(ch)
    return (
        0x0600 <= o <= 0x06FF
        or 0x0750 <= o <= 0x077F
        or 0xFB50 <= o <= 0xFDFF
        or 0xFE70 <= o <= 0xFEFF
    )


def script_share(text: str, units: UnitTable, exempt: Sequence[str] = ()) -> tuple[int, int, int]:
    """(latin, arabic, total letters) outside masked spans."""
    s = scan(text, units, exempt=exempt)
    latin = arabic = total = 0
    for i, ch in enumerate(s.normalized):
        if not ch.isalpha() or _overlaps(i, i + 1, s.masks):
            continue
        total += 1
        if _is_arabic(ch):
            arabic += 1
        elif ch.isascii() or "LATIN" in _uname(ch):
            latin += 1
    return latin, arabic, total


def _uname(ch: str) -> str:
    import unicodedata

    return unicodedata.name(ch, "")


def language_ok(text: str, lang: str, units: UnitTable, exempt: Sequence[str] = ()) -> bool:
    latin, arabic, total = script_share(text, units, exempt)
    if total == 0:
        return True
    if lang == "en":
        return latin / total >= 0.90
    return arabic / total >= 0.60


# --- formatting --------------------------------------------------------------------------------
def format_number(
    value: Decimal, fmt: str, decimals: int | None, lang: str = "en", digits: DigitStyle = "ascii"
) -> str:
    if fmt == "pct":
        d = decimals or 0
        q = _q(value * 100, d, ROUND_HALF_UP)
        out = f"{q:,.{d}f}%"
    elif fmt == "int":
        q = _q(value, 0, ROUND_HALF_UP)
        out = f"{q:,.0f}"
    elif fmt == "dec":
        d = 2 if decimals is None else decimals
        q = _q(value, d, ROUND_HALF_UP)
        out = f"{q:,.{d}f}"
    else:
        raise ValueError(f"not a numeric format: {fmt}")
    if out.startswith("-") and Decimal(out.rstrip("%").replace(",", "")) == 0:
        out = out[1:]
    if lang == "ur" and digits == "extended":
        out = to_extended(out).replace("%", "\u066a")
    return out


def format_date(value: date) -> str:
    return value.isoformat()


def to_decimal(x: Any) -> Decimal:
    """Decimal from a JSON number, via ``repr`` for floats (design 5.1)."""
    if isinstance(x, bool):
        raise TypeError("bool is not a number")
    if isinstance(x, float):
        return Decimal(repr(x))
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, Decimal):
        return x
    raise TypeError(f"not a number: {type(x).__name__}")
