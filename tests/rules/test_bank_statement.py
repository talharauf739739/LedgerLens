from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from ledgerlens.rules.bank_statement import (
    balance_roll_forward,
    dates_within_period,
    no_duplicate_rows,
    printed_totals_match,
    running_balance_consistency,
    validate,
)
from ledgerlens.schemas import BankStatement, RuleStatus, Source

BOX = Source(page=1, bbox=(0, 0, 10, 10))
START, END = date(2026, 9, 1), date(2026, 9, 30)

amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2)
rows_st = st.lists(
    st.tuples(amounts, st.sampled_from(["credit", "debit"]), st.integers(0, 29)),
    min_size=1,
    max_size=60,
)


def g(value: Any) -> dict[str, Any]:
    return {"value": value, "confidence": 1.0, "source": BOX, "status": "grounded"}


def build(
    opening: Decimal, rows: list[tuple[Decimal, str, int]], *, totals: bool = True
) -> BankStatement:
    bal = opening
    txns = []
    for amount, direction, day in sorted(rows, key=lambda r: r[2]):
        bal += amount if direction == "credit" else -amount
        txns.append(
            {
                "date": START + timedelta(days=day),
                "description": f"ROW {len(txns)}",
                "amount": amount,
                "direction": direction,
                "balance": bal,
                "source": BOX,
            }
        )
    fields: dict[str, Any] = {
        "currency": g("USD"),
        "period_start": g(START),
        "period_end": g(END),
        "opening_balance": g(opening),
        "closing_balance": g(bal),
    }
    if totals:
        fields["total_credits"] = g(
            sum((t["amount"] for t in txns if t["direction"] == "credit"), Decimal(0))
        )
        fields["total_debits"] = g(
            sum((t["amount"] for t in txns if t["direction"] == "debit"), Decimal(0))
        )
    return BankStatement.model_validate({"fields": fields, "transactions": txns})


@given(opening=amounts, rows=rows_st)
def test_consistent_statement_passes_every_rule(
    opening: Decimal, rows: list[tuple[Decimal, str, int]]
) -> None:
    results = validate(build(opening, rows))
    assert all(r.status is RuleStatus.PASS for r in results), [
        r for r in results if r.status is not RuleStatus.PASS
    ]


@given(opening=amounts, rows=rows_st, data=st.data())
def test_tampered_amount_is_caught_at_that_row(
    opening: Decimal, rows: list[tuple[Decimal, str, int]], data: st.DataObject
) -> None:
    doc = build(opening, rows)
    i = data.draw(st.integers(0, len(doc.transactions) - 1))
    delta = data.draw(st.decimals(min_value=Decimal("0.02"), max_value=Decimal("500"), places=2))
    doc.transactions[i] = doc.transactions[i].model_copy(
        update={"amount": doc.transactions[i].amount + delta}
    )

    assert balance_roll_forward(doc).status is RuleStatus.FAIL
    running = running_balance_consistency(doc)
    assert running.status is RuleStatus.FAIL
    assert running.rows == [i]  # reported once, not cascaded to later rows
    assert printed_totals_match(doc).status is RuleStatus.FAIL


def test_tolerance_is_one_cent() -> None:
    doc = build(Decimal("100.00"), [(Decimal("10.00"), "debit", 3)])
    doc.fields.closing_balance.value = Decimal("90.01")
    assert balance_roll_forward(doc).status is RuleStatus.PASS
    doc.fields.closing_balance.value = Decimal("90.02")
    assert balance_roll_forward(doc).status is RuleStatus.FAIL


def test_missing_inputs_skip_not_fail() -> None:
    doc = BankStatement()
    for rule in (
        balance_roll_forward,
        running_balance_consistency,
        dates_within_period,
        printed_totals_match,
    ):
        assert rule(doc).status is RuleStatus.SKIP


def test_date_outside_period() -> None:
    doc = build(Decimal("100.00"), [(Decimal("5.00"), "debit", 2), (Decimal("5.00"), "debit", 4)])
    doc.transactions[1] = doc.transactions[1].model_copy(update={"date": date(2026, 10, 2)})
    r = dates_within_period(doc)
    assert r.status is RuleStatus.FAIL and r.rows == [1]


def test_row_repeated_across_page_break() -> None:
    doc = build(Decimal("100.00"), [(Decimal("5.00"), "debit", 2), (Decimal("7.00"), "debit", 4)])
    doc.transactions.insert(1, doc.transactions[0])
    r = no_duplicate_rows(doc)
    assert r.status is RuleStatus.FAIL and r.rows == [1]
