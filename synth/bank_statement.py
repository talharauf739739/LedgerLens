"""Synthetic bank statements with exact ground truth (values + bboxes)."""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from faker import Faker

from ledgerlens.schemas.bank_statement import BankStatement, BankStatementFields, Transaction
from ledgerlens.schemas.base import FieldStatus, Source
from synth.common import (
    CURRENCY_SYMBOL,
    Fonts,
    Generated,
    MoneyStyle,
    PdfWriter,
    SyntheticMeta,
    Tampering,
    bank_name,
    digits,
    fake_iban,
    fmt_date,
    fmt_money,
    group4,
    page_size,
    q,
)
from synth.text import latin


@dataclass(frozen=True)
class Template:
    name: str
    country: str
    locale: str
    currency: str
    money: MoneyStyle
    date_style: str
    columns: tuple[str, ...]  # subset/order of: date, description, debit, credit, amount, balance
    labels: dict[str, str]
    print_totals: bool
    print_iban: bool
    currency_phrase: str  # how the currency code is introduced


TEMPLATES = [
    Template(
        "classic_us",
        "US",
        "en_US",
        "USD",
        "us",
        "us",
        ("date", "description", "debit", "credit", "balance"),
        {
            "date": "Date",
            "description": "Description",
            "debit": "Withdrawals",
            "credit": "Deposits",
            "balance": "Balance",
        },
        print_totals=False,
        print_iban=False,
        currency_phrase="All amounts in ",
    ),
    Template(
        "uk_money_in_out",
        "GB",
        "en_GB",
        "GBP",
        "us",
        "uk",
        ("date", "description", "debit", "credit", "balance"),
        {
            "date": "Date",
            "description": "Details",
            "debit": "Money out",
            "credit": "Money in",
            "balance": "Balance",
        },
        print_totals=True,
        print_iban=True,
        currency_phrase="Currency: ",
    ),
    Template(
        "eu_signed",
        "DE",
        "de_DE",
        "EUR",
        "eu",
        "de",
        ("date", "amount", "description", "balance"),
        {
            "date": "Datum",
            "amount": "Betrag",
            "description": "Verwendungszweck",
            "balance": "Saldo",
        },
        print_totals=False,
        print_iban=True,
        currency_phrase="Währung: ",
    ),
]

COLUMN_WIDTH = {
    "date": 70,
    "description": 0,
    "debit": 72,
    "credit": 72,
    "amount": 80,
    "balance": 80,
}
NUMERIC = {"debit", "credit", "amount", "balance"}

_DEBIT_KINDS = ["CARD PAYMENT", "DIRECT DEBIT", "STANDING ORDER", "TRANSFER TO", "ONLINE PAYMENT"]


def _grounded(value: Any, box: Source) -> dict[str, Any]:
    return {"value": value, "confidence": 1.0, "source": box, "status": FieldStatus.GROUNDED}


def _transactions(
    rng: random.Random, fake: Faker, start: date, end: date, opening: Decimal
) -> list[dict[str, Any]]:
    days = (end - start).days
    n = rng.randint(12, 75)
    employer = latin(fake.company()).upper()
    rows: list[dict[str, Any]] = []
    for payday in sorted(rng.sample(range(days + 1), k=rng.choice([1, 2]))):
        rows.append(
            {
                "date": start + timedelta(days=payday),
                "description": f"SALARY {employer}",
                "amount": q(rng.uniform(1800, 6500)),
                "direction": "credit",
            }
        )
    for _ in range(n - len(rows)):
        if rng.random() < 0.08:
            desc, amt, direction = (
                "TRANSFER FROM " + latin(fake.name()).upper(),
                q(rng.uniform(20, 900)),
                "credit",
            )
        elif rng.random() < 0.06:
            desc, amt, direction = (
                "ATM WITHDRAWAL",
                q(rng.choice([20, 40, 50, 60, 100, 200])),
                "debit",
            )
        else:
            payee = latin(fake.company() if rng.random() < 0.8 else fake.name()).upper()
            desc = f"{rng.choice(_DEBIT_KINDS)} {payee}"
            amt, direction = q(min(rng.lognormvariate(3.3, 1.0), 1500) + 1), "debit"
        rows.append(
            {
                "date": start + timedelta(days=rng.randint(0, days)),
                "description": desc,
                "amount": amt,
                "direction": direction,
            }
        )
    rows.sort(key=lambda r: r["date"])  # stable: keeps payroll first on its day
    bal = opening
    for r in rows:
        bal += r["amount"] if r["direction"] == "credit" else -r["amount"]
        r["balance"] = bal
    return rows


