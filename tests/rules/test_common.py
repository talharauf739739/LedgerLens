from decimal import Decimal

from ledgerlens.rules.common import all_values_grounded
from ledgerlens.schemas import Invoice, RuleStatus, Source

BOX = Source(page=1, bbox=(0, 0, 10, 10))


def test_reviewer_corrected_values_count_as_receipted() -> None:
    doc = Invoice.model_validate(
        {
            "fields": {
                "subtotal": {"value": Decimal("10.00"), "status": "grounded", "source": BOX},
                # A human set this value during review: the sign-off is its receipt.
                "total": {"value": Decimal("12.00"), "status": "corrected"},
            }
        }
    )
    assert all_values_grounded(doc).status is RuleStatus.PASS


def test_proposed_values_without_source_still_fail() -> None:
    doc = Invoice.model_validate(
        {"fields": {"total": {"value": Decimal("12.00"), "status": "proposed"}}}
    )
    r = all_values_grounded(doc)
    assert r.status is RuleStatus.FAIL and "total" in r.detail
