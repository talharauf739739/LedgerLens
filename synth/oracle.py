"""The ideal extractor's answer for a synthetic document, built from its ground truth.

Used by tests and by the review UI's offline "replay" mode, so the whole pipeline (parse,
classify, ground, rules, review) runs without any LLM. Replay is always labelled as such.
"""

from __future__ import annotations

import json
from typing import Any

from ledgerlens.agents.drafts import draft_key
from ledgerlens.schemas import REGISTRY, BaseDocument
from synth.common import Generated


def draft_from(printed: dict[str, str], document: BaseDocument) -> dict[str, Any]:
    """Header values verbatim as printed; rows as plain text (rows are grounded by typed
    value, so their formatting doesn't matter)."""
    draft: dict[str, Any] = {draft_key(k): v for k, v in printed.items()}
    if document.doc_type == "bank_statement":
        draft["transactions"] = [
            {
                "date": t.date.isoformat(),
                "description": t.description,
                "amount": ("-" if t.direction == "debit" else "") + str(t.amount),
                "direction": t.direction,
                "balance": str(t.balance),
            }
            for t in document.transactions  # type: ignore[attr-defined]
        ]
    else:
        draft["line_items"] = [
            {
                "description": li.description,
                "quantity": str(li.quantity),
                "unit_price": str(li.unit_price),
                "amount": str(li.amount),
            }
            for li in document.line_items  # type: ignore[attr-defined]
        ]
    return draft


def oracle_draft(gen: Generated) -> dict[str, Any]:
    return draft_from(gen.meta.printed, gen.document)


def draft_from_truth(truth: dict[str, Any]) -> dict[str, Any]:
    """Same, from a `.truth.json` written by `python -m synth`."""
    doc = truth["document"]
    return draft_from(truth["synthetic"]["printed"], REGISTRY[doc["doc_type"]].model_validate(doc))


class ReplayLLM:
    """Stands in for the extractor LLM: always answers with a fixed draft."""

    model = "replay (synthetic ground truth, no LLM)"

    def __init__(self, draft: dict[str, Any]) -> None:
        self.draft = draft

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> str:
        return json.dumps(self.draft)
