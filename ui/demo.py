"""Demo-screen logic, free of Streamlit so it can be unit-tested.

The demo tells one story: AI reads the document, code proves every number. Each scenario
shows one capability a client can see for themselves: fraud caught by arithmetic, an
invented number blocked, OCR on a crooked scan, healthcare documents read with receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from ledgerlens.pipeline.ground import GroundingReport
from ledgerlens.pipeline.spans import ParsedDocument
from ledgerlens.rules.base import money_eq
from ledgerlens.schemas import BaseDocument, RuleStatus
from ledgerlens.schemas.base import FieldStatus
from ui.review import field_items, rows_attr

# --- scenarios ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    teaser: str  # one line under the title in the picker
    story: str  # what the presenter says while it's on screen
    sector: Literal["Fintech", "Healthcare"]
    source: str  # synthetic sample stem, or a file path relative to the repo root
    from_file: bool = False
    read_only: bool = False  # OCR view only (no schema for this type yet)
    hallucinate: str | None = None  # field the stand-in AI will invent


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "fraud",
        "Tampered bank statement",
        "Fraud caught by the math",
        "Someone edited one transaction on this statement. It still looks normal to the eye, "
        "but LedgerLens redoes the arithmetic from the printed numbers: the balances no longer "
        "add up, so the document is stopped and sent to a person.",
        "Fintech",
        "bank_statement_00000_tampered",
    ),
    Scenario(
        "hallucination",
        "AI invents a number",
        "A made-up value is blocked",
        "Here the AI model reports a closing balance that is printed nowhere on the page. A "
        "typical AI pipeline would pass it straight into your systems. LedgerLens looks for it "
        "on the page, asks the model once more, and when it still can't find it, removes it "
        "and sends the document to review.",
        "Fintech",
        "bank_statement_00000",
        hallucinate="closing_balance",
    ),
    Scenario(
        "clean",
        "Clean bank statement",
        "Every number proven",
        "Every value is found on the page and every finance check passes, so this statement "
        "is ready to approve. Click any row under Receipts to see exactly where it came from.",
        "Fintech",
        "bank_statement_00000",
    ),
    Scenario(
        "scan",
        "Scanned invoice",
        "OCR on a crooked scan",
        "A scanned, slightly rotated invoice with no text layer. OCR reads it, the page is "
        "straightened, and every value still gets an exact receipt on the image.",
        "Fintech",
        "invoice_00000_noisy",
    ),
    Scenario(
        "hospital",
        "Hospital bill (phone photo)",
        "Healthcare: every word located",
        "A phone photo of an itemised hospital bill. LedgerLens reads every word and its "
        "position. Search for any term and it lights up on the page. Healthcare schemas and "
        "rules (charges minus payments equals balance) use the same receipts approach.",
        "Healthcare",
        "App_Test/healthcare/images/hospital_bill_1_photo.jpg",
        from_file=True,
        read_only=True,
    ),
    Scenario(
        "lab",
        "Lab report (scan)",
        "Healthcare: results and ranges",
        "A scanned lab report: test names, results, flags and reference ranges, read with OCR "
        "and kept in their table columns.",
        "Healthcare",
        "App_Test/healthcare/images/lab_report_2_scan.png",
        from_file=True,
        read_only=True,
    ),
)


def hallucinate(draft: dict[str, Any], field: str) -> tuple[dict[str, Any], str]:
    """A copy of `draft` where `field` has one digit changed: a plausible number that isn't
    printed anywhere. Returns (draft, invented value)."""
    out = dict(draft)
    value = str(out[field])
    for i, ch in enumerate(value):
        if ch.isdigit() and ch != "0":
            new = "8" if ch == "9" else str(int(ch) + 1)
            invented = value[:i] + new + value[i + 1 :]
            out[field] = invented
            return out, invented
    raise ValueError(f"{field} has no digit to change: {value!r}")


# --- headline numbers ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    fields_proven: int
    fields_total: int
    rows_proven: int
    rows_total: int
    checks_passed: int
    checks_run: int
    removed: list[str]  # values the AI gave that weren't on the page
    ready: bool


def stats(doc: BaseDocument, grounding: GroundingReport) -> Stats:
    fields = [
        f for _, f in field_items(doc) if f.value is not None or f.status is FieldStatus.UNGROUNDED
    ]
    proven = sum(f.status in (FieldStatus.GROUNDED, FieldStatus.CORRECTED) for f in fields)
    rows = getattr(doc, rows_attr(doc))
    run = [r for r in doc.validation if r.status is not RuleStatus.SKIP]
    passed = sum(r.status is RuleStatus.PASS for r in run)
    removed = [n for n, f in field_items(doc) if f.status is FieldStatus.UNGROUNDED]
    failed = any(r.status is RuleStatus.FAIL for r in run)
    return Stats(
        fields_proven=proven,
        fields_total=len(fields),
        rows_proven=sum(r.source is not None for r in rows),
        rows_total=len(rows),
        checks_passed=passed,
        checks_run=len(run),
        removed=removed,
        ready=not failed and not removed and not grounding.rows_ungrounded,
    )


# --- the pipeline as a timeline -----------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    name: str
    ms: int
    what: str
    flag: bool = False  # something the audience should notice


def pipeline_steps(trace: list[dict[str, Any]]) -> list[Step]:
    """One tile per stage; a retried extract/ground shows as one tile with x2."""
    order = ["parse", "classify", "extract", "ground", "validate"]
    by: dict[str, list[dict[str, Any]]] = {}
    for entry in trace:
        by.setdefault(entry["step"], []).append(entry)
    steps: list[Step] = []
    for name in order:
        entries = by.get(name, [])
        if not entries:
            continue
        last, ms = entries[-1], sum(int(e.get("ms", 0)) for e in entries)
        times = f" (x{len(entries)})" if len(entries) > 1 else ""
        if name == "parse":
            ocr = last.get("scanned", 0)
            what = f"{last.get('pages', 0)} page(s), " + (
                f"{ocr} read with OCR" if ocr else "digital text layer"
            )
            steps.append(Step("Read", ms, what))
        elif name == "classify":
            how = "keyword cues, no AI needed" if last.get("method") == "cues" else "asked the AI"
            what = f"{str(last.get('doc_type', '')).replace('_', ' ')}: {how}"
            steps.append(Step("Classify", ms, what))
        elif name == "extract":
            steps.append(Step("Extract" + times, ms, "AI copies printed values", len(entries) > 1))
        elif name == "ground":
            missing = len(last.get("ungrounded", [])) + len(last.get("rows_ungrounded", []))
            what = f"{last.get('grounded', 0)} values found on the page" + (
                f", {missing} not found" if missing else ""
            )
            steps.append(Step("Find on page" + times, ms, what, bool(missing)))
        else:
            failed = last.get("failed", [])
            what = f"{len(failed)} check(s) failed" if failed else "all checks passed"
            steps.append(Step("Prove the math", ms, what, bool(failed)))
    return steps


# --- prove the math ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ProofLine:
    label: str
    amount: Decimal | None
    sign: str = ""  # "+", "-", "=" or ""


@dataclass(frozen=True)
class Proof:
    title: str
    lines: list[ProofLine]
    computed_label: str
    computed: Decimal | None
    printed_label: str
    printed: Decimal | None
    ok: bool | None  # None: can't be proven (a value has no receipt)


def _v(doc: BaseDocument, name: str) -> Decimal | None:
    value = getattr(getattr(doc, "fields"), name).value  # noqa: B009
    return value if isinstance(value, Decimal) else None


def proof(doc: BaseDocument) -> Proof | None:
    """The headline equation for the document, recomputed from what is printed."""
    if doc.doc_type == "bank_statement":
        txs = getattr(doc, "transactions")  # noqa: B009
        credits = sum((t.amount for t in txs if t.direction == "credit"), Decimal(0))
        debits = sum((t.amount for t in txs if t.direction == "debit"), Decimal(0))
        opening, closing = _v(doc, "opening_balance"), _v(doc, "closing_balance")
        computed = None if opening is None else opening + credits - debits
        return Proof(
            "Balance roll-forward",
            [
                ProofLine("Opening balance (printed)", opening),
                ProofLine(
                    f"Money in ({sum(t.direction == 'credit' for t in txs)} rows)", credits, "+"
                ),
                ProofLine(
                    f"Money out ({sum(t.direction == 'debit' for t in txs)} rows)", debits, "-"
                ),
            ],
            "Closing balance, recomputed",
            computed,
            "Closing balance (printed)",
            closing,
            None if computed is None or closing is None else money_eq(computed, closing),
        )
    if doc.doc_type == "invoice":
        items = getattr(doc, "line_items")  # noqa: B009
        lines_sum = sum((i.amount for i in items), Decimal(0))
        subtotal, tax = _v(doc, "subtotal"), _v(doc, "tax")
        discount, total = _v(doc, "discount") or Decimal(0), _v(doc, "total")
        computed = None if subtotal is None else subtotal + (tax or Decimal(0)) - discount
        lines = [
            ProofLine(f"Line items ({len(items)})", lines_sum),
            ProofLine("Subtotal (printed)", subtotal),
            ProofLine("Tax", tax, "+"),
        ]
        if discount:
            lines.append(ProofLine("Discount", discount, "-"))
        ok = None
        if computed is not None and total is not None and subtotal is not None:
            ok = money_eq(computed, total) and money_eq(lines_sum, subtotal)
        return Proof(
            "Invoice total", lines, "Total, recomputed", computed, "Total (printed)", total, ok
        )
    return None


# --- search the page (read-only view) ------------------------------------------------------------


def search_spans(parsed: ParsedDocument, query: str) -> list[int]:
    """Indexes into `parsed.spans` of words matching any term in `query` (case-insensitive)."""
    terms = [t for t in query.lower().replace(",", " ").split() if len(t) >= 2]
    if not terms:
        return []
    return [i for i, s in enumerate(parsed.spans) if any(t in s.text.lower() for t in terms)]
