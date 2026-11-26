"""End to end with a stand-in LLM: parse -> extract -> ground -> validate, and the eval
harness that scores it. A real model only changes the drafts, not this plumbing."""

import json
from pathlib import Path
from typing import Any

import pytest

from eval.runners import eval_extract, extract_report, load_samples
from ledgerlens.pipeline.process import process_pdf
from ledgerlens.schemas import RuleStatus
from synth import GENERATORS
from synth.__main__ import main as synth_main
from tests.helpers import perfect_draft


class OracleLLM:
    """Answers every extraction with the perfect draft for the document it's shown."""

    model = "oracle"

    def __init__(self, drafts_by_marker: dict[str, dict[str, Any]], lie: bool = False) -> None:
        self.drafts = drafts_by_marker
        self.lie = lie

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> str:
        text = messages[-1]["content"]
        draft = next(d for marker, d in self.drafts.items() if marker in text)
        draft = dict(draft)
        if self.lie:  # invent one value that isn't printed anywhere
            key = "opening_balance" if "transactions" in draft else "subtotal"
            draft[key] = "424,242.42"
        return json.dumps(draft)


def _marker(gen: Any) -> str:
    # A string that appears in this document's Markdown and no other's.
    return gen.meta.printed.get("account_number_masked") or gen.meta.printed["invoice_number"]


@pytest.mark.parametrize("lie", [False, True])
async def test_process_pdf(lie: bool) -> None:
    gen = GENERATORS["bank_statement"](5, "t")
    llm = OracleLLM({_marker(gen): perfect_draft(gen)}, lie=lie)
    result = await process_pdf(gen.pdf, "bank_statement", llm)  # type: ignore[arg-type]
    rules = {r.rule: r.status for r in result.document.validation}
    if lie:
        assert result.grounding.ungrounded == ["opening_balance"]
        assert result.document.fields.opening_balance.value is None
        assert result.needs_review
        assert rules["all_values_grounded"] is RuleStatus.FAIL
    else:
        assert not result.needs_review
        assert all(s is not RuleStatus.FAIL for s in rules.values())
        assert result.document.markdown and "| --- |" in result.document.markdown


async def test_tampered_statement_fails_reconciliation_after_grounding() -> None:
    gen = GENERATORS["bank_statement"](5, "t", tamper=True)
    llm = OracleLLM({_marker(gen): perfect_draft(gen)})
    result = await process_pdf(gen.pdf, "bank_statement", llm)  # type: ignore[arg-type]
    failed = {r.rule for r in result.document.validation if r.status is RuleStatus.FAIL}
    assert failed == set(gen.meta.expected_failures)
    assert result.needs_review


@pytest.mark.parametrize("lie", [False, True])
@pytest.mark.parametrize("variant", ["clean", "tampered"])
async def test_eval_extract_scores_the_pipeline(tmp_path: Path, lie: bool, variant: str) -> None:
    # One variant per run: a tampered document differs from its clean twin by a single
    # amount, so the stand-in LLM couldn't tell them apart if both were in one run.
    synth_main(["--count", "2", "--out", str(tmp_path), "--variants", variant])
    samples = load_samples(tmp_path, ["bank_statement", "invoice"], [variant], 2)
    drafts = {}
    for s in samples:
        meta = s.meta
        gen = GENERATORS[meta["doc_type"]](meta["seed"], meta["id"], tamper=variant == "tampered")
        drafts[_marker(gen)] = perfect_draft(gen)
    stats = await eval_extract(samples, OracleLLM(drafts, lie=lie))
    report = extract_report(stats, "oracle")
    assert set(stats) == {f"bank_statement/{variant}", f"invoice/{variant}"}
    for st in stats.values():
        assert st.failed == 0
        assert st.rows.f1 == 1.0
        if lie:
            assert st.hallucinated == st.docs  # one invented value per document, all caught
            assert st.fields_raw.f1 < 1.0 and st.review == st.docs
        else:
            assert st.hallucinated == 0
            assert st.fields.f1 == 1.0
            assert st.rule_disagree == 0  # clean: no failures; tampered: exactly the planted
    assert "Hallucinated" in report
