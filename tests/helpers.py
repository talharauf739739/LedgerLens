"""Shared test helpers."""

from typing import Any

from ledgerlens.agents.drafts import draft_key
from synth.common import Generated


def perfect_draft(gen: Generated) -> dict[str, Any]:
    """What an ideal extractor returns: header values verbatim as printed; rows as plain
    text (rows are grounded by typed value, so their formatting doesn't matter)."""
    draft: dict[str, Any] = {draft_key(k): v for k, v in gen.meta.printed.items()}
    doc = gen.document
    if gen.meta.doc_type == "bank_statement":
        draft["transactions"] = [
            {
                "date": t.date.isoformat(),
                "description": t.description,
                "amount": ("-" if t.direction == "debit" else "") + str(t.amount),
                "direction": t.direction,
                "balance": str(t.balance),
            }
            for t in doc.transactions
        ]
    else:
        draft["line_items"] = [
            {
                "description": li.description,
                "quantity": str(li.quantity),
                "unit_price": str(li.unit_price),
                "amount": str(li.amount),
            }
            for li in doc.line_items
        ]
    return draft
