"""Review-screen logic, kept free of Streamlit so it can be unit-tested.

A reviewer sees every value with its receipt (a box on the page), the finance checks, and
can correct a value. Corrections are normalised exactly like model output (code decides the
type), marked CORRECTED, and the rules re-run. Decisions are saved for the audit log.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, get_args

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pydantic import BaseModel
from pydantic import Field as PydanticField

from ledgerlens.normalize import clean_text, parse_country, parse_currency, parse_date, parse_money
from ledgerlens.rules import validate
from ledgerlens.schemas import BaseDocument, RuleStatus
from ledgerlens.schemas.base import Field, FieldStatus

STATUS_COLOR = {
    FieldStatus.GROUNDED: (22, 163, 74),  # green
    FieldStatus.CORRECTED: (37, 99, 235),  # blue
    FieldStatus.PROPOSED: (217, 119, 6),  # amber
    FieldStatus.UNGROUNDED: (220, 38, 38),  # red
}
SELECTED = (147, 51, 234)  # purple


@dataclass(frozen=True)
class Highlight:
    page: int
    bbox: tuple[float, float, float, float]
    color: tuple[int, int, int]
    selected: bool = False


def render_page(
    pdf: bytes, page: int, highlights: list[Highlight], scale: float = 1.6
) -> Image.Image:
    """The page as an image with translucent boxes over each receipt (PDF points -> px)."""
    doc = pdfium.PdfDocument(pdf)
    try:
        img = doc[page - 1].render(scale=scale).to_pil().convert("RGBA")
    finally:
        doc.close()
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for h in highlights:
        if h.page != page:
            continue
        x0, y0, x1, y1 = (round(v * scale) for v in h.bbox)
        pad = 3 if h.selected else 1
        box = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        color = SELECTED if h.selected else h.color
        draw.rectangle(
            box,
            fill=(*color, 70 if h.selected else 40),
            outline=(*color, 255),
            width=3 if h.selected else 1,
        )
    return Image.alpha_composite(img, overlay).convert("RGB")


def field_items(doc: BaseDocument) -> list[tuple[str, Field[Any]]]:
    fields = getattr(doc, "fields")  # noqa: B009
    return [
        (name, f)
        for name in type(fields).model_fields
        if isinstance(f := getattr(fields, name), Field)
    ]


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def field_rows(doc: BaseDocument) -> list[dict[str, Any]]:
    return [
        {
            "field": name,
            "value": _display(f.value),
            "status": f.status.value,
            "confidence": round(f.confidence, 3),
            "page": f.source.page if f.source else None,
        }
        for name, f in field_items(doc)
        if f.value is not None or f.status is not FieldStatus.MISSING
    ]


def rows_attr(doc: BaseDocument) -> str:
    return "transactions" if hasattr(doc, "transactions") else "line_items"


def row_records(doc: BaseDocument) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(getattr(doc, rows_attr(doc))):
        values = row.model_dump(exclude={"source", "confidence"})
        rec: dict[str, Any] = {"#": i, **{k: _display(v) for k, v in values.items()}}
        rec["receipt"] = "yes" if row.source else "MISSING"
        out.append(rec)
    return out


def highlights(doc: BaseDocument, selected: str | None = None) -> list[Highlight]:
    hs = [
        Highlight(f.source.page, f.source.bbox, STATUS_COLOR[f.status], name == selected)
        for name, f in field_items(doc)
        if f.source is not None
    ]
    hs += [
        Highlight(r.source.page, r.source.bbox, (100, 116, 139), f"row {i}" == selected)
        for i, r in enumerate(getattr(doc, rows_attr(doc)))
        if r.source is not None
    ]
    return hs


# Header fields each rule checks. Row-level rules (running balance, line amounts) point at
# rows instead, which the Checks tab lists by index.
RULE_FIELDS: dict[str, tuple[str, ...]] = {
    "balance_roll_forward": ("opening_balance", "closing_balance"),
    "printed_totals_match": ("total_credits", "total_debits"),
    "dates_within_period": ("period_start", "period_end"),
    "lines_sum_to_subtotal": ("subtotal",),
    "total_arithmetic": ("subtotal", "discount", "tax", "total"),
    "due_on_or_after_issue": ("issue_date", "due_date"),
    "iban_mod97": ("seller_iban_masked",),
    "tax_id_format": ("seller_tax_id", "seller_country"),
    "currency_iso4217": ("currency",),
}


def needs_attention(doc: BaseDocument) -> list[str]:
    """Fields a reviewer should look at: ungrounded ones and those checked by failed rules."""
    names = {name for name, f in field_items(doc) if f.status is FieldStatus.UNGROUNDED}
    for r in doc.validation:
        if r.status is RuleStatus.FAIL:
            names |= set(RULE_FIELDS.get(r.rule, ()))
    return [
        name
        for name, f in field_items(doc)
        if name in names and (f.value is not None or f.status is FieldStatus.UNGROUNDED)
    ]


def _field_type(doc: BaseDocument, name: str) -> Any:
    fields_cls = type(getattr(doc, "fields"))  # noqa: B009
    annotation = fields_cls.model_fields[name].annotation
    value_type = annotation.model_fields["value"].annotation
    args = [a for a in get_args(value_type) if a is not type(None)]
    base = args[0] if args else value_type
    return get_args(base)[0] if get_args(base) else base  # unwrap Annotated[Decimal, ...]


def apply_correction(doc: BaseDocument, name: str, text: str) -> tuple[BaseDocument, str | None]:
    """Set a field from what the reviewer typed. Returns (new document, error message)."""
    t = _field_type(doc, name)
    currency = getattr(getattr(doc, "fields"), "currency", None)  # noqa: B009
    dayfirst = getattr(currency, "value", None) != "USD"
    value: Any
    if t is Decimal:
        value = parse_money(text)
    elif t is date:
        value = parse_date(text, dayfirst=dayfirst)
    elif name == "currency":
        value = parse_currency(text)
    elif name == "seller_country":
        value = parse_country(text)
    else:
        value = clean_text(text)
    if value is None:
        return doc, f"Couldn't read {text!r} as a {getattr(t, '__name__', 'value')} for {name}."
    fields = getattr(doc, "fields")  # noqa: B009
    corrected = getattr(fields, name).model_copy(
        update={"value": value, "status": FieldStatus.CORRECTED, "confidence": 1.0}
    )
    new_fields = fields.model_copy(update={name: corrected})
    new_doc = doc.model_copy(update={"fields": new_fields})
    return new_doc.model_copy(update={"validation": validate(new_doc)}), None


class Correction(BaseModel):
    field: str
    value: str


class ReviewDecision(BaseModel):
    document_sha256: str
    doc_type: str
    decision: Literal["approved", "rejected"]
    reviewer: str
    comment: str = ""
    corrections: list[Correction] = []
    failed_rules: list[str] = []
    decided_at: datetime = PydanticField(default_factory=lambda: datetime.now(UTC))


def make_decision(
    doc: BaseDocument,
    sha256: str,
    decision: Literal["approved", "rejected"],
    reviewer: str,
    comment: str,
    corrections: list[Correction],
) -> ReviewDecision:
    return ReviewDecision(
        document_sha256=sha256,
        doc_type=doc.doc_type,
        decision=decision,
        reviewer=reviewer.strip() or "anonymous",
        comment=comment.strip(),
        corrections=corrections,
        failed_rules=[r.rule for r in doc.validation if r.status is RuleStatus.FAIL],
        decided_at=datetime.now(UTC),
    )


def save_decision(decision: ReviewDecision, doc: BaseDocument, root: Path) -> Path:
    """Write the decision and the reviewed document as JSON (one file per document).

    Local stand-in for the PostgreSQL audit log; the worker writes the same record there.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{decision.document_sha256[:16]}.json"
    payload = {
        "decision": decision.model_dump(mode="json"),
        "document": doc.model_dump_doc(exclude={"markdown"}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def image_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
