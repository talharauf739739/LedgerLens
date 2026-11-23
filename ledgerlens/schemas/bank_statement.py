from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from pydantic import BaseModel, model_validator
from pydantic import Field as PydanticField

from ledgerlens.schemas.base import (
    BaseDocument,
    DateField,
    Direction,
    Money,
    MoneyField,
    Source,
    StrField,
    mask_iban,
    mask_identifier,
)


class BankStatementFields(BaseModel):
    bank_name: StrField = PydanticField(default_factory=StrField)
    account_holder: StrField = PydanticField(default_factory=StrField)
    # Stored masked ("****4821"); the document may print the full number.
    account_number_masked: StrField = PydanticField(default_factory=StrField)
    iban_masked: StrField = PydanticField(default_factory=StrField)
    currency: StrField = PydanticField(default_factory=StrField)  # ISO-4217
    period_start: DateField = PydanticField(default_factory=DateField)
    period_end: DateField = PydanticField(default_factory=DateField)
    opening_balance: MoneyField = PydanticField(default_factory=MoneyField)
    closing_balance: MoneyField = PydanticField(default_factory=MoneyField)
    # Summary totals, when the statement prints them.
    total_credits: MoneyField = PydanticField(default_factory=MoneyField)
    total_debits: MoneyField = PydanticField(default_factory=MoneyField)

    @model_validator(mode="before")
    @classmethod
    def _mask(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key, masker in (("account_number_masked", mask_identifier), ("iban_masked", mask_iban)):
            f = data.get(key)
            value = f.get("value") if isinstance(f, dict) else getattr(f, "value", None)
            if isinstance(value, str):
                masked = masker(value)
                data[key] = (
                    {**f, "value": masked}
                    if isinstance(f, dict)
                    else f.model_copy(update={"value": masked})  # type: ignore[union-attr]
                )
        return data


class Transaction(BaseModel):
    date: date
    description: str
    amount: Money = PydanticField(gt=0)  # always positive; sign lives in `direction`
    direction: Direction
    balance: Money | None = None  # running balance, when printed
    source: Source | None = None
    confidence: float = PydanticField(default=0.0, ge=0.0, le=1.0)


class BankStatement(BaseDocument):
    doc_type: ClassVar[str] = "bank_statement"

    fields: BankStatementFields = PydanticField(default_factory=BankStatementFields)
    transactions: list[Transaction] = PydanticField(default_factory=list)
