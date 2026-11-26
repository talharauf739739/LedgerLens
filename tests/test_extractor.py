"""Extractor plumbing with a fake LLM: prompt loading, JSON handling, draft -> document."""

import json
from typing import Any

import pytest

from ledgerlens.agents.drafts import DRAFTS, to_document
from ledgerlens.agents.extractor import ExtractionError, extract, load_prompt, parse_json_object
from ledgerlens.schemas.base import FieldStatus
from synth import GENERATORS
from synth.common import Generated

# draft key -> schema field name, where they differ
DRAFT_KEYS = {
    "account_number_masked": "account_number",
    "iban_masked": "iban",
    "seller_iban_masked": "seller_iban",
}


def perfect_draft(gen: Generated) -> dict[str, Any]:
    """What an ideal extractor returns: header values verbatim as printed; rows as plain text."""
    draft: dict[str, Any] = {DRAFT_KEYS.get(k, k): v for k, v in gen.meta.printed.items()}
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


class FakeLLM:
    model = "fake"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


@pytest.mark.parametrize(
    ("doc_type", "seed"), [(t, s) for t in sorted(GENERATORS) for s in range(12)]
)
def test_perfect_draft_normalises_to_the_truth(doc_type: str, seed: int) -> None:
    gen = GENERATORS[doc_type](seed, "t")
    draft = DRAFTS[doc_type].model_validate(perfect_draft(gen))
    doc, issues = to_document(doc_type, draft)
    assert issues == []
    truth = gen.document
    for name in type(truth.fields).model_fields:
        expected = getattr(truth.fields, name)
        got = getattr(doc.fields, name)
        if name == "seller_iban_checksum_ok":
            assert got == expected
            continue
        assert got.value == expected.value, name
        if got.value is not None:
            assert got.status is FieldStatus.PROPOSED and got.source is None
    rows = "transactions" if doc_type == "bank_statement" else "line_items"
    strip = {"source", "confidence"}
    assert [r.model_dump(exclude=strip) for r in getattr(doc, rows)] == [
        r.model_dump(exclude=strip) for r in getattr(truth, rows)
    ]


def test_prompts_exist_and_embed_the_schema() -> None:
    for doc_type in DRAFTS:
        prompt = load_prompt(doc_type)
        assert "{schema}" not in prompt
        assert '"properties"' in prompt
        assert "untrusted" in prompt  # prompt-injection rule is present


def test_parse_json_object_tolerates_fences_and_chatter() -> None:
    assert parse_json_object('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('here: {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


async def test_extract_repairs_once_then_succeeds() -> None:
    gen = GENERATORS["invoice"](1, "t")
    llm = FakeLLM("I think the total is big", json.dumps(perfect_draft(gen)))
    result = await extract(llm, "invoice", "markdown")  # type: ignore[arg-type]
    assert result.document.fields.total.value == gen.document.fields.total.value
    assert len(llm.calls) == 2
    assert "<document>" in llm.calls[0][1]["content"]


async def test_extract_rejects_after_two_bad_replies() -> None:
    llm = FakeLLM("nope", '{"line_items": "not a list"}')
    with pytest.raises(ExtractionError):
        await extract(llm, "invoice", "markdown")  # type: ignore[arg-type]
