from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, model_validator
from pydantic import Field as PydanticField

from ledgerlens.schemas.base import (
    BaseDocument,
    DateField,
    Money,
    MoneyField,
    Source,
    StrField,
    iban_is_valid,
    mask_iban,
)


class InvoiceFields(BaseModel):
    invoice_number: StrField = PydanticField(default_factory=StrField)
    issue_date: DateField = PydanticField(default_factory=DateField)
    due_date: DateField = PydanticField(default_factory=DateField)
    seller_name: StrField = PydanticField(default_factory=StrField)
    seller_tax_id: StrField = PydanticField(
        default_factory=StrField
    )  # business ID: kept as printed
    seller_country: StrField = PydanticField(default_factory=StrField)  # ISO-3166 alpha-2
    # Stored masked ("GB****6819"). The mod-97 result is computed from the printed value
    # before masking and kept in `seller_iban_checksum_ok`, so the raw IBAN is never stored.
    seller_iban_masked: StrField = PydanticField(default_factory=StrField)
    seller_iban_checksum_ok: bool | None = None
    buyer_name: StrField = PydanticField(default_factory=StrField)
    currency: StrField = PydanticField(default_factory=StrField)  # ISO-4217
    subtotal: MoneyField = PydanticField(default_factory=MoneyField)
    discount: MoneyField = PydanticField(default_factory=MoneyField)
    tax: MoneyField = PydanticField(default_factory=MoneyField)
    total: MoneyField = PydanticField(default_factory=MoneyField)

    @model_validator(mode="before")
    @classmethod
    def _mask_iban(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        f = data.get("seller_iban_masked")
        value = f.get("value") if isinstance(f, dict) else getattr(f, "value", None)
        if isinstance(value, str) and "*" not in value:
            data["seller_iban_checksum_ok"] = iban_is_valid(value)
            masked = mask_iban(value)
            data["seller_iban_masked"] = (
                {**f, "value": masked}
                if isinstance(f, dict)
                else f.model_copy(update={"value": masked})  # type: ignore[union-attr]
            )
        return data


class LineItem(BaseModel):
    description: str
    quantity: Money  # Decimal: hours and kg are fractional
    unit_price: Money
    amount: Money  # as printed on the line
    source: Source | None = None
    confidence: float = PydanticField(default=0.0, ge=0.0, le=1.0)


class Invoice(BaseDocument):
    doc_type: ClassVar[str] = "invoice"

    fields: InvoiceFields = PydanticField(default_factory=InvoiceFields)
    line_items: list[LineItem] = PydanticField(default_factory=list)
