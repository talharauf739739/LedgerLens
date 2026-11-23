from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledgerlens.rules.invoice import (
    due_after_issue,
    iban_checksum,
    line_amounts,
    lines_sum_to_subtotal,
    tax_id_format,
    total_arithmetic,
    validate,
)
from ledgerlens.schemas import Invoice, RuleStatus, Source

BOX = Source(page=1, bbox=(0, 0, 10, 10))
CENT = Decimal("0.01")

money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999.99"), places=2)
qty = st.decimals(min_value=Decimal("0.5"), max_value=Decimal("100"), places=1)
lines_st = st.lists(st.tuples(qty, money), min_size=1, max_size=40)


def g(value: Any) -> dict[str, Any]:
    return {"value": value, "confidence": 1.0, "source": BOX, "status": "grounded"}


def build(
    lines: list[tuple[Decimal, Decimal]],
    rate: Decimal = Decimal("0.20"),
    discount: Decimal | None = None,
) -> Invoice:
    items = [
        {
            "description": f"Item {i}",
            "quantity": q,
            "unit_price": p,
            "amount": (q * p).quantize(CENT),
            "source": BOX,
        }
        for i, (q, p) in enumerate(lines)
    ]
    subtotal = sum((i["amount"] for i in items), Decimal(0))
    tax = ((subtotal - (discount or 0)) * rate).quantize(CENT)
    fields: dict[str, Any] = {
        "invoice_number": g("INV-1"),
        "issue_date": g(date(2026, 1, 5)),
        "due_date": g(date(2026, 2, 4)),
        "seller_tax_id": g("DE123456789"),
        "seller_country": g("DE"),
        "seller_iban_masked": g("DE89 3704 0044 0532 0130 00"),
        "currency": g("EUR"),
        "subtotal": g(subtotal),
        "tax": g(tax),
        "total": g(subtotal - (discount or 0) + tax),
    }
    if discount is not None:
        fields["discount"] = g(discount)
    return Invoice.model_validate({"fields": fields, "line_items": items})


@given(
    lines=lines_st,
    rate=st.sampled_from([Decimal(0), Decimal("0.07"), Decimal("0.19"), Decimal("0.20")]),
    discount=st.one_of(
        st.none(), st.decimals(min_value=Decimal("0.01"), max_value=Decimal("5"), places=2)
    ),
)
def test_consistent_invoice_passes_every_rule(
    lines: list[tuple[Decimal, Decimal]], rate: Decimal, discount: Decimal | None
) -> None:
    results = validate(build(lines, rate, discount))
    assert all(r.status is RuleStatus.PASS for r in results), [
        r for r in results if r.status is not RuleStatus.PASS
    ]


@given(lines=lines_st, data=st.data())
def test_tampered_line_amount_is_caught(
    lines: list[tuple[Decimal, Decimal]], data: st.DataObject
) -> None:
    doc = build(lines)
    i = data.draw(st.integers(0, len(doc.line_items) - 1))
    li = doc.line_items[i]
    doc.line_items[i] = li.model_copy(update={"amount": li.amount + Decimal("1.00")})
    r = line_amounts(doc)
    assert r.status is RuleStatus.FAIL and r.rows == [i]
    assert lines_sum_to_subtotal(doc).status is RuleStatus.FAIL
    assert total_arithmetic(doc).status is RuleStatus.PASS  # totals block itself is untouched


def test_due_before_issue_fails() -> None:
    doc = build([(Decimal(1), Decimal(10))])
    doc.fields.due_date.value = date(2025, 12, 31)
    assert due_after_issue(doc).status is RuleStatus.FAIL


def test_bad_iban_fails() -> None:
    doc = Invoice.model_validate(
        {"fields": {"seller_iban_masked": g("DE89 3704 0044 0532 0130 01")}}
    )
    assert iban_checksum(doc).status is RuleStatus.FAIL


@pytest.mark.parametrize(
    ("country", "tax_id", "ok"),
    [
        ("GB", "GB 123 4567 89", True),
        ("GB", "GB12345678", False),
        ("DE", "DE123456789", True),
        ("DE", "DE12345678", False),
        ("FR", "FR 12 123456789", True),
        ("NL", "NL123456789B01", True),
        ("US", "12-3456789", True),
        ("US", "123456789", False),
    ],
)
def test_tax_id_formats(country: str, tax_id: str, ok: bool) -> None:
    doc = Invoice.model_validate(
        {"fields": {"seller_tax_id": g(tax_id), "seller_country": g(country)}}
    )
    assert (tax_id_format(doc).status is RuleStatus.PASS) is ok
