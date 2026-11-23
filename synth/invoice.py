"""Synthetic invoices with exact ground truth (values + bboxes)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from faker import Faker

from ledgerlens.schemas.base import FieldStatus, Source
from ledgerlens.schemas.invoice import Invoice, InvoiceFields, LineItem
from synth.common import (
    CURRENCY_SYMBOL,
    Fonts,
    Generated,
    MoneyStyle,
    PdfWriter,
    SyntheticMeta,
    Tampering,
    digits,
    fake_iban,
    fmt_date,
    fmt_money,
    group4,
    page_size,
    q,
)
from synth.text import latin

DATE_STYLES = {"fr": "%d/%m/%Y", "nl": "%d-%m-%Y"}


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    locale: str
    currency: str
    money: MoneyStyle
    date_style: str
    tax_label: str
    tax_rates: tuple[Decimal, ...]
    tax_id_label: str
    has_iban: bool

    def tax_id(self, rng: random.Random) -> str:
        match self.code:
            case "GB":
                return f"GB {digits(rng, 3)} {digits(rng, 4)} {digits(rng, 2)}"
            case "DE":
                return "DE" + digits(rng, 9)
            case "FR":
                return f"FR {digits(rng, 2)} {digits(rng, 9)}"
            case "NL":
                return f"NL{digits(rng, 9)}B{rng.randint(1, 99):02d}"
            case "US":
                return f"{rng.randint(10, 98)}-{digits(rng, 7)}"
        raise ValueError(self.code)


COUNTRIES = [
    Country(
        "GB",
        "United Kingdom",
        "en_GB",
        "GBP",
        "us",
        "uk",
        "VAT",
        (Decimal("0.20"),),
        "VAT No.",
        True,
    ),
    Country(
        "DE",
        "Deutschland",
        "de_DE",
        "EUR",
        "eu",
        "de",
        "USt.",
        (Decimal("0.19"), Decimal("0.07")),
        "USt-IdNr.",
        True,
    ),
    Country("FR", "France", "fr_FR", "EUR", "eu", "fr", "TVA", (Decimal("0.20"),), "N° TVA", True),
    Country(
        "NL",
        "Nederland",
        "nl_NL",
        "EUR",
        "eu",
        "nl",
        "BTW",
        (Decimal("0.21"), Decimal("0.09")),
        "BTW-nr.",
        True,
    ),
    Country(
        "US",
        "United States",
        "en_US",
        "USD",
        "us",
        "us",
        "Sales tax",
        (Decimal("0"), Decimal("0.0625"), Decimal("0.08875")),
        "EIN",
        False,
    ),
]

ITEMS = [
    ("Consulting services", "hours", 60, 220),
    ("Software licence (annual)", "unit", 300, 2500),
    ("Cloud hosting", "month", 40, 900),
    ("Office chairs", "unit", 90, 450),
    ("Data migration", "hours", 70, 180),
    ("Laptop stand", "unit", 15, 80),
    ("Support retainer", "month", 250, 1500),
    ("Printer paper A4 (box)", "unit", 18, 45),
    ("Security audit", "day", 600, 1400),
    ("Training workshop", "day", 450, 1200),
    ("Domain renewal", "unit", 10, 40),
    ("Design work", "hours", 45, 150),
]

TEMPLATES = ("modern", "compact")


def _grounded(value: Any, box: Source) -> dict[str, Any]:
    return {"value": value, "confidence": 1.0, "source": box, "status": FieldStatus.GROUNDED}


def _fmt_date(d: date, style: str) -> str:
    return d.strftime(DATE_STYLES[style]) if style in DATE_STYLES else fmt_date(d, style)


def generate(seed: int, doc_id: str, tamper: bool = False) -> Generated:
    rng = random.Random(seed)
    country = rng.choice(COUNTRIES)
    template = rng.choice(TEMPLATES)
    fake = Faker(country.locale)
    fake.seed_instance(seed)
    fonts = Fonts.pick(rng)
    sym = CURRENCY_SYMBOL[country.currency]

    def money(x: Decimal, symbol: bool = False) -> str:
        return fmt_money(x, country.money, sym if symbol else "")

    # --- data ------------------------------------------------------------------------
    issue = date(2025, 1, 1) + timedelta(days=rng.randint(0, 700))
    due = issue + timedelta(days=rng.choice([0, 7, 14, 30, 45, 60]))
    number = rng.choice(
        [
            f"INV-{issue.year}-{digits(rng, 5)}",
            f"{issue.year}/{digits(rng, 4)}",
            f"A-{digits(rng, 5)}",
        ]
    )
    lines: list[dict[str, Any]] = []
    for _ in range(rng.choice([rng.randint(1, 6), rng.randint(7, 45)])):
        name, unit, lo, hi = rng.choice(ITEMS)
        qty = q(
            rng.choice([1, 2, 3, 5, 10])
            if unit == "unit"
            else rng.choice([0.5, 1, 1.5, 2, 4, 7.5, 12, 20])
        )
        price = q(rng.uniform(lo, hi))
        detail = f" - {fake.month_name()}" if unit == "month" else ""
        lines.append(
            {
                "description": latin(name + detail),
                "quantity": qty,
                "unit_price": price,
                "amount": q(qty * price),
            }
        )
    subtotal = sum((li["amount"] for li in lines), Decimal(0))
    discount = q(subtotal * Decimal(rng.choice([5, 10])) / 100) if rng.random() < 0.3 else None
    rate = rng.choice(country.tax_rates)
    tax = q((subtotal - (discount or 0)) * rate)
    total = subtotal - (discount or 0) + tax

    tampering: Tampering | None = None
    printed_line_amounts = [li["amount"] for li in lines]
    if tamper:
        trng = random.Random(seed ^ 0x5EED)  # separate stream: rest of the document is identical
        i = trng.randrange(len(lines))
        printed_line_amounts[i] = lines[i]["amount"] + q(trng.uniform(5, 500))
        tampering = Tampering(
            row=i,
            field="amount",
            original=str(lines[i]["amount"]),
            printed=str(printed_line_amounts[i]),
        )

    # --- layout ------------------------------------------------------------------------
    w = PdfWriter(page_size(country.code))
    W = w.width
    f: dict[str, Any] = {}
    printed: dict[str, str] = {}

    def put(key: str, value: Any, text: str, box: Source) -> None:
        f[key] = _grounded(value, box)
        printed[key] = text

    seller = latin(fake.company())
    seller_addr = latin(fake.address()).split("\n")
    seller_x, title_x, title_align = (
        (40, W - 40, "right") if template == "modern" else (W / 2 + 40, 40, "left")
    )
    put("seller_name", seller, seller, w.text(seller_x, 60, seller, fonts.bold, 13))
    y: float = 76
    for line in seller_addr:
        w.text(seller_x, y, line, fonts.regular, 8.5)
        y += 11
    put(
        "seller_country",
        country.code,
        country.name,
        w.text(seller_x, y, country.name, fonts.regular, 8.5),
    )
    y += 11
    tax_id = country.tax_id(rng)
    _, box = w.runs(
        seller_x, y, [(f"{country.tax_id_label} ", fonts.regular), (tax_id, fonts.regular)], 8.5
    )
    put("seller_tax_id", tax_id, tax_id, box)
    # Everything below starts under the seller block, however long its address is.
    top = max(150.0, y + 24)

    title = {"DE": "RECHNUNG", "FR": "FACTURE", "NL": "FACTUUR"}.get(country.code, "INVOICE")
    w.text(title_x, 64, title, fonts.bold, 22, align=title_align)  # type: ignore[arg-type]

    # invoice meta (number / dates)
    mx = W - 230 if template == "modern" else 40
    my = top
    labels = {"invoice_number": "Invoice no.", "issue_date": "Issue date", "due_date": "Due date"}
    values = {
        "invoice_number": (number, number),
        "issue_date": (issue, _fmt_date(issue, country.date_style)),
        "due_date": (due, _fmt_date(due, country.date_style)),
    }
    for key, label in labels.items():
        w.text(mx, my, label, fonts.regular, 9)
        val, txt = values[key]
        put(key, val, txt, w.text(mx + 90, my, txt, fonts.bold, 9))
        my += 13

    bx = 40 if template == "modern" else W / 2 + 40
    w.text(bx, top, "Bill to", fonts.bold, 9)
    buyer = latin(fake.company())
    put("buyer_name", buyer, buyer, w.text(bx, top + 13, buyer, fonts.regular, 9))
    buyer_lines = latin(fake.address()).split("\n")
    for k, line in enumerate(buyer_lines):
        w.text(bx, top + 25 + k * 11, line, fonts.regular, 8.5)
    below = max(top + 25 + len(buyer_lines) * 11, my) + 14

    _, box = w.runs(
        40, below, [("Currency: ", fonts.regular), (country.currency, fonts.regular)], 8.5
    )
    put("currency", country.currency, country.currency, box)

    # --- line items --------------------------------------------------------------------
    cols = (
        ("description", "Description"),
        ("quantity", "Qty"),
        ("unit_price", "Unit price"),
        ("amount", "Amount"),
    )
    if template == "compact":
        cols = (
            ("quantity", "Qty"),
            ("description", "Description"),
            ("unit_price", "Unit price"),
            ("amount", "Line total"),
        )
    widths: dict[str, float] = {"quantity": 50, "unit_price": 85, "amount": 90}
    widths["description"] = (W - 80) - sum(widths.values())
    xs: dict[str, tuple[float, float]] = {}
    x = 40.0
    for c, _ in cols:
        xs[c] = (x, x + widths[c])
        x += widths[c]

    def header(y: float) -> float:
        w.rect(40, y - 10, W - 40, y + 4, gray=0.85)
        for c, label in cols:
            x0, x1 = xs[c]
            if c == "description":
                w.text(x0 + 2, y, label, fonts.bold, 8.5)
            else:
                w.text(x1 - 4, y, label, fonts.bold, 8.5, align="right")
        return y + 16

    def qty_txt(v: Decimal) -> str:
        s = f"{v.normalize():f}"
        return s.replace(".", ",") if country.money == "eu" else s

    y = header(below + 22)
    bottom = w.height - 60
    items: list[LineItem] = []
    for i, li in enumerate(lines):
        if y > bottom:
            w.footer(fonts.regular)
            w.new_page()
            y = header(60)
        desc = w.fit(li["description"], fonts.regular, 8.5, widths["description"] - 6)
        cells = {
            "description": desc,
            "quantity": qty_txt(li["quantity"]),
            "unit_price": money(li["unit_price"]),
            "amount": money(printed_line_amounts[i]),
        }
        row_box: Source | None = None
        for c, txt in cells.items():
            x0, x1 = xs[c]
            b = (
                w.text(x0 + 2, y, txt, fonts.regular, 8.5)
                if c == "description"
                else w.text(x1 - 4, y, txt, fonts.regular, 8.5, align="right")
            )
            row_box = b if row_box is None else row_box.union(b)
        assert row_box is not None
        items.append(
            LineItem(
                description=desc,
                quantity=li["quantity"],
                unit_price=li["unit_price"],
                amount=printed_line_amounts[i],
                source=row_box,
                confidence=1.0,
            )
        )
        y += 14

    # --- totals ------------------------------------------------------------------------
    if y + 110 > w.height - 40:
        w.footer(fonts.regular)
        w.new_page()
        y = 60
    y += 8
    w.hline(W - 260, W - 40, y - 10)
    tax_label = f"{country.tax_label} {(rate * 100).normalize():f}%"
    totals: list[tuple[str, str, Decimal | None]] = [
        ("subtotal", "Subtotal", subtotal),
        ("discount", "Discount", discount),
        ("tax", tax_label, tax),
        ("total", "Total due", total),
    ]
    for key, label, amount in totals:
        if amount is None:
            continue
        bold = key == "total"
        w.text(W - 250, y, label, fonts.bold if bold else fonts.regular, 9.5 if bold else 9)
        txt = money(-amount if key == "discount" else amount, symbol=True)
        box = w.text(
            W - 44, y, txt, fonts.bold if bold else fonts.regular, 9.5 if bold else 9, align="right"
        )
        put(key, amount, txt, box)
        y += 15

    if country.has_iban:
        iban = group4(fake_iban(rng, country.code))
        _, box = w.runs(
            40, y + 20, [("Payment to IBAN: ", fonts.regular), (iban, fonts.regular)], 8.5
        )
        put("seller_iban_masked", iban, iban, box)
    w.text(
        40, y + 34, f"Payment terms: due by {_fmt_date(due, country.date_style)}.", fonts.regular, 8
    )
    w.footer(fonts.regular)

    doc = Invoice(fields=InvoiceFields.model_validate(f), line_items=items)
    meta = SyntheticMeta(
        id=doc_id,
        doc_type="invoice",
        variant="tampered" if tamper else "clean",
        seed=seed,
        template=f"{template}_{country.code.lower()}",
        printed=printed,
        tampering=tampering,
        expected_failures=["line_amounts", "lines_sum_to_subtotal"] if tamper else [],
    )
    return Generated(pdf=w.save(), document=doc, meta=meta)
