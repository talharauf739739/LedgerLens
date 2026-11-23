from decimal import Decimal

import pytest
from pydantic import ValidationError

from ledgerlens.schemas import REGISTRY, BankStatement, Invoice, Source
from ledgerlens.schemas.base import Field, FieldStatus, iban_is_valid, mask_iban, mask_identifier

BOX = Source(page=1, bbox=(10, 10, 50, 20))


def g(value: object) -> dict[str, object]:
    return {"value": value, "confidence": 1.0, "source": BOX, "status": "grounded"}


def test_registry() -> None:
    assert REGISTRY == {"bank_statement": BankStatement, "invoice": Invoice}


@pytest.mark.parametrize(
    ("iban", "ok"),
    [
        ("GB82 WEST 1234 5698 7654 32", True),  # ISO 13616 documentation example
        ("DE89 3704 0044 0532 0130 00", True),  # documentation example
        ("GB82 WEST 1234 5698 7654 33", False),
        ("not an iban", False),
    ],
)
def test_iban_mod97(iban: str, ok: bool) -> None:
    assert iban_is_valid(iban) is ok


def test_masking() -> None:
    assert mask_identifier("12 3456 4821") == "****4821"
    assert mask_identifier("****4821") == "****4821"
    assert mask_iban("GB82 WEST 1234 5698 7654 32") == "GB****5432"


def test_bank_statement_masks_account_and_iban() -> None:
    doc = BankStatement.model_validate(
        {
            "fields": {
                "account_number_masked": g("12345678"),
                "iban_masked": g("GB82 WEST 1234 5698 7654 32"),
            }
        }
    )
    assert doc.fields.account_number_masked.value == "****5678"
    assert doc.fields.iban_masked.value == "GB****5432"
    dumped = doc.model_dump_json()
    assert "12345678" not in dumped and "WEST" not in dumped


def test_invoice_keeps_checksum_but_not_raw_iban() -> None:
    bad = Invoice.model_validate(
        {"fields": {"seller_iban_masked": g("GB82 WEST 1234 5698 7654 33")}}
    )
    assert bad.fields.seller_iban_checksum_ok is False
    assert bad.fields.seller_iban_masked.value == "GB****5433"
    # Re-validating the stored (masked) form keeps the flag.
    again = Invoice.model_validate(bad.model_dump(mode="json"))
    assert again.fields.seller_iban_checksum_ok is False


def test_grounded_needs_value_and_source() -> None:
    with pytest.raises(ValidationError):
        Field[str](value="x", status=FieldStatus.GROUNDED)


def test_ungrounded_never_keeps_a_value() -> None:
    with pytest.raises(ValidationError):
        Field[str](value="guess", status=FieldStatus.UNGROUNDED)


def test_money_serialises_as_exact_string() -> None:
    doc = BankStatement.model_validate({"fields": {"opening_balance": g(Decimal("1520.40"))}})
    assert doc.model_dump_doc()["fields"]["opening_balance"]["value"] == "1520.40"
    assert doc.model_dump_doc()["doc_type"] == "bank_statement"


def test_doc_type_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        Invoice.model_validate({"doc_type": "bank_statement"})


def test_bad_bbox_rejected() -> None:
    with pytest.raises(ValidationError):
        Source(page=1, bbox=(50, 10, 10, 20))
