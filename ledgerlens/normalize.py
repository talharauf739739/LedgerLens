"""Deterministic normalisation of values *as printed* into typed values.

The extractor copies text exactly as it appears ("£8,699.54", "(1.234,56)", "01 May 2025");
these functions turn it into Decimal / date / ISO codes. Code decides, not the model.
Every function returns None when it can't parse unambiguously: never guess.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_CURRENCY_TOKENS = re.compile(r"[$£€¥]|\b(?:USD|GBP|EUR|CHF|JPY|CAD|AUD)\b", re.IGNORECASE)
_SPACES = re.compile(r"[\s\u00a0\u202f']")  # incl. NBSP, narrow NBSP and Swiss apostrophe


def parse_money(text: str | None) -> Decimal | None:
    """'£8,699.54' -> 8699.54; '8.499,32 €' -> 8499.32; '(12.50)' / '-12.50' / '12.50-' -> -12.50.

    The decimal separator is whichever of '.'/',' comes last when followed by exactly
    1-2 digits; otherwise the number is treated as an integer with grouping separators.
    """
    if text is None:
        return None
    s = _CURRENCY_TOKENS.sub("", text).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.startswith(("-", "\u2212")):  # hyphen-minus or Unicode minus sign
        negative, s = True, s[1:].strip()
    elif s.endswith("-"):
        negative, s = True, s[:-1].strip()
    if s.startswith("+"):
        s = s[1:].strip()
    s = _SPACES.sub("", s)
    if not s or not re.fullmatch(r"[\d.,]+", s) or not s[0].isdigit():
        return None

    last_sep = max(s.rfind("."), s.rfind(","))
    if last_sep != -1 and 1 <= len(s) - last_sep - 1 <= 2:
        whole, frac = s[:last_sep], s[last_sep + 1 :]
        if not _valid_grouping(whole):
            return None
        number = whole.replace(".", "").replace(",", "") + "." + frac
    else:
        if not _valid_grouping(s):
            return None
        number = s.replace(".", "").replace(",", "")
    try:
        value = Decimal(number)
    except InvalidOperation:
        return None
    return -value if negative else value


def _valid_grouping(whole: str) -> bool:
    """Grouping separators must split the integer part into 3-digit groups."""
    if whole.isdigit():
        return True
    parts = re.split(r"[.,]", whole)
    seps = set(re.findall(r"[.,]", whole))
    return (
        len(seps) == 1
        and 1 <= len(parts[0]) <= 3
        and all(len(p) == 3 and p.isdigit() for p in parts[1:])
    )


_DATE_FORMATS_DAYFIRST = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%d.%m.%y"]
_DATE_FORMATS_MONTHFIRST = ["%m/%d/%Y", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"]
_DATE_FORMATS_ISO = ["%Y-%m-%d", "%Y/%m/%d"]


def parse_date(text: str | None, *, dayfirst: bool) -> date | None:
    """Parse a printed date. `dayfirst` resolves 03/04/2026 (True -> 3 April) and comes from
    the document's locale (e.g. USD statements are month-first)."""
    if text is None:
        return None
    s = re.sub(r"\s+", " ", text.strip().rstrip("."))
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)  # 1st May 2026
    ordered = (
        _DATE_FORMATS_ISO
        + (_DATE_FORMATS_DAYFIRST if dayfirst else _DATE_FORMATS_MONTHFIRST)
        + (_DATE_FORMATS_MONTHFIRST if dayfirst else _DATE_FORMATS_DAYFIRST)
    )
    for fmt in ordered:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


CURRENCY_BY_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY"}


def parse_currency(text: str | None) -> str | None:
    """'USD' -> 'USD'; '£' -> 'GBP'. ISO validity itself is checked by a rule."""
    if text is None:
        return None
    s = text.strip()
    if re.fullmatch(r"[A-Za-z]{3}", s):
        return s.upper()
    return CURRENCY_BY_SYMBOL.get(s)


COUNTRY_NAMES = {
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "germany": "DE",
    "deutschland": "DE",
    "france": "FR",
    "netherlands": "NL",
    "nederland": "NL",
    "the netherlands": "NL",
    "ireland": "IE",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "us": "US",
}


def parse_country(text: str | None) -> str | None:
    """Country as printed -> ISO-3166 alpha-2 (only names we know; else None)."""
    if text is None:
        return None
    s = text.strip()
    if re.fullmatch(r"[A-Z]{2}", s):
        return s
    return COUNTRY_NAMES.get(s.lower().rstrip("."))


def clean_text(text: str | None) -> str | None:
    if text is None:
        return None
    s = re.sub(r"\s+", " ", text).strip()
    return s or None
