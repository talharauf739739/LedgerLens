"""Agent workflow: classification, the grounding-driven retry loop and the audit trace."""

import json
from typing import Any

import pytest

from ledgerlens.agents.classifier import classify, cue_scores
from ledgerlens.agents.workflow import UnsupportedDocument, run_workflow
from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.schemas.base import FieldStatus
from synth import GENERATORS
from tests.helpers import perfect_draft


class ScriptedLLM:
    """Replies from a script; records every conversation it was sent."""

    model = "scripted"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


@pytest.mark.parametrize(
    ("doc_type", "seed"), [(t, s) for t in sorted(GENERATORS) for s in range(10)]
)
async def test_cues_classify_every_template_without_an_llm(doc_type: str, seed: int) -> None:
    gen = GENERATORS[doc_type](seed, "t")
    c = await classify(parse_pdf(gen.pdf).markdown, llm=None)
    assert (c.doc_type, c.method) == (doc_type, "cues"), (gen.meta.template, c.scores)


async def test_llm_is_asked_only_when_cues_are_ambiguous() -> None:
    llm = ScriptedLLM('{"doc_type": "invoice", "confidence": 0.8}')
    c = await classify("Some letter mentioning an invoice once.", llm)
    assert (c.doc_type, c.method, c.confidence) == ("invoice", "llm", 0.8)
    assert "untrusted" in llm.calls[0][0]["content"]


async def test_unusable_llm_answer_falls_back_to_cues() -> None:
    c = await classify("Dear customer, thanks.", ScriptedLLM("I think it's a poem"))
    assert c.doc_type == "other"


def test_cue_scores() -> None:
    s = cue_scores("Invoice no. 12 | Bill to | Subtotal | VAT 20% | Total due")
    assert s["invoice"] >= 5 and s["bank_statement"] == 0


async def test_retry_fixes_a_misread_value_and_the_trace_shows_it() -> None:
    gen = GENERATORS["bank_statement"](4, "t")
    good = perfect_draft(gen)
    misread = dict(good, opening_balance="$1,234,567.89")  # not printed anywhere
    llm = ScriptedLLM(json.dumps(misread), json.dumps(good))
    job = await run_workflow(gen.pdf, llm)  # classifier decides the type

    assert job.doc_type == "bank_statement" and job.classification.method == "cues"
    assert job.attempts == 2
    f = job.document.fields.opening_balance
    assert f.status is FieldStatus.GROUNDED and f.value == gen.document.fields.opening_balance.value
    assert not job.needs_review
    retry_note = llm.calls[1][-1]["content"]
    assert "opening_balance" in retry_note and "not found" in retry_note
    steps = [e["step"] for e in job.trace]
    assert steps == ["parse", "classify", "extract", "ground", "extract", "ground", "validate"]
    assert job.trace[3]["ungrounded"] == ["opening_balance"]


async def test_a_value_that_stays_invented_is_nulled_and_reviewed() -> None:
    gen = GENERATORS["invoice"](4, "t")
    lie = dict(perfect_draft(gen), total="999,999.99")
    llm = ScriptedLLM(json.dumps(lie), json.dumps(lie))
    job = await run_workflow(gen.pdf, llm, doc_type="invoice")
    assert job.attempts == 2  # one retry, then stop
    assert job.document.fields.total.value is None
    assert job.document.fields.total.status is FieldStatus.UNGROUNDED
    assert job.needs_review


async def test_no_retry_when_everything_is_grounded() -> None:
    gen = GENERATORS["invoice"](6, "t")
    llm = ScriptedLLM(json.dumps(perfect_draft(gen)))
    job = await run_workflow(gen.pdf, llm, doc_type="invoice")
    assert job.attempts == 1 and len(llm.calls) == 1
    assert not job.needs_review


async def test_unsupported_documents_are_rejected() -> None:
    gen = GENERATORS["invoice"](1, "t")
    with pytest.raises(UnsupportedDocument):
        await run_workflow(gen.pdf, ScriptedLLM(), doc_type="w2")
