from __future__ import annotations

from decimal import Decimal

from ledgerlens.rules.base import failed, money_eq, passed, run_rules, skipped, warned
from ledgerlens.rules.common import all_values_grounded, currency_is_iso4217
from ledgerlens.schemas.bank_statement import BankStatement, Transaction
from ledgerlens.schemas.base import RuleResult


def _signed(t: Transaction) -> Decimal:
    return t.amount if t.direction == "credit" else -t.amount


def balance_roll_forward(doc: BankStatement) -> RuleResult:
    """opening + Σcredits - Σdebits = closing (±0.01)."""
    rule = "balance_roll_forward"
    opening, closing = doc.fields.opening_balance.value, doc.fields.closing_balance.value
    if opening is None or closing is None:
        return skipped(rule, "opening_balance/closing_balance")
    if not doc.transactions:
        return skipped(rule, "transactions")
    expected = opening + sum((_signed(t) for t in doc.transactions), Decimal(0))
    if money_eq(expected, closing):
        return passed(rule)
    return failed(
        rule, f"opening {opening} + net {expected - opening} = {expected} != closing {closing}"
    )


def running_balance_consistency(doc: BankStatement) -> RuleResult:
    """Each printed running balance = previous balance ± this row's amount."""
    rule = "running_balance_consistency"
    prev = doc.fields.opening_balance.value
    if prev is None or not any(t.balance is not None for t in doc.transactions):
        return skipped(rule, "opening_balance/row balances")
    bad: list[int] = []
    for i, t in enumerate(doc.transactions):
        expected = prev + _signed(t)
        if t.balance is None:
            prev = expected  # unprinted balance: carry the computed one
            continue
        if not money_eq(expected, t.balance):
            bad.append(i)
        prev = t.balance  # resync so one bad row is reported once, not cascaded
    if bad:
        return failed(rule, f"{len(bad)} row(s) don't follow from the previous balance", bad)
    return passed(rule)


def dates_within_period(doc: BankStatement) -> RuleResult:
    rule = "dates_within_period"
    start, end = doc.fields.period_start.value, doc.fields.period_end.value
    if start is None or end is None:
        return skipped(rule, "period_start/period_end")
    if start > end:
        return failed(rule, f"period_start {start} is after period_end {end}")
    bad = [i for i, t in enumerate(doc.transactions) if not start <= t.date <= end]
    if bad:
        return failed(rule, f"{len(bad)} transaction(s) outside {start}..{end}", bad)
    return passed(rule)


def no_duplicate_rows(doc: BankStatement) -> RuleResult:
    """Adjacent identical rows (same date, description, amount, direction, balance).

    The usual cause is a row repeated across a page break. Identical running balances on
    consecutive rows are impossible for a non-zero amount, so this is a WARN only when
    balances aren't printed.
    """
    rule = "no_duplicate_rows"
    dupes: list[int] = []
    for i in range(1, len(doc.transactions)):
        a, b = doc.transactions[i - 1], doc.transactions[i]
        if (a.date, a.description, a.amount, a.direction, a.balance) == (
            b.date,
            b.description,
            b.amount,
            b.direction,
            b.balance,
        ):
            dupes.append(i)
    if not dupes:
        return passed(rule)
    if all(doc.transactions[i].balance is not None for i in dupes):
        return failed(rule, "row repeated (likely across a page break)", dupes)
    return warned(rule, "identical adjacent rows; may be genuine repeat payments", dupes)


def printed_totals_match(doc: BankStatement) -> RuleResult:
    rule = "printed_totals_match"
    tc, td = doc.fields.total_credits.value, doc.fields.total_debits.value
    if tc is None and td is None:
        return skipped(rule, "total_credits/total_debits")
    credits = sum((t.amount for t in doc.transactions if t.direction == "credit"), Decimal(0))
    debits = sum((t.amount for t in doc.transactions if t.direction == "debit"), Decimal(0))
    problems = []
    if tc is not None and not money_eq(tc, credits):
        problems.append(f"credits printed {tc} vs rows {credits}")
    if td is not None and not money_eq(td, debits):
        problems.append(f"debits printed {td} vs rows {debits}")
    return failed(rule, "; ".join(problems)) if problems else passed(rule)


RULES = (
    balance_roll_forward,
    running_balance_consistency,
    dates_within_period,
    no_duplicate_rows,
    printed_totals_match,
    currency_is_iso4217,
    all_values_grounded,
)


def validate(doc: BankStatement) -> list[RuleResult]:
    return run_rules(doc, RULES)
