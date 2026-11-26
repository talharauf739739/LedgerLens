"""Parser contract: text-layer and OCR paths give the same evidence and the same tables."""

import re

import pytest

from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.pipeline.spans import Span, group_lines, lines_to_markdown
from synth import GENERATORS
from synth.noise import make_noisy, rotate_point


def _table_rows(markdown: str) -> list[list[str]]:
    rows = []
    for line in markdown.splitlines():
        if line.startswith("| ") and not line.startswith("| ---"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


@pytest.mark.parametrize("seed", range(6))
def test_statement_table_keeps_money_in_and_out_columns(seed: int) -> None:
    gen = GENERATORS["bank_statement"](seed, "t")
    parsed = parse_pdf(gen.pdf)
    assert all(p.kind == "digital" for p in parsed.pages)
    rows = _table_rows(parsed.markdown)
    header = rows[0]
    data = [r for r in rows if r != header and re.search(r"\d", r[0])]
    assert len(data) == len(gen.document.transactions)
    if "Betrag" in header:  # signed single amount column
        return
    out_col = next(i for i, h in enumerate(header) if h in {"Withdrawals", "Money out"})
    in_col = next(i for i, h in enumerate(header) if h in {"Deposits", "Money in"})
    for row, txn in zip(data, gen.document.transactions, strict=True):
        filled = out_col if txn.direction == "debit" else in_col
        empty = in_col if txn.direction == "debit" else out_col
        assert row[filled] and not row[empty], (row, txn.direction)


def test_scanned_page_parses_like_the_clean_one() -> None:
    clean = GENERATORS["invoice"](4, "t")
    noisy = make_noisy(clean, 4)
    a, b = parse_pdf(clean.pdf), parse_pdf(noisy.pdf)
    assert a.pages[0].kind == "digital" and b.pages[0].kind == "scanned"
    true_angle = -noisy.meta.noise["rotation_deg"][1]  # PIL's CCW angle -> our slope sign
    assert abs(b.pages[0].skew_deg - true_angle) < 0.5
    rows_a, rows_b = _table_rows(a.markdown), _table_rows(b.markdown)
    assert len(rows_a) == len(rows_b)
    same = sum(ra == rb for ra, rb in zip(rows_a, rows_b, strict=True))
    assert same / len(rows_a) >= 0.9  # OCR may misread the odd character


def test_group_lines_undoes_skew() -> None:
    # Two rows of three words, rotated 3 degrees: without deskew the right-hand words
    # would drift into the next row.
    size, angle = (600.0, 800.0), 3.0
    spans = []
    for row, y in enumerate((100.0, 112.0)):
        for col, x in enumerate((50.0, 300.0, 550.0)):
            # place on a page whose text slopes down to the right by `angle`
            cx, cy = rotate_point(x, y, 300, 400, -angle)
            spans.append(
                Span(
                    text=f"r{row}c{col}",
                    page=1,
                    bbox=(cx - 10, cy - 4, cx + 10, cy + 4),
                    origin="ocr",
                )
            )
    flat = group_lines(spans, 1)
    straight = group_lines(spans, 1, skew_deg=angle, size=size)
    assert [line.text for line in straight] == ["r0c0 r0c1 r0c2", "r1c0 r1c1 r1c2"]
    assert [line.text for line in flat] != [line.text for line in straight]


def test_markdown_table_keeps_empty_cells() -> None:
    def span(text: str, x0: float, x1: float, y: float) -> Span:
        return Span(text=text, page=1, bbox=(x0, y, x1, y + 8), origin="pdf")

    spans = [
        span("Date", 40, 60, 100),
        span("Out", 200, 220, 100),
        span("In", 300, 312, 100),
        span("Balance", 400, 440, 100),
        span("01/02/2026", 40, 90, 115),
        span("12.00", 195, 220, 115),
        span("88.00", 415, 440, 115),
        span("02/02/2026", 40, 90, 130),
        span("50.00", 287, 312, 130),
        span("138.00", 410, 440, 130),
    ]
    md = lines_to_markdown(group_lines(spans, 1))
    assert "| 01/02/2026 | 12.00 |  | 88.00 |" in md
    assert "| 02/02/2026 |  | 50.00 | 138.00 |" in md


def test_page_limit() -> None:
    gen = GENERATORS["bank_statement"](1, "t")  # 2 pages
    with pytest.raises(ValueError, match="limit"):
        parse_pdf(gen.pdf, max_pages=1)
