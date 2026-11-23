"""Document schemas. Register every type in REGISTRY."""

from ledgerlens.schemas.bank_statement import BankStatement, BankStatementFields, Transaction
from ledgerlens.schemas.base import (
    BaseDocument,
    Field,
    FieldStatus,
    RuleResult,
    RuleStatus,
    Source,
)
from ledgerlens.schemas.invoice import Invoice, InvoiceFields, LineItem

REGISTRY: dict[str, type[BaseDocument]] = {
    BankStatement.doc_type: BankStatement,
    Invoice.doc_type: Invoice,
}

__all__ = [
    "REGISTRY",
    "BankStatement",
    "BankStatementFields",
    "BaseDocument",
    "Field",
    "FieldStatus",
    "Invoice",
    "InvoiceFields",
    "LineItem",
    "RuleResult",
    "RuleStatus",
    "Source",
    "Transaction",
]
