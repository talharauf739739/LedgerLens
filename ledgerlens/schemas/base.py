"""Building blocks shared by every document schema.

Coordinates: ``bbox`` is ``[x0, y0, x1, y1]`` in PDF points (1/72 inch) with the origin at
the **top-left** of the page; ``page`` is 1-based. Scanned pages use the same space (the
page's size in points), so grounding never needs to know how a page was produced.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer, model_validator
from pydantic import Field as PydanticField

T = TypeVar("T")

# Money is Decimal, serialised as a string with exactly what was quantised (never a float).
Money = Annotated[Decimal, PlainSerializer(lambda d: str(d), return_type=str, when_used="json")]


class Source(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = PydanticField(ge=1)
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def _ordered(self) -> Source:
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError(f"bbox must be [x0, y0, x1, y1] with x0<=x1, y0<=y1, got {self.bbox}")
        return self

    def union(self, other: Source) -> Source:
        if other.page != self.page:
            raise ValueError("can't union boxes on different pages")
        a, b = self.bbox, other.bbox
        return Source(
            page=self.page,
            bbox=(min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])),
        )


class FieldStatus(StrEnum):
    GROUNDED = "grounded"  # value matched an OCR span at `source`
    UNGROUNDED = (
        "ungrounded"  # model proposed a value we couldn't find: value is null, needs review
    )
    MISSING = "missing"  # not present on the document
    CORRECTED = "corrected"  # a human reviewer set the value


class Field(BaseModel, Generic[T]):
    """One extracted value with its receipt."""

    value: T | None = None
    confidence: float = PydanticField(default=0.0, ge=0.0, le=1.0)
    source: Source | None = None
    status: FieldStatus = FieldStatus.MISSING

    @model_validator(mode="after")
    def _receipt_required(self) -> Field[T]:
        if self.status is FieldStatus.GROUNDED and (self.value is None or self.source is None):
            raise ValueError("a grounded field needs both a value and a source")
        if self.status is FieldStatus.UNGROUNDED and self.value is not None:
            raise ValueError("an ungrounded field must have value=None (never guess)")
        return self


class RuleStatus(StrEnum):
    PASS = "pass"  # noqa: S105 (a rule status, not a password)
    FAIL = "fail"
    WARN = "warn"  # suspicious but legitimately possible
    SKIP = "skip"  # inputs missing; not evidence either way


class RuleResult(BaseModel):
    rule: str
    status: RuleStatus
    detail: str = ""
    rows: list[int] = PydanticField(default_factory=list)  # 0-based row indexes involved


class BaseDocument(BaseModel):
    """Every document type: typed `fields`, its own row lists, rule results and Markdown."""

    doc_type: ClassVar[str]
    validation: list[RuleResult] = PydanticField(default_factory=list)
    markdown: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _check_doc_type(cls, data: Any) -> Any:
        if isinstance(data, dict) and "doc_type" in data:
            if data["doc_type"] != cls.doc_type:
                raise ValueError(f"doc_type {data['doc_type']!r} != {cls.doc_type!r}")
            data = {k: v for k, v in data.items() if k != "doc_type"}
        return data

    def model_dump_doc(self, **kwargs: Any) -> dict[str, Any]:
        """JSON-ready dict with `doc_type` first, as stored and returned by the API."""
        return {"doc_type": self.doc_type, **self.model_dump(mode="json", **kwargs)}


# --- identifiers: stored masked, checksum kept as a derived flag ---------------------------

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")


def mask_identifier(raw: str, keep: int = 4) -> str:
    """'12345678' -> '****5678'. Already-masked values pass through unchanged."""
    if raw.startswith("*") or "*" in raw:
        return raw
    clean = _NON_ALNUM.sub("", raw)
    return "****" + clean[-keep:]


def mask_iban(raw: str) -> str:
    """'GB29 LLNS 6016 1331 9268 19' -> 'GB****6819' (country code + last 4)."""
    if "*" in raw:
        return raw
    clean = _NON_ALNUM.sub("", raw).upper()
    return clean[:2] + "****" + clean[-4:]


def iban_is_valid(raw: str) -> bool:
    """ISO 13616 mod-97 check."""
    clean = _NON_ALNUM.sub("", raw).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", clean):
        return False
    rearranged = clean[4:] + clean[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


DateField = Field[date]
MoneyField = Field[Money]
StrField = Field[str]
Direction = Literal["credit", "debit"]