def generate(seed: int, doc_id: str, tamper: bool = False) -> Generated:
    rng = random.Random(seed)
    tpl = rng.choice(TEMPLATES)
    fake = Faker(tpl.locale)
    fake.seed_instance(seed)
    fonts = Fonts.pick(rng)

    year, month = rng.choice([2025, 2026]), rng.randint(1, 12)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    opening = q(rng.uniform(300, 9000))
    rows = _transactions(rng, fake, start, end, opening)
    closing = rows[-1]["balance"]

    tampering: Tampering | None = None
    printed_amounts = [r["amount"] for r in rows]
    if tamper:
        trng = random.Random(seed ^ 0x5EED)  # separate stream: rest of the document is identical
        i = trng.randrange(len(rows))
        delta = q(trng.choice([trng.uniform(1, 9), trng.uniform(10, 99), trng.uniform(100, 900)]))
        printed_amounts[i] = rows[i]["amount"] + delta
        tampering = Tampering(
            row=i, field="amount", original=str(rows[i]["amount"]), printed=str(printed_amounts[i])
        )

    sym = CURRENCY_SYMBOL[tpl.currency]

    def money(x: Decimal, symbol: bool = False) -> str:
        return fmt_money(x, tpl.money, sym if symbol else "")

    w = PdfWriter(page_size(tpl.country))
    W = w.width
    f: dict[str, Any] = {}
    printed: dict[str, str] = {}

    def put(key: str, value: Any, text: str, box: Source) -> None:
        f[key] = _grounded(value, box)
        printed[key] = text

    # --- header ------------------------------------------------------------------------
    name = bank_name(rng)
    put("bank_name", name, name, w.text(40, 58, name, fonts.bold, 17))
    w.text(40, 72, latin(fake.address().replace("\n", ", ")), fonts.regular, 7.5)
    w.hline(40, W - 40, 84, 1)

    holder = latin(fake.name())
    put("account_holder", holder, holder, w.text(40, 110, holder, fonts.bold, 10))
    for k, line in enumerate(latin(fake.address()).split("\n")):
        w.text(40, 124 + k * 12, line, fonts.regular, 9)

    x_info, y = W / 2 + 30, 110.0
    acct = digits(rng, 8)
    _, box = w.runs(x_info, y, [("Account number: ", fonts.regular), (acct, fonts.bold)], 9)
    put("account_number_masked", acct, acct, box)
    y += 13
    if tpl.print_iban:
        iban = group4(fake_iban(rng, tpl.country))
        _, box = w.runs(x_info, y, [("IBAN: ", fonts.regular), (iban, fonts.regular)], 9)
        put("iban_masked", iban, iban, box)
        y += 13
    s_txt, e_txt = fmt_date(start, tpl.date_style), fmt_date(end, tpl.date_style)
    _, b_start, _, b_end = w.runs(
        x_info,
        y,
        [
            ("Statement period: ", fonts.regular),
            (s_txt, fonts.regular),
            (" to ", fonts.regular),
            (e_txt, fonts.regular),
        ],
        9,
    )
    put("period_start", start, s_txt, b_start)
    put("period_end", end, e_txt, b_end)
    y += 13
    _, box = w.runs(
        x_info, y, [(tpl.currency_phrase, fonts.regular), (tpl.currency, fonts.regular)], 9
    )
    put("currency", tpl.currency, tpl.currency, box)

    # --- summary -------------------------------------------------------------------------
    y = 185.0
    w.rect(40, y - 12, W - 40, y + (62 if tpl.print_totals else 30))
    summary = [
        ("opening_balance", "Opening balance", opening),
        ("closing_balance", "Closing balance", closing),
    ]
    if tpl.print_totals:
        credits = sum((r["amount"] for r in rows if r["direction"] == "credit"), Decimal(0))
        debits = sum((r["amount"] for r in rows if r["direction"] == "debit"), Decimal(0))
        summary[1:1] = [
            ("total_credits", "Total money in", credits),
            ("total_debits", "Total money out", debits),
        ]
    for key, label, amount in summary:
        w.text(50, y, label, fonts.regular, 9)
        txt = money(amount, symbol=True)
        put(key, amount, txt, w.text(W - 50, y, txt, fonts.bold, 9, align="right"))
        y += 16

    # --- transaction table -------------------------------------------------------------
    fixed = sum(COLUMN_WIDTH[c] for c in tpl.columns if c != "description")
    desc_w = (W - 80) - fixed
    xs: dict[str, tuple[float, float]] = {}
    x = 40.0
    for c in tpl.columns:
        cw = desc_w if c == "description" else COLUMN_WIDTH[c]
        xs[c] = (x, x + cw)
        x += cw

    # Text columns that follow a right-aligned number column need a gutter.
    pad = {
        c: (14.0 if k and tpl.columns[k - 1] in NUMERIC else 2.0) for k, c in enumerate(tpl.columns)
    }

    def header(y: float) -> float:
        w.rect(40, y - 10, W - 40, y + 4, gray=0.85)
        for c in tpl.columns:
            x0, x1 = xs[c]
            if c in NUMERIC:
                w.text(x1 - 4, y, tpl.labels[c], fonts.bold, 8.5, align="right")
            else:
                w.text(x0 + pad[c], y, tpl.labels[c], fonts.bold, 8.5)
        return y + 16

    def carry_line(y: float, label: str, bal: Decimal) -> None:
        w.text(xs[tpl.columns[1]][0] + 2, y, label, fonts.regular, 8)
        w.text(xs["balance"][1] - 4, y, money(bal), fonts.regular, 8, align="right")

    y = header(y + 14)
    bottom = w.height - 56
    txns: list[Transaction] = []
    bal_before = opening
    for i, r in enumerate(rows):
        if y > bottom:
            carry_line(y, "Balance carried forward", bal_before)
            w.footer(fonts.regular)
            w.new_page()
            y = header(60)
            carry_line(y, "Balance brought forward", bal_before)
            y += 14
        amt = printed_amounts[i]
        cells: dict[str, str] = {
            "date": fmt_date(r["date"], tpl.date_style),
            "description": w.fit(
                r["description"], fonts.regular, 8, desc_w - pad["description"] - 4
            ),
            "balance": money(r["balance"]),
        }
        if "amount" in tpl.columns:
            cells["amount"] = money(amt if r["direction"] == "credit" else -amt)
        else:
            cells["debit" if r["direction"] == "debit" else "credit"] = money(amt)
        row_box: Source | None = None
        for c, txt in cells.items():
            x0, x1 = xs[c]
            b = (
                w.text(x1 - 4, y, txt, fonts.regular, 8, align="right")
                if c in NUMERIC
                else w.text(x0 + pad[c], y, txt, fonts.regular, 8)
            )
            row_box = b if row_box is None else row_box.union(b)
        assert row_box is not None
        txns.append(
            Transaction(
                date=r["date"],
                description=cells["description"],
                amount=amt,
                direction=r["direction"],
                balance=r["balance"],
                source=row_box,
                confidence=1.0,
            )
        )
        bal_before = r["balance"]
        y += 13
    w.footer(fonts.regular)

    doc = BankStatement(
        fields=BankStatementFields.model_validate(f),
        transactions=txns,
    )
    expected: list[str] = []
    if tampering:
        expected = ["balance_roll_forward", "running_balance_consistency"]
        if tpl.print_totals:
            expected.append("printed_totals_match")
    meta = SyntheticMeta(
        id=doc_id,
        doc_type="bank_statement",
        variant="tampered" if tamper else "clean",
        seed=seed,
        template=tpl.name,
        printed=printed,
        tampering=tampering,
        expected_failures=expected,
    )
    return Generated(pdf=w.save(), document=doc, meta=meta)
