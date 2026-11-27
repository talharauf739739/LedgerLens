"""Review UI: the logic module directly, and the Streamlit page headlessly."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerlens.pipeline.process import ProcessResult, process_pdf
from ledgerlens.schemas import RuleStatus
from ledgerlens.schemas.base import FieldStatus
from synth import GENERATORS
from synth.oracle import ReplayLLM, oracle_draft
from ui.review import (
    apply_correction,
    field_rows,
    highlights,
    make_decision,
    needs_attention,
    render_page,
    row_records,
    save_decision,
)


def _process(
    doc_type: str, seed: int, *, tamper: bool = False, lie: dict | None = None
) -> ProcessResult:
    gen = GENERATORS[doc_type](seed, "t", tamper=tamper)
    draft = {**oracle_draft(gen), **(lie or {})}
    return asyncio.run(process_pdf(gen.pdf, None, ReplayLLM(draft)))


def test_tables_and_highlights_cover_every_receipt() -> None:
    r = _process("invoice", 2)
    rows = field_rows(r.document)
    assert rows and all(row["status"] == "grounded" for row in rows)
    assert len(row_records(r.document)) == len(r.document.line_items)
    hs = highlights(r.document, selected="total")
    assert sum(h.selected for h in hs) == 1
    assert len(hs) == len(rows) + len(r.document.line_items)


def test_render_page_draws_boxes() -> None:
    gen = GENERATORS["invoice"](2, "t")
    r = _process("invoice", 2)
    plain = render_page(gen.pdf, 1, [])
    boxed = render_page(gen.pdf, 1, highlights(r.document, "total"))
    assert plain.size == boxed.size and plain.tobytes() != boxed.tobytes()


def test_invented_value_needs_attention_and_can_be_corrected() -> None:
    r = _process("invoice", 2, lie={"total": "999,999.99"})
    assert "total" in needs_attention(r.document)
    assert r.document.fields.total.status is FieldStatus.UNGROUNDED

    bad, err = apply_correction(r.document, "total", "lots")
    assert err and bad is r.document  # unreadable input changes nothing

    true_total = GENERATORS["invoice"](2, "t").document.fields.total.value
    fixed, err = apply_correction(r.document, "total", f"{true_total:,}")
    assert err is None
    assert fixed.fields.total.value == true_total
    assert fixed.fields.total.status is FieldStatus.CORRECTED
    rules = {x.rule: x.status for x in fixed.validation}
    assert rules["all_values_grounded"] is RuleStatus.PASS
    assert rules["total_arithmetic"] is RuleStatus.PASS
    assert needs_attention(fixed) == []


def test_correction_types_follow_the_schema() -> None:
    r = _process("bank_statement", 3)
    doc, err = apply_correction(r.document, "period_start", "2026-01-31")
    assert err is None and str(doc.fields.period_start.value) == "2026-01-31"
    doc, err = apply_correction(doc, "opening_balance", "(1.234,50)")
    assert err is None and doc.fields.opening_balance.value == Decimal("-1234.50")


def test_tampered_statement_is_flagged_and_decision_saved(tmp_path: Path) -> None:
    r = _process("bank_statement", 5, tamper=True)
    attention = needs_attention(r.document)
    assert {"opening_balance", "closing_balance"} <= set(attention)  # named by roll-forward
    d = make_decision(r.document, r.parsed.sha256, "rejected", " Ana ", "amount altered", [])
    assert d.reviewer == "Ana" and "balance_roll_forward" in d.failed_rules
    path = save_decision(d, r.document, tmp_path)
    saved = json.loads(path.read_text("utf-8"))
    assert saved["decision"]["decision"] == "rejected"
    assert saved["document"]["doc_type"] == "bank_statement"


def test_streamlit_page_runs_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh deploy: no samples yet, uploads off. The page must generate its own synthetic
    samples, process a tampered statement, flag it, and save a review decision."""
    from streamlit.testing.v1 import AppTest

    app = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    monkeypatch.setenv("LEDGERLENS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LEDGERLENS_ALLOW_UPLOAD", raising=False)

    at = AppTest.from_file(str(app), default_timeout=300).run()
    assert not at.exception
    assert len(list((tmp_path / "synth").glob("*/*.pdf"))) == 12
    assert not [r for r in at.sidebar.radio if r.label == "Source"]  # no upload option
    assert any("synthetic documents only" in i.value for i in at.sidebar.info)

    sample = at.sidebar.selectbox[0]
    sample.select(
        next(o for o in sample.options if "bank_statement" in str(o) and "tampered" in str(o))
    ).run()
    at.sidebar.button[0].click().run()  # Process
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Document type"] == "bank statement"
    assert int(metrics["Checks failed"]) >= 1  # the planted amount breaks reconciliation
    assert any("Needs review" in w.value for w in at.warning)

    next(t for t in at.text_input if t.label == "Reviewer").input("Test Reviewer")
    next(b for b in at.button if b.label == "Approve").click().run()
    assert not at.exception
    assert list((tmp_path / "reviews").glob("*.json"))


def test_uploads_can_be_enabled_locally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    app = Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py"
    monkeypatch.setenv("LEDGERLENS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LEDGERLENS_ALLOW_UPLOAD", "1")
    at = AppTest.from_file(str(app), default_timeout=300).run()
    assert not at.exception
    assert [r for r in at.sidebar.radio if r.label == "Source"]


def test_read_only_view_boxes_every_word_by_source() -> None:
    from ledgerlens.pipeline.parse import parse_pdf
    from ui.review import ORIGIN_COLOR, page_summary, span_highlights, span_rows

    gen = GENERATORS["invoice"](2, "t")
    parsed = parse_pdf(gen.pdf)
    boxes = span_highlights(parsed, page=1)
    assert len(boxes) == len([s for s in parsed.spans if s.page == 1])
    assert {b.color for b in boxes} == {ORIGIN_COLOR["pdf"]}  # born-digital: text layer only
    assert span_rows(parsed)[0]["source"] == "text layer"
    assert page_summary(parsed)[0]["read with"] == "text layer"
