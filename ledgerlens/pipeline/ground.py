"""Grounding: give every proposed value a receipt, or take it away.

For each field the extractor proposed, look for the text it claims was printed among the
parsed spans (text layer or OCR). A match attaches the page + bbox and makes the field
GROUNDED; no match nulls the value and marks it UNGROUNDED for human review. Rows
(transactions, line items) must have their key values on one printed line.

Matching is typed where it can be: money and dates are compared as values (so "$1,234.50"
matches spans "$" "1,234.50"), text fuzzily (rapidfuzz >= 90) to tolerate OCR slips.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from rapidfuzz import fuzz

from ledgerlens.agents.drafts import draft_key
from ledgerlens.normalize import parse_date, parse_money
from ledgerlens.pipeline.spans import Line, ParsedDocument, Span
from ledgerlens.schemas import BaseDocument
from ledgerlens.schemas.base import Field, FieldStatus, Source

TEXT_MIN_SCORE = 90.0
MAX_EXTRA_WORDS = 2  # a candidate may span a couple more words than the printed value


# Extra label words per field, on top of the words in the field's own name. Used only to
# break ties when the same value is printed in several places (e.g. due date == issue date).
LABEL_WORDS: dict[str, tuple[str, ...]] = {
    "tax": ("vat", "tax", "tva", "btw", "ust", "mwst"),
    "seller_tax_id": ("vat", "ust", "tva", "btw", "ein", "tax"),
    "total": ("total", "due", "amount"),
    "invoice_number": ("invoice", "no", "number", "nr", "rechnung", "facture", "factuur"),
    "issue_date": ("issue", "invoice", "dated"),
    "due_date": ("due", "payable"),
    "period_start": ("period", "from"),
    "period_end": ("period", "to"),
    "total_credits": ("in", "credits", "deposits"),
    "total_debits": ("out", "debits", "withdrawals"),
    "account_number_masked": ("account",),
    "iban_masked": ("iban",),
    "seller_iban_masked": ("iban",),
}
_IGNORED_NAME_WORDS = {"masked", "seller", "buyer", "name"}


def label_words(field_name: str) -> set[str]:
    own = {w for w in field_name.split("_") if w not in _IGNORED_NAME_WORDS}
    return own | set(LABEL_WORDS.get(field_name, ()))


@dataclass(frozen=True)
class Candidate:
    text: str
    spans: tuple[Span, ...]
    line_text: str = ""

    def label_hits(self, words: set[str]) -> int:
        context = re.findall(r"[a-z]+", self.line_text.lower().replace(self.text.lower(), " "))
        return len(words & set(context))

    @property
    def source(self) -> Source:
        s = self.spans
        return Source(
            page=s[0].page,
            bbox=(
                min(x.bbox[0] for x in s),
                min(x.bbox[1] for x in s),
                max(x.bbox[2] for x in s),
                max(x.bbox[3] for x in s),
            ),
        )

    @property
    def ocr_confidence(self) -> float:
        return min(x.confidence for x in self.spans)


@dataclass
class GroundingReport:
    grounded: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)
    rows_grounded: int = 0
    rows_ungrounded: list[int] = field(default_factory=list)


def _compact(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", "", s)


def _ngrams(line: Line, max_len: int) -> list[Candidate]:
    spans = line.spans
    out = []
    for i in range(len(spans)):
        for j in range(i + 1, min(len(spans), i + max_len) + 1):
            chunk = spans[i:j]
            out.append(Candidate(" ".join(s.text for s in chunk), chunk, line.text))
    return out


class Grounder:
    """Index a parsed document once, then ground any number of values against it."""

    def __init__(self, parsed: ParsedDocument, *, dayfirst: bool) -> None:
        self.parsed = parsed
        self.dayfirst = dayfirst
        self.lines = [line for page in parsed.pages for line in page.lines]

    # --- single values ---------------------------------------------------------------

    def _candidates(self, printed: str) -> list[Candidate]:
        n = len(printed.split()) + MAX_EXTRA_WORDS
        return [c for line in self.lines for c in _ngrams(line, n)]

    def find(
        self, value: Any, printed: str | None, field_name: str = ""
    ) -> tuple[Candidate, float] | None:
        """Best candidate for a proposed value, with a 0-1 match score.

        Ranking: match score, then how many of the field's label words share the line
        (so "Due date 25 Sep" beats "Issue date 25 Sep" for `due_date`), then the
        tightest box."""
        if printed is None or value is None:
            return None
        words = label_words(field_name)
        best: tuple[Candidate, float] | None = None
        best_key: tuple[float, int, int] | None = None
        target = _compact(printed)
        for cand in self._candidates(printed):
            score = self._score(value, target, cand)
            if score <= 0:
                continue
            key = (score, cand.label_hits(words), -len(cand.spans))
            if best_key is None or key > best_key:
                best, best_key = (cand, score), key
        return best

    def _score(self, value: Any, target: str, cand: Candidate) -> float:
        text = _compact(cand.text)
        if isinstance(value, (Decimal, date)):
            if isinstance(value, Decimal):
                got = parse_money(cand.text)
                same = got is not None and abs(got) == abs(value)
            else:
                same = parse_date(cand.text, dayfirst=self.dayfirst) == value
            if not same:
                return 0.0
            # Same value: an exact match of the printed text ("£81.97") beats the same
            # number elsewhere ("81.97" in a table), so equal amounts land in the right place.
            return 1.0 if text == target else 0.99
        if not text:
            return 0.0
        if text == target:
            return 1.0
        ratio = fuzz.ratio(target, text)
        return ratio / 100 if ratio >= TEXT_MIN_SCORE else 0.0

    # --- rows --------------------------------------------------------------------------

    def find_row(self, keys: list[Any], used: set[int]) -> tuple[Line, float] | None:
        """The first unused line that contains every typed key (money/date) of a row."""
        for idx, line in enumerate(self.lines):
            if idx in used:
                continue
            cands = _ngrams(line, 3)
            if all(any(self._score(k, "", c) > 0 for c in cands) for k in keys if k is not None):
                used.add(idx)
                return line, min(s.confidence for s in line.spans)
        return None


def _line_source(line: Line) -> Source:
    return Source(page=line.page, bbox=line.bbox)


def ground_document(
    doc: BaseDocument, draft: dict[str, Any], parsed: ParsedDocument
) -> tuple[BaseDocument, GroundingReport]:
    """Return a copy of `doc` where every value is GROUNDED (with source) or UNGROUNDED."""
    currency = getattr(getattr(doc, "fields", None), "currency", None)
    dayfirst = getattr(currency, "value", None) != "USD"
    g = Grounder(parsed, dayfirst=dayfirst)
    report = GroundingReport()

    fields_model = getattr(doc, "fields")  # noqa: B009 (every document type has `fields`)
    updates: dict[str, Any] = {}
    for name in type(fields_model).model_fields:
        f = getattr(fields_model, name)
        if not isinstance(f, Field) or f.value is None:
            continue
        printed = draft.get(draft_key(name))
        hit = g.find(f.value, printed if isinstance(printed, str) else None, name)
        if hit is None:
            updates[name] = f.model_copy(
                update={
                    "value": None,
                    "source": None,
                    "confidence": 0.0,
                    "status": FieldStatus.UNGROUNDED,
                }
            )
            report.ungrounded.append(name)
            continue
        cand, score = hit
        updates[name] = f.model_copy(
            update={
                "source": cand.source,
                "status": FieldStatus.GROUNDED,
                "confidence": round(score * cand.ocr_confidence, 4),
            }
        )
        report.grounded.append(name)
    new_fields = fields_model.model_copy(update=updates)

    rows_attr = "transactions" if hasattr(doc, "transactions") else "line_items"
    used: set[int] = set()
    new_rows: list[BaseModel] = []
    for i, row in enumerate(getattr(doc, rows_attr)):
        if rows_attr == "transactions":
            keys = [row.date, row.amount, row.balance]
        else:
            keys = [row.unit_price, row.amount]
        found = g.find_row(keys, used)
        if found is None:
            report.rows_ungrounded.append(i)
            new_rows.append(row.model_copy(update={"source": None, "confidence": 0.0}))
            continue
        line, conf = found
        report.rows_grounded += 1
        new_rows.append(
            row.model_copy(update={"source": _line_source(line), "confidence": round(conf, 4)})
        )
    grounded = doc.model_copy(update={"fields": new_fields, rows_attr: new_rows})
    return grounded, report
