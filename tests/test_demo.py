"""Demo screen: each scenario must tell its story with the real pipeline."""

from decimal import Decimal
from pathlib import Path

import pytest

from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.pipeline.process import process_pdf
from ledgerlens.schemas.base import FieldStatus
from synth import GENERATORS
from synth.oracle import ReplayLLM
from tests.helpers import perfect_draft
from ui import components
from ui.demo import SCENARIOS, hallucinate, pipeline_steps, proof, search_spans, stats

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest  # UI extra only

APP = str(Path(__file__).resolve().parents[1] / "ui" / "streamlit_app.py")


async def _run(doc_type: str, tamper: bool = False, invent: str | None = None):  # type: ignore[no-untyped-def]
    gen = GENERATORS[doc_type](7, "t", tamper=tamper)
    draft = perfect_draft(gen)
    if invent:
        draft, _ = hallucinate(draft, invent)
    return await process_pdf(gen.pdf, None, ReplayLLM(draft))


def test_hallucinate_changes_one_digit_only() -> None:
    draft, value = hallucinate({"closing_balance": "£20,268.56", "x": 1}, "closing_balance")
    assert value == "£30,268.56" and draft["closing_balance"] == value and draft["x"] == 1
    assert hallucinate({"t": "9.00"}, "t")[1] == "8.00"


async def test_clean_statement_is_ready_and_proven() -> None:
    res = await _run("bank_statement")
    s = stats(res.document, res.grounding)
    assert s.ready and not s.removed and s.fields_proven == s.fields_total
    assert s.rows_proven == s.rows_total > 0 and s.checks_passed == s.checks_run
    p = proof(res.document)
    assert p is not None and p.ok is True and p.computed == p.printed


async def test_tampered_statement_fails_the_proof() -> None:
    res = await _run("bank_statement", tamper=True)
    s = stats(res.document, res.grounding)
    assert not s.ready and s.checks_passed < s.checks_run
    p = proof(res.document)
    assert p is not None and p.ok is False
    assert "off by" in components.proof_card(p)


async def test_invented_value_is_removed_after_one_retry() -> None:
    res = await _run("bank_statement", invent="closing_balance")
    doc = res.document
    assert doc.fields.closing_balance.status is FieldStatus.UNGROUNDED  # type: ignore[attr-defined]
    s = stats(doc, res.grounding)
    assert s.removed == ["closing_balance"] and not s.ready
    p = proof(doc)
    assert p is not None and p.ok is None and p.printed is None  # can't be proven
    steps = pipeline_steps(res.trace)
    assert [st.name for st in steps] == [
        "Read",
        "Classify",
        "Extract (x2)",
        "Find on page (x2)",
        "Prove the math",
    ]
    assert steps[2].flag and steps[3].flag


async def test_invoice_proof_adds_up() -> None:
    res = await _run("invoice")
    p = proof(res.document)
    assert p is not None and p.ok is True
    assert p.computed is not None and p.computed > Decimal(0)


def test_search_finds_words_on_the_page() -> None:
    gen = GENERATORS["invoice"](7, "t")
    parsed = parse_pdf(gen.pdf)
    hits = search_spans(parsed, "total, subtotal")
    assert hits and all("total" in parsed.spans[i].text.lower() for i in hits)
    assert search_spans(parsed, " ") == []


def test_components_escape_document_text() -> None:
    html = components.story("Fintech", "<script>alert(1)</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "&lt;b&gt;" in components.compare("total", "<b>1</b>")


@pytest.fixture
def synth_dir(tmp_path: Path) -> Path:
    from synth.__main__ import main as synth_main

    out = tmp_path / "synth"
    synth_main(["--count", "1", "--out", str(out)])
    return tmp_path


@pytest.mark.parametrize("key", [s.key for s in SCENARIOS])
def test_every_scenario_renders(key: str, synth_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGERLENS_DATA_DIR", str(synth_dir))
    monkeypatch.delenv("LEDGERLENS_ALLOW_UPLOAD", raising=False)
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    at.sidebar.radio[0].set_value(key).run()
    assert not at.exception, [e.message for e in at.exception]
    page = " ".join(m.value for m in at.markdown)
    assert "ll-kpis" in page and "ll-story" in page
    scenario = next(s for s in SCENARIOS if s.key == key)
    if scenario.read_only:
        assert "Words located" in page
    else:
        assert "Verdict" in page
        if key == "fraud":
            assert "Needs review" in page
        if key == "clean":
            assert "Ready to approve" in page
        if key == "hallucination":
            assert "Typical AI pipeline" in page


def test_receipt_closeup_zooms_on_the_value() -> None:
    from ui.review import receipt_closeup

    gen = GENERATORS["bank_statement"](7, "t")
    src = gen.document.fields.closing_balance.source  # type: ignore[attr-defined]
    crop = receipt_closeup(gen.pdf, src.page, src.bbox, scale=3.0, pad=(150, 40))
    x0, y0, x1, y1 = src.bbox
    assert crop.height == round((y1 + 40) * 3) - round((y0 - 40) * 3)
    assert crop.width <= round((x1 - x0 + 300) * 3)
