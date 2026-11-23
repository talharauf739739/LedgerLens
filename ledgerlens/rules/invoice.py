from __future__ import annotations

import re
from decimal import Decimal

from ledgerlens.rules.base import failed, money_eq, passed, run_rules, skipped
from ledgerlens.rules.common import all_values_grounded, currency_is_iso4217
from ledgerlens.schemas.base import RuleResult
from ledgerlens.schemas.invoice import Invoice

# Format checks only (no check-digit algorithms yet). Spaces/dots/dashes are stripped first,
# except for the US EIN which is matched as printed.
TAX_ID_FORMATS: dict[str, re.Pattern[str]] = {
    "GB": re.compile(r"GB(\d{9}|\d{12}|GD\d{3}|HA\d{3})"),
    "DE": re.compile(r"DE\d{9}"),
    "FR": re.compile(r"FR[0-9A-HJ-NP-Z]{2}\d{9}"),
    "NL": re.compile(r"NL\d{9}B\d{2}"),
    "IE": re.compile(r"IE\d{7}[A-W][A-I]?|IE\d[A-Z+*]\d{5}[A-W]"),
    "US": re.compile(r"\d{2}-\d{7}"),  # EIN
}


def line_amounts(doc: Invoice) -> RuleResult:
    """Each line: quantity x unit price = amount (±0.01)."""
    rule = "line_amounts"
    if not doc.line_items:
        return skipped(rule, "line_items")
    bad = [
        i
        for i, li in enumerate(doc.line_items)
        if not money_eq((li.quantity * li.unit_price).quantize(Decimal("0.01")), li.amount)
    ]
    return (
        failed(rule, f"{len(bad)} line(s) where qty x price != amount", bad)
        if bad
        else passed(rule)
    )


def lines_sum_to_subtotal(doc: Invoice) -> RuleResult:
    rule = "lines_sum_to_subtotal"
    subtotal = doc.fields.subtotal.value
    if subtotal is None or not doc.line_items:
        return skipped(rule, "subtotal/line_items")
    s = sum((li.amount for li in doc.line_items), Decimal(0))
    return (
        passed(rule)
        if money_eq(s, subtotal)
        else failed(rule, f"Σ lines {s} != subtotal {subtotal}")
    )


def total_arithmetic(doc: Invoice) -> RuleResult:
    """subtotal + tax - discount = total (missing tax/discount count as 0)."""
    rule = "total_arithmetic"
    f = doc.fields
    if f.subtotal.value is None or f.total.value is None:
        return skipped(rule, "subtotal/total")
    tax = f.tax.value or Decimal(0)
    discount = f.discount.value or Decimal(0)
    expected = f.subtotal.value + tax - discount
    if money_eq(expected, f.total.value):
        return passed(rule)
    return failed(
        rule, f"{f.subtotal.value} + {tax} - {discount} = {expected} != total {f.total.value}"
    )


def due_after_issue(doc: Invoice) -> RuleResult:
    rule = "due_on_or_after_issue"
    issue, due = doc.fields.issue_date.value, doc.fields.due_date.value
    if issue is None or due is None:
        return skipped(rule, "issue_date/due_date")
    return passed(rule) if due >= issue else failed(rule, f"due {due} is before issue {issue}")


def iban_checksum(doc: Invoice) -> RuleResult:
    rule = "iban_mod97"
    ok = doc.fields.seller_iban_checksum_ok
    if ok is None:
        return skipped(rule, "seller_iban")
    return passed(rule) if ok else failed(rule, "IBAN fails the mod-97 check")


def tax_id_format(doc: Invoice) -> RuleResult:
    rule = "tax_id_format"
    tax_id, country = doc.fields.seller_tax_id.value, doc.fields.seller_country.value
    if tax_id is None or country is None:
        return skipped(rule, "seller_tax_id/seller_country")
    pattern = TAX_ID_FORMATS.get(country)
    if pattern is None:
        return skipped(rule, f"no format known for country {country}")
    candidate = tax_id.strip() if country == "US" else re.sub(r"[\s.\-]", "", tax_id).upper()
    if pattern.fullmatch(candidate):
        return passed(rule)
    return failed(rule, f"{tax_id!r} doesn't match the {country} tax-ID format")


RULES = (
    line_amounts,
    lines_sum_to_subtotal,
    total_arithmetic,
    due_after_issue,
    iban_checksum,
    tax_id_format,
    currency_is_iso4217,
    all_values_grounded,
)


def validate(doc: Invoice) -> list[RuleResult]:
    return run_rules(doc, RULES)
