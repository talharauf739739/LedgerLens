"""Deterministic validators per document type."""

from collections.abc import Callable

from ledgerlens.rules import bank_statement, invoice
from ledgerlens.schemas import BaseDocument, RuleResult

VALIDATORS: dict[str, Callable[..., list[RuleResult]]] = {
    "bank_statement": bank_statement.validate,
    "invoice": invoice.validate,
}


def validate(doc: BaseDocument) -> list[RuleResult]:
    return VALIDATORS[doc.doc_type](doc)


__all__ = ["VALIDATORS", "validate"]
