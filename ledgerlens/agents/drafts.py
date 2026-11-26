"""What the extractor LLM fills in: every value is a string copied *as printed*.

`to_document` turns a draft into a typed document with deterministic normalisation
(ledgerlens.normalize). Values come out with status PROPOSED and no source; grounding
(phase 3) attaches receipts or nulls them. Unparseable values become missing, never guessed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField

from ledgerlens.normalize import (
    clean_text,
    parse_country,
    parse_currency,
    parse_date,
    parse_money,
)
from ledgerlens.schemas import BankStatement, BaseDocument, Invoice
from ledgerlens.schemas.base import FieldStatus


class _Draft(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TransactionDraft(_Draft):
    date: str | None = PydanticField(None, description="Transaction date exactly as printed")
    description: str | None = PydanticField(None, description="Description/details text")
    amount: str | None = PydanticField(
        None, description="The row's amount exactly as printed, including any minus sign/brackets"
    )
    direction: Literal["credit", "debit"] | None = PydanticField(
        None,
        description=(
            "'debit' if the amount is in a money-out/withdrawals/debit column or printed "
            "negative; 'credit' if in a money-in/deposits/credit column or positive"
        ),
    )
    balance: str | None = PydanticField(None, description="Running balance as printed, if any")


class BankStatementDraft(_Draft):
    bank_name: str | None = None
    account_holder: str | None = None
    account_number: str | None = None
    iban: str | None = None
    currency: str | None = PydanticField(None, description="Currency code or symbol as printed")
    period_start: str | None = None
    period_end: str | None = None
    opening_balance: str | None = None
    closing_balance: str | None = None
    total_credits: str | None = PydanticField(None, description="Printed total money in, if any")
    total_debits: str | None = PydanticField(None, description="Printed total money out, if any")
    transactions: list[TransactionDraft] = PydanticField(default_factory=list)


class LineItemDraft(_Draft):
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = PydanticField(None, description="Line total exactly as printed")


class InvoiceDraft(_Draft):
    invoice_number: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    seller_name: str | None = None
    seller_tax_id: str | None = PydanticField(None, description="VAT / tax ID / EIN as printed")
    seller_country: str | None = PydanticField(None, description="Seller's country as printed")
    seller_iban: str | None = None
    buyer_name: str | None = None
    currency: str | None = PydanticField(None, description="Currency code or symbol as printed")
    subtotal: str | None = None
    discount: str | None = None
    tax: str | None = None
    total: str | None = None
    line_items: list[LineItemDraft] = PydanticField(default_factory=list)


DRAFTS: dict[str, type[_Draft]] = {
    "bank_statement": BankStatementDraft,
    "invoice": InvoiceDraft,
}


# --- draft -> typed document -------------------------------------------------------------


# Schema field name -> draft key, where they differ (identifiers are masked in the schema).
DRAFT_KEY: dict[str, str] = {
    "account_number_masked": "account_number",
    "iban_masked": "iban",
    "seller_iban_masked": "seller_iban",
}


def draft_key(field_name: str) -> str:
    return DRAFT_KEY.get(field_name, field_name)


def _proposed(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {"value": value, "status": FieldStatus.PROPOSED}


def _dayfirst(currency: str | None) -> bool:
    # Month-first is a US convention; everything else we support is day-first.
    return currency != "USD"


def _abs(d: Decimal | None) -> Decimal | None:
    return None if d is None else abs(d)


def bank_statement_from_draft(d: BankStatementDraft) -> tuple[BankStatement, list[str]]:
    issues: list[str] = []
    cur = parse_currency(d.currency)
    df = _dayfirst(cur)
    f: dict[str, Any] = {
        "bank_name": _proposed(clean_text(d.bank_name)),
        "account_holder": _proposed(clean_text(d.account_holder)),
        "account_number_masked": _proposed(clean_text(d.account_number)),
        "iban_masked": _proposed(clean_text(d.iban)),
        "currency": _proposed(cur),
        "period_start": _proposed(parse_date(d.period_start, dayfirst=df)),
        "period_end": _proposed(parse_date(d.period_end, dayfirst=df)),
        "opening_balance": _proposed(parse_money(d.opening_balance)),
        "closing_balance": _proposed(parse_money(d.closing_balance)),
        "total_credits": _proposed(_abs(parse_money(d.total_credits))),
        "total_debits": _proposed(_abs(parse_money(d.total_debits))),
    }
    txns: list[dict[str, Any]] = []
    for i, t in enumerate(d.transactions):
        day = parse_date(t.date, dayfirst=df)
        amount = parse_money(t.amount)
        if day is None or amount is None or amount == 0:
            issues.append(f"transaction {i}: unparseable date/amount {t.date!r} {t.amount!r}")
            continue
        direction = t.direction or ("debit" if amount < 0 else "credit")
        if amount < 0 and direction == "credit":
            issues.append(f"transaction {i}: negative amount marked credit; using debit")
            direction = "debit"
        txns.append(
            {
                "date": day,
                "description": clean_text(t.description) or "",
                "amount": abs(amount),
                "direction": direction,
                "balance": parse_money(t.balance),
            }
        )
    doc = BankStatement.model_validate({"fields": f, "transactions": txns})
    return doc, issues


def invoice_from_draft(d: InvoiceDraft) -> tuple[Invoice, list[str]]:
    issues: list[str] = []
    cur = parse_currency(d.currency)
    df = _dayfirst(cur)
    f: dict[str, Any] = {
        "invoice_number": _proposed(clean_text(d.invoice_number)),
        "issue_date": _proposed(parse_date(d.issue_date, dayfirst=df)),
        "due_date": _proposed(parse_date(d.due_date, dayfirst=df)),
        "seller_name": _proposed(clean_text(d.seller_name)),
        "seller_tax_id": _proposed(clean_text(d.seller_tax_id)),
        "seller_country": _proposed(parse_country(d.seller_country)),
        "seller_iban_masked": _proposed(clean_text(d.seller_iban)),
        "buyer_name": _proposed(clean_text(d.buyer_name)),
        "currency": _proposed(cur),
        "subtotal": _proposed(parse_money(d.subtotal)),
        "discount": _proposed(_abs(parse_money(d.discount))),  # printed as "-£12.00"
        "tax": _proposed(parse_money(d.tax)),
        "total": _proposed(parse_money(d.total)),
    }
    items: list[dict[str, Any]] = []
    for i, li in enumerate(d.line_items):
        qty, price, amount = (
            parse_money(li.quantity),
            parse_money(li.unit_price),
            parse_money(li.amount),
        )
        if qty is None or price is None or amount is None:
            issues.append(
                f"line {i}: unparseable {li.quantity!r} x {li.unit_price!r} = {li.amount!r}"
            )
            continue
        items.append(
            {
                "description": clean_text(li.description) or "",
                "quantity": qty,
                "unit_price": price,
                "amount": amount,
            }
        )
    doc = Invoice.model_validate({"fields": f, "line_items": items})
    return doc, issues


def to_document(doc_type: str, draft: _Draft) -> tuple[BaseDocument, list[str]]:
    if isinstance(draft, BankStatementDraft):
        return bank_statement_from_draft(draft)
    if isinstance(draft, InvoiceDraft):
        return invoice_from_draft(draft)
    raise ValueError(f"no converter for {doc_type}")
