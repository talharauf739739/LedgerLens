from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledgerlens.normalize import parse_country, parse_currency, parse_date, parse_money
from synth.common import fmt_money


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£8,699.54", "8699.54"),
        ("$2,949.06", "2949.06"),
        ("8.499,32 €", "8499.32"),
        ("1.255,18", "1255.18"),
        ("-33,34", "-33.34"),
        ("(1,234.56)", "-1234.56"),
        ("12.50-", "-12.50"),
        ("1 234,56", "1234.56"),
        ("1'234.50", "1234.50"),
        ("EUR 10", "10"),
        ("1,000", "1000"),  # grouping only, no decimals
        ("7.5", "7.5"),
        ("0,5", "0.5"),
    ],
)
def test_parse_money(text: str, expected: str) -> None:
    assert parse_money(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "12,34,5", "1.23.4,5", "N/A", "--", None])
def test_parse_money_refuses_to_guess(text: str | None) -> None:
    assert parse_money(text) is None


@given(
    amount=st.decimals(min_value=Decimal("-9999999.99"), max_value=Decimal("9999999.99"), places=2),
    style=st.sampled_from(["us", "eu"]),
    symbol=st.sampled_from(["", "$", "£", "€"]),
    negative=st.sampled_from(["minus", "parens"]),
)
def test_parse_money_inverts_the_generators_formatter(
    amount: Decimal, style: str, symbol: str, negative: str
) -> None:
    assert parse_money(fmt_money(amount, style, symbol, negative)) == amount  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "dayfirst", "expected"),
    [
        ("01 May 2025", True, date(2025, 5, 1)),
        ("31.12.2026", True, date(2026, 12, 31)),
        ("03/04/2026", True, date(2026, 4, 3)),
        ("03/04/2026", False, date(2026, 3, 4)),
        ("11/30/2025", True, date(2025, 11, 30)),  # unambiguous: falls back to month-first
        ("2026-09-01", False, date(2026, 9, 1)),
        ("23-09-2025", True, date(2025, 9, 23)),
        ("Sep 3, 2026", False, date(2026, 9, 3)),
        ("1st May 2026", True, date(2026, 5, 1)),
    ],
)
def test_parse_date(text: str, dayfirst: bool, expected: date) -> None:
    assert parse_date(text, dayfirst=dayfirst) == expected


def test_parse_date_refuses_to_guess() -> None:
    assert parse_date("32/13/2026", dayfirst=True) is None
    assert parse_date("soon", dayfirst=True) is None


def test_currency_and_country() -> None:
    assert parse_currency("usd") == "USD"
    assert parse_currency("£") == "GBP"
    assert parse_currency("dollars") is None
    assert parse_country("United Kingdom") == "GB"
    assert parse_country("Nederland") == "NL"
    assert parse_country("Atlantis") is None
