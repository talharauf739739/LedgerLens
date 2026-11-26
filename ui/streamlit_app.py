"""LedgerLens review UI.

    uv sync --extra ui
    uv run streamlit run ui/streamlit_app.py

Replay mode runs the real pipeline (parse, classify, ground, rules) on synthetic samples with
the ground truth standing in for the LLM, so it works offline on a small laptop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import streamlit as st

from ledgerlens.pipeline.process import ProcessResult, process_pdf
from ledgerlens.schemas import RuleStatus
from synth.oracle import ReplayLLM, draft_from_truth
from ui.review import (
    Correction,
    apply_correction,
    field_items,
    field_rows,
    highlights,
    image_bytes,
    make_decision,
    needs_attention,
    render_page,
    row_records,
    save_decision,
)

SYNTH_DIR = Path("data/synth")
REVIEWS_DIR = Path("data/reviews")
RULE_ICON = {
    RuleStatus.PASS: "✅",
    RuleStatus.FAIL: "❌",
    RuleStatus.WARN: "⚠️",
    RuleStatus.SKIP: "⚪",
}

st.set_page_config(page_title="LedgerLens review", page_icon="🧾", layout="wide")


# --- inputs ------------------------------------------------------------------------------


def list_samples() -> list[Path]:
    return sorted(SYNTH_DIR.glob("*/*.pdf"))


def sample_label(pdf: Path) -> str:
    truth = json.loads(pdf.with_suffix("").with_suffix(".truth.json").read_text("utf-8"))
    meta = truth["synthetic"]
    return f"{meta['id']} · {meta['template']} · {meta['variant']}"


def run(pdf_bytes: bytes, llm: Any, doc_type: str | None) -> ProcessResult:
    return asyncio.run(process_pdf(pdf_bytes, doc_type, llm))


def start(key: str, pdf_bytes: bytes, result: ProcessResult) -> None:
    st.session_state.update(
        key=key, pdf=pdf_bytes, result=result, doc=result.document, corrections=[], saved=None
    )


with st.sidebar:
    st.title("🧾 LedgerLens")
    st.caption("Every extracted number has a receipt.")
    mode = st.radio("Source", ["Synthetic sample (replay, no LLM)", "Upload a PDF (uses your LLM)"])

    if mode.startswith("Synthetic"):
        samples = list_samples()
        if not samples:
            st.info("No synthetic samples yet.")
            if st.button("Generate samples"):
                from synth.__main__ import main as synth_main

                synth_main(["--count", "3", "--out", str(SYNTH_DIR)])
                st.rerun()
        else:
            choice = st.selectbox("Sample", samples, format_func=sample_label)
            st.caption("Tip: pick a *tampered* statement to see reconciliation fail.")
            if st.button("Process", type="primary"):
                truth = json.loads(
                    choice.with_suffix("").with_suffix(".truth.json").read_text("utf-8")
                )
                with st.spinner("Parsing, grounding and checking..."):
                    data = choice.read_bytes()
                    start(str(choice), data, run(data, ReplayLLM(draft_from_truth(truth)), None))
    else:
        upload = st.file_uploader("PDF (synthetic or public data only)", type=["pdf"])
        dt = st.selectbox("Document type", ["auto", "bank_statement", "invoice"])
        if upload is not None and st.button("Process", type="primary"):
            data = upload.getvalue()
            try:
                from ledgerlens.llm import get_llm_client

                with st.spinner("Running the pipeline with your LLM..."):
                    start(
                        upload.name, data, run(data, get_llm_client(), None if dt == "auto" else dt)
                    )
            except Exception as exc:  # show the reason instead of a stack trace
                st.error(
                    f"Couldn't process with the configured LLM ({type(exc).__name__}: {exc}). "
                    "Start Foundry Local or Ollama (see .env.example), or use replay mode."
                )


if "result" not in st.session_state:
    st.header("Review queue")
    st.write(
        "Pick a sample or upload a PDF in the sidebar. Every value is shown with its receipt "
        "(a box on the page); values that couldn't be found, and failed finance checks, "
        "come here for a human decision."
    )
    st.stop()

result: ProcessResult = st.session_state["result"]
doc = st.session_state["doc"]
pdf_bytes: bytes = st.session_state["pdf"]

# --- header ------------------------------------------------------------------------------

failed = [r for r in doc.validation if r.status is RuleStatus.FAIL]
attention = needs_attention(doc)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Document type", doc.doc_type.replace("_", " "), result.classification.method)
c2.metric("Checks failed", len(failed))
c3.metric("Need attention", len(attention))
c4.metric("Extraction attempts", result.attempts)
if failed or attention:
    st.warning("Needs review: " + ", ".join(sorted({r.rule for r in failed} | set(attention))))
else:
    st.success("All values have receipts and every finance check passed.")
st.caption(f"Model: {result.model} · prompt {result.prompt_version}")

# --- page + details --------------------------------------------------------------------

left, right = st.columns([5, 6])
with right:
    names = [n for n, f in field_items(doc) if f.source is not None]
    rows = [f"row {i}" for i, r in enumerate(row_records(doc))]
    picked = st.selectbox("Show on page", ["(all receipts)", *names, *rows])
    selected = None if picked.startswith("(") else picked

    tab_f, tab_r, tab_c, tab_rev, tab_t = st.tabs(["Fields", "Rows", "Checks", "Review", "Trace"])
    with tab_f:
        st.dataframe(field_rows(doc), hide_index=True, use_container_width=True)
    with tab_r:
        st.dataframe(row_records(doc), hide_index=True, use_container_width=True)
    with tab_c:
        for r in doc.validation:
            line = f"{RULE_ICON[r.status]} **{r.rule}**"
            if r.detail:
                line += f": {r.detail}"
            if r.rows:
                line += f" (rows {', '.join(map(str, r.rows))})"
            st.markdown(line)
    with tab_rev:
        if attention:
            st.write("Correct a value if it's wrong. Corrections are checked by the same rules.")
            for name in attention:
                current = getattr(doc.fields, name)
                with st.form(f"fix-{name}"):
                    text = st.text_input(
                        f"{name} ({current.status.value})",
                        value="" if current.value is None else str(current.value),
                    )
                    if st.form_submit_button("Apply correction"):
                        new_doc, error = apply_correction(doc, name, text)
                        if error:
                            st.error(error)
                        else:
                            st.session_state["doc"] = new_doc
                            st.session_state["corrections"].append(
                                Correction(field=name, value=text)
                            )
                            st.rerun()
        else:
            st.write("Nothing needs correcting.")
        st.divider()
        with st.form("decide"):
            reviewer = st.text_input("Reviewer")
            comment = st.text_area("Comment")
            a, b = st.columns(2)
            approve = a.form_submit_button("Approve", type="primary")
            reject = b.form_submit_button("Reject")
        if approve or reject:
            decision = make_decision(
                doc,
                result.parsed.sha256,
                "approved" if approve else "rejected",
                reviewer,
                comment,
                st.session_state["corrections"],
            )
            st.session_state["saved"] = str(save_decision(decision, doc, REVIEWS_DIR))
        if st.session_state.get("saved"):
            st.success(f"Decision saved to {st.session_state['saved']}")
    with tab_t:
        st.json(result.trace)

with left:
    pages = len(result.parsed.pages)
    hl = highlights(doc, selected)
    default_page = next((h.page for h in hl if h.selected), 1)
    page = st.number_input("Page", 1, pages, value=default_page) if pages > 1 else 1
    st.image(image_bytes(render_page(pdf_bytes, int(page), hl)), use_container_width=True)
    st.caption("Green: grounded · Blue: corrected by a reviewer · Purple: selected")
