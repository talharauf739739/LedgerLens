"""LedgerLens review UI.

    uv sync --extra ui
    uv run streamlit run ui/streamlit_app.py

Replay mode runs the real pipeline (parse, classify, ground, rules) on synthetic samples with
the ground truth standing in for the LLM, so it works offline on a small laptop.

Uploads (PDF, JPEG, PNG, TIFF, BMP, WebP) are off unless LEDGERLENS_ALLOW_UPLOAD=1. Turn them
on only where viewers are restricted (a private Streamlit app, your laptop): a public demo
must only ever show synthetic documents. Uploads run read-only (text layer + OCR, no LLM) or
full extraction when an LLM is configured.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

# Streamlit Community Cloud runs this file from a plain checkout (the package isn't
# installed), so make the repo root importable.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledgerlens.agents.classifier import classify  # noqa: E402
from ledgerlens.pipeline.ingest import UPLOAD_EXTENSIONS, UnsupportedFile, to_pdf  # noqa: E402
from ledgerlens.pipeline.parse import parse_pdf  # noqa: E402
from ledgerlens.pipeline.process import ProcessResult, process_pdf  # noqa: E402
from ledgerlens.pipeline.spans import ParsedDocument  # noqa: E402
from ledgerlens.schemas import RuleStatus  # noqa: E402
from synth.oracle import ReplayLLM, draft_from_truth  # noqa: E402
from ui.review import (  # noqa: E402
    Correction,
    apply_correction,
    field_items,
    field_rows,
    highlights,
    image_bytes,
    make_decision,
    needs_attention,
    page_summary,
    render_page,
    row_records,
    save_decision,
    span_highlights,
    span_rows,
)

DATA_DIR = Path(os.environ.get("LEDGERLENS_DATA_DIR", ROOT / "data"))  # tests point this elsewhere
SYNTH_DIR = DATA_DIR / "synth"
REVIEWS_DIR = DATA_DIR / "reviews"


def _upload_flag() -> bool:
    """LEDGERLENS_ALLOW_UPLOAD from the environment or Streamlit secrets (1/true/yes/on)."""
    raw: Any = os.environ.get("LEDGERLENS_ALLOW_UPLOAD")
    if raw is None:
        try:
            raw = st.secrets.get("LEDGERLENS_ALLOW_UPLOAD")
        except Exception:  # no secrets file (local runs)
            raw = None
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


ALLOW_UPLOAD = _upload_flag()
SAMPLES_PER_TYPE = 2  # x 2 types x 3 variants (clean, scanned, tampered) = 12 documents
READ_ONLY = "Read with OCR (no LLM)"
FULL = "Full extraction (needs an LLM)"
RUN_HELP = (
    "Read with OCR shows the text and a box for every word: the PDF text layer when there "
    "is one, OCR for scans and photos. Full extraction also fills the schema with an LLM, "
    "grounds every value and runs the finance checks."
)
RULE_ICON = {
    RuleStatus.PASS: "✅",
    RuleStatus.FAIL: "❌",
    RuleStatus.WARN: "⚠️",
    RuleStatus.SKIP: "⚪",
}

ASSETS = ROOT / "assets"
LOGO = ASSETS / "logo.png"  # 450x158, navy background, rounded corners
ICON = ASSETS / "icon.png"  # 128x128 mark: browser tab icon

st.set_page_config(
    page_title="LedgerLens review",
    page_icon=str(ICON) if ICON.exists() else "🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- inputs ------------------------------------------------------------------------------


def list_samples() -> list[Path]:
    return sorted(SYNTH_DIR.glob("*/*.pdf"))


def sample_label(pdf: Path) -> str:
    truth = json.loads(pdf.with_suffix("").with_suffix(".truth.json").read_text("utf-8"))
    meta = truth["synthetic"]
    return f"{meta['id']} · {meta['template']} · {meta['variant']}"


@st.cache_resource(show_spinner="Generating synthetic sample documents (first visit only)...")
def ensure_samples() -> int:
    """Create synthetic samples once per server if there are none (fresh cloud deploys)."""
    if not list_samples():
        from synth.__main__ import main as synth_main

        synth_main(["--count", str(SAMPLES_PER_TYPE), "--out", str(SYNTH_DIR)])
    return len(list_samples())


def run(pdf_bytes: bytes, llm: Any, doc_type: str | None) -> ProcessResult:
    return asyncio.run(process_pdf(pdf_bytes, doc_type, llm))


def start(key: str, pdf_bytes: bytes, result: ProcessResult) -> None:
    st.session_state.pop("parsed_only", None)
    st.session_state.update(
        key=key, pdf=pdf_bytes, result=result, doc=result.document, corrections=[], saved=None
    )


def inspect(key: str, pdf_bytes: bytes, parsed: ParsedDocument) -> None:
    st.session_state.pop("result", None)
    st.session_state.update(key=key, pdf=pdf_bytes, parsed_only=parsed)


def show_read_only(parsed: ParsedDocument, pdf_bytes: bytes) -> None:
    """Text layer / OCR view of an upload: what the extractor would see, with boxes."""
    scanned = sum(p.kind == "scanned" for p in parsed.pages)
    guess = asyncio.run(classify(parsed.markdown))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pages", len(parsed.pages))
    c2.metric("Read with OCR", scanned)
    c3.metric("Words", len(parsed.spans))
    c4.metric("Looks like", guess.doc_type.replace("_", " "), "keyword cues")
    st.info(
        "Read-only: text and word boxes, no LLM. Field extraction and finance checks run in "
        "'Full extraction' once an LLM is configured."
    )
    left, right = st.columns([5, 6])
    with right:
        tab_text, tab_words, tab_pages = st.tabs(["Text", "Words", "Pages"])
        with tab_text:
            st.caption("The Markdown the extractor gets (tables keep their columns).")
            st.code(parsed.markdown, language="markdown")
        with tab_words:
            st.dataframe(span_rows(parsed), hide_index=True, width="stretch")
        with tab_pages:
            st.dataframe(page_summary(parsed), hide_index=True, width="stretch")
    with left:
        pages = len(parsed.pages)
        page = st.number_input("Page", 1, pages, value=1) if pages > 1 else 1
        img = render_page(pdf_bytes, int(page), span_highlights(parsed, int(page)))
        st.image(image_bytes(img), width="stretch")
        st.caption("Blue: PDF text layer · Green: OCR · Red: OCR unsure (confidence < 0.8)")


with st.sidebar:
    if LOGO.exists():
        st.image(str(LOGO), width="stretch")
    else:  # e.g. a container image built without assets/
        st.title("LedgerLens")
        st.caption("Every value has a receipt.")
    if ALLOW_UPLOAD:
        mode = st.radio(
            "Source", ["Synthetic sample (replay, no LLM)", "Upload a document (PDF or image)"]
        )
    else:
        mode = "Synthetic"
        st.info(
            "Public demo: synthetic documents only (fake names and numbers, generated on the "
            "fly). Ground truth stands in for the LLM. Uploads are disabled."
        )
        with st.expander("Turn on uploads (PDF or image)"):
            st.markdown(
                "Only on a **private** app or your own machine.\n\n"
                "- **Streamlit Cloud:** Manage app → ⋮ → Settings → **Secrets**, add\n"
                '  `LEDGERLENS_ALLOW_UPLOAD = "1"`, save, then reboot the app.\n'
                "- **Locally:** set `LEDGERLENS_ALLOW_UPLOAD=1` before `streamlit run`."
            )

    if mode.startswith("Synthetic"):
        ensure_samples()
        samples = list_samples()
        if not samples:
            st.error("Couldn't generate the synthetic samples.")
        else:
            # Open on a tampered statement so a first visit shows a failing check right away.
            first = next((i for i, p in enumerate(samples) if "tampered" in p.stem), 0)
            choice = st.selectbox("Sample", samples, index=first, format_func=sample_label)
            st.caption("Tip: pick a *tampered* statement to see reconciliation fail.")
            clicked = st.button("Process", type="primary")
            if clicked or "result" not in st.session_state:
                truth = json.loads(
                    choice.with_suffix("").with_suffix(".truth.json").read_text("utf-8")
                )
                with st.spinner("Parsing, grounding and checking..."):
                    data = choice.read_bytes()
                    start(str(choice), data, run(data, ReplayLLM(draft_from_truth(truth)), None))
    else:
        upload = st.file_uploader(
            "Document: PDF or image (synthetic or public data only)", type=UPLOAD_EXTENSIONS
        )
        how = st.radio("Run", [READ_ONLY, FULL], help=RUN_HELP)
        dt = "auto"
        if how == FULL:
            dt = st.selectbox("Document type", ["auto", "bank_statement", "invoice"])
        if upload is not None and st.button("Process", type="primary"):
            try:
                pdf = to_pdf(upload.getvalue())
            except UnsupportedFile as exc:
                st.error(str(exc))
            else:
                if how == READ_ONLY:
                    with st.spinner("Reading the text (OCR for scans and photos)..."):
                        inspect(upload.name, pdf, parse_pdf(pdf))
                else:
                    try:
                        from ledgerlens.llm import get_llm_client

                        with st.spinner("Running the pipeline with your LLM..."):
                            doc_type = None if dt == "auto" else dt
                            start(upload.name, pdf, run(pdf, get_llm_client(), doc_type))
                    except Exception as exc:  # show the reason instead of a stack trace
                        st.error(
                            f"Couldn't run full extraction ({type(exc).__name__}: {exc}). "
                            "It needs an LLM (see .env.example); 'Read with OCR' works "
                            "without one."
                        )


if "parsed_only" in st.session_state:
    show_read_only(st.session_state["parsed_only"], st.session_state["pdf"])
    st.stop()

if "result" not in st.session_state:
    st.header("Review queue")
    st.write(
        "Pick a sample in the sidebar (open it with the arrow at the top left) and press "
        "Process. Every value is shown with its receipt (a box on the page); values that "
        "couldn't be found, and failed finance checks, come here for a human decision."
    )
    st.stop()

result: ProcessResult = st.session_state["result"]
doc = st.session_state["doc"]
pdf_bytes: bytes = st.session_state["pdf"]

# --- header ------------------------------------------------------------------------------

failed = [r for r in doc.validation if r.status is RuleStatus.FAIL]
attention = needs_attention(doc)
c1, c2, c3, c4 = st.columns([1.6, 1, 1, 1])  # room for "bank statement"
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
        st.dataframe(field_rows(doc), hide_index=True, width="stretch")
    with tab_r:
        st.dataframe(row_records(doc), hide_index=True, width="stretch")
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
    st.image(image_bytes(render_page(pdf_bytes, int(page), hl)), width="stretch")
    st.caption("Green: grounded · Blue: corrected by a reviewer · Purple: selected")
