"""Grounding contract: real values get the right receipt; invented values lose theirs."""

from typing import Any

import pytest

from eval.metrics import iou
from ledgerlens.agents.drafts import DRAFTS, to_document
from ledgerlens.pipeline.ground import ground_document
from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.rules import validate
from ledgerlens.schemas import RuleStatus
from ledgerlens.schemas.base import FieldStatus
from synth import GENERATORS
from synth.common import Generated
from synth.noise import make_noisy
from tests.helpers import perfect_draft

CASES = [(t, s) for t in sorted(GENERATORS) for s in range(8)]


def _ground(gen: Generated, draft: dict[str, Any]) -> Any:
    doc, _ = to_document(gen.meta.doc_type, DRAFTS[gen.meta.doc_type].model_validate(draft))
    return ground_document(doc, draft, parse_pdf(gen.pdf))


def _fields(doc: Any) -> dict[str, Any]:
    return {n: getattr(doc.fields, n) for n in type(doc.fields).model_fields}


@pytest.mark.parametrize(("doc_type", "seed"), CASES)
def test_perfect_extraction_is_fully_grounded_at_the_true_position(
    doc_type: str, seed: int
) -> None:
    gen = GENERATORS[doc_type](seed, "t")
    grounded, report = _ground(gen, perfect_draft(gen))
    assert report.ungrounded == [] and report.rows_ungrounded == []
    truth = _fields(gen.document)
    for name, f in _fields(grounded).items():
        if not hasattr(f, "status") or f.value is None:
            continue
        assert f.status is FieldStatus.GROUNDED, name
        assert iou(f.source.bbox, truth[name].source.bbox) > 0.5, name
    rows = "transactions" if doc_type == "bank_statement" else "line_items"
    for got, want in zip(getattr(grounded, rows), getattr(gen.document, rows), strict=True):
        assert got.source.page == want.source.page
        assert iou(got.source.bbox, want.source.bbox) > 0.5
    # With receipts attached, the "every value has a source" rule now passes.
    results = {r.rule: r.status for r in validate(grounded)}
    assert results["all_values_grounded"] is RuleStatus.PASS


@pytest.mark.parametrize("doc_type", sorted(GENERATORS))
def test_invented_values_are_ungrounded_never_kept(doc_type: str) -> None:
    gen = GENERATORS[doc_type](2, "t")
    draft = perfect_draft(gen)
    if doc_type == "bank_statement":
        draft["closing_balance"] = "$123,456.78"  # not printed anywhere
        draft["account_holder"] = "Someone Else Entirely"
        draft["transactions"].append(
            {
                "date": "2026-01-01",
                "description": "GHOST",
                "amount": "-999.99",
                "direction": "debit",
                "balance": "1.00",
            }
        )
    else:
        draft["total"] = "999,999.99"
        draft["buyer_name"] = "Imaginary Holdings"
        draft["line_items"].append(
            {"description": "Ghost", "quantity": "1", "unit_price": "77.77", "amount": "77.77"}
        )
    grounded, report = _ground(gen, draft)
    invented = (
        {"closing_balance", "account_holder"}
        if doc_type == "bank_statement"
        else {"total", "buyer_name"}
    )
    assert set(report.ungrounded) == invented
    for name in invented:
        f = getattr(grounded.fields, name)
        assert f.value is None and f.status is FieldStatus.UNGROUNDED
    rows = "transactions" if doc_type == "bank_statement" else "line_items"
    assert report.rows_ungrounded == [len(getattr(grounded, rows)) - 1]
    results = {r.rule: r.status for r in validate(grounded)}
    assert results["all_values_grounded"] is RuleStatus.FAIL  # sent to review


@pytest.mark.parametrize("doc_type", sorted(GENERATORS))
def test_grounding_works_on_scans(doc_type: str) -> None:
    gen = make_noisy(GENERATORS[doc_type](3, "t"), 3)
    grounded, report = _ground(gen, perfect_draft(gen))
    total = len(report.grounded) + len(report.ungrounded)
    assert len(report.grounded) / total >= 0.9
    rows = len(getattr(grounded, "transactions", None) or grounded.line_items)
    assert report.rows_grounded / rows >= 0.9
    truth = _fields(gen.document)
    for name in report.grounded:
        assert iou(getattr(grounded.fields, name).source.bbox, truth[name].source.bbox) > 0.3, name
