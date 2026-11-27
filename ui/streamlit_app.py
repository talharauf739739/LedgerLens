"""LedgerLens demo and review UI.

    uv sync --extra ui
    uv run streamlit run ui/streamlit_app.py

The sidebar offers one-click demo scenarios, each showing one capability: fraud caught by
the arithmetic, an invented number blocked, OCR on a crooked scan, healthcare documents
read with receipts. Synthetic scenarios run the real pipeline (parse, classify, ground,
rules) with the ground truth standing in for the LLM, so they work offline and free.

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
import time
from dataclasses import dataclass, field
from functools import partial
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
from ledgerlens.schemas import BaseDocument, RuleStatus  # noqa: E402
from ledgerlens.schemas.base import FieldStatus  # noqa: E402
from synth.oracle import ReplayLLM, draft_from_truth  # noqa: E402
from ui import components as ui  # noqa: E402
from ui.demo import (  # noqa: E402
    SCENARIOS,
    Scenario,
    hallucinate,
    pipeline_steps,
    proof,
    search_spans,
    stats,
)
from ui.review import (  # noqa: E402
    ORIGIN_COLOR,
    Correction,
    Highlight,
    apply_correction,
    field_items,
    highlights,
    image_bytes,
    make_decision,
    needs_attention,
    page_summary,
    receipt_closeup,
    render_page,
    row_records,
    rows_attr,
    save_decision,
    span_rows,
)

DATA_DIR = Path(os.environ.get("LEDGERLENS_DATA_DIR", ROOT / "data"))  # tests point this elsewhere
SYNTH_DIR = DATA_DIR / "synth"
REVIEWS_DIR = DATA_DIR / "reviews"
SAMPLES_PER_TYPE = 2  # x 2 types x 3 variants (clean, scanned, tampered) = 12 documents
ASSETS = ROOT / "assets"
LOGO = ASSETS / "logo.png"  # 450x158, navy background, rounded corners
ICON = ASSETS / "icon.png"  # 128x128 mark: browser tab icon

RULE_NAMES = {
    "balance_roll_forward": "Opening + money in - money out = closing balance",
    "running_balance_consistency": "Every row's running balance follows from the one before",
    "dates_within_period": "All transactions fall inside the statement period",
    "no_duplicate_rows": "No transaction is listed twice",
    "printed_totals_match": "Printed totals equal the sum of the rows",
    "line_amounts": "Quantity x unit price = line amount, on every line",
    "lines_sum_to_subtotal": "Line amounts add up to the subtotal",
    "total_arithmetic": "Subtotal + tax - discount = total",
    "due_on_or_after_issue": "Due date is on or after the issue date",
    "iban_mod97": "IBAN checksum is valid",
    "tax_id_format": "VAT / tax ID matches the country's format",
    "currency_iso4217": "Currency is a real ISO 4217 code",
    "all_values_grounded": "Every value has a receipt on the page",
}
RULE_ICON = {
    RuleStatus.PASS: "✅",
    RuleStatus.FAIL: "❌",
    RuleStatus.WARN: "⚠️",
    RuleStatus.SKIP: "⚪",
}
STATUS_LABEL = {
    FieldStatus.GROUNDED: "✅ on the page",
    FieldStatus.CORRECTED: "✏️ corrected",
    FieldStatus.UNGROUNDED: "⛔ removed: not on page",
    FieldStatus.PROPOSED: "… not checked yet",
    FieldStatus.MISSING: "· not in the document",
}


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

st.set_page_config(
    page_title="LedgerLens: every number has a receipt",
    page_icon=str(ICON) if ICON.exists() else "🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(ui.CSS, unsafe_allow_html=True)


def html(fragment: str) -> None:
    st.markdown(fragment, unsafe_allow_html=True)


# --- what's on screen ---------------------------------------------------------------------------


@dataclass
class View:
    key: str
    title: str
    sector: str
    story: str
    pdf: bytes
    seconds: float
    result: ProcessResult | None = None  # full extraction
    parsed: ParsedDocument | None = None  # read-only (OCR) view
    doc: BaseDocument | None = None  # current document, including reviewer corrections
    invented: tuple[str, str] | None = None  # (field, value) the stand-in AI made up
    corrections: list[Correction] = field(default_factory=list)
    saved: str | None = None


def list_samples() -> list[Path]:
    return sorted(SYNTH_DIR.glob("*/*.pdf"))


def find_sample(stem: str) -> Path | None:
    return next(iter(SYNTH_DIR.glob(f"*/{stem}.pdf")), None)


def truth_of(pdf: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        pdf.with_suffix("").with_suffix(".truth.json").read_text("utf-8")
    )
    return data


def sample_label(pdf: Path) -> str:
    meta = truth_of(pdf)["synthetic"]
    return f"{meta['id']} · {meta['template']} · {meta['variant']}"


@st.cache_resource(show_spinner="Generating synthetic sample documents (first visit only)...")
def ensure_samples(synth_dir: str) -> int:
    """Create synthetic samples once per server and folder if there are none (fresh deploys)."""
    if not list_samples():
        from synth.__main__ import main as synth_main

        synth_main(["--count", str(SAMPLES_PER_TYPE), "--out", str(SYNTH_DIR)])
    return len(list_samples())


def available(sc: Scenario) -> bool:
    return (ROOT / sc.source).exists() if sc.from_file else find_sample(sc.source) is not None


def run_full(
    key: str,
    title: str,
    sector: str,
    story: str,
    pdf: bytes,
    llm: Any,
    doc_type: str | None = None,
    invented: tuple[str, str] | None = None,
) -> View:
    t = time.perf_counter()
    result = asyncio.run(process_pdf(pdf, doc_type, llm))
    return View(
        key,
        title,
        sector,
        story,
        pdf,
        time.perf_counter() - t,
        result=result,
        doc=result.document,
        invented=invented,
    )


def run_read(key: str, title: str, sector: str, story: str, data: bytes) -> View:
    t = time.perf_counter()
    pdf = to_pdf(data)
    parsed = parse_pdf(pdf)
    return View(key, title, sector, story, pdf, time.perf_counter() - t, parsed=parsed)


def run_sample(
    key: str, title: str, sector: str, story: str, path: Path, invent: str | None = None
) -> View:
    draft = draft_from_truth(truth_of(path))
    invented = None
    if invent:
        draft, value = hallucinate(draft, invent)
        invented = (invent, value)
    return run_full(
        key, title, sector, story, path.read_bytes(), ReplayLLM(draft), invented=invented
    )


def scenario_view(sc: Scenario) -> View:
    views: dict[str, View] = st.session_state.setdefault("views", {})
    if sc.key not in views:
        if sc.read_only:
            with st.spinner("Reading the photo: OCR on every word (a few seconds)..."):
                views[sc.key] = run_read(
                    sc.key, sc.title, sc.sector, sc.story, (ROOT / sc.source).read_bytes()
                )
        else:
            path = find_sample(sc.source)
            assert path is not None
            with st.spinner("Reading, extracting, finding every value, proving the math..."):
                views[sc.key] = run_sample(
                    sc.key, sc.title, sc.sector, sc.story, path, sc.hallucinate
                )
    return views[sc.key]


# --- sidebar: pick a demo ----------------------------------------------------------------------

with st.sidebar:
    if LOGO.exists():
        st.image(str(LOGO), width="stretch")
    else:  # e.g. a container image built without assets/
        st.title("LedgerLens")
    ensure_samples(str(SYNTH_DIR))
    scenarios = [s for s in SCENARIOS if available(s)]
    by_key = {s.key: s for s in scenarios}
    options = [s.key for s in scenarios] + ["browse"] + (["upload"] if ALLOW_UPLOAD else [])
    titles = {s.key: f"{s.title}" for s in scenarios} | {
        "browse": "All synthetic samples",
        "upload": "Upload your own document",
    }
    captions = (
        [f"{s.sector} · {s.teaser}" for s in scenarios]
        + ["Pick any of the 12"]
        + (["PDF or photo"] if ALLOW_UPLOAD else [])
    )
    choice = st.radio(
        "Pick a demo",
        options,
        format_func=titles.__getitem__,
        captions=captions,
        key="choice",
        index=options.index(q) if (q := st.query_params.get("demo")) in options else 0,
    )

    if choice == "browse":
        samples = list_samples()
        pick = st.selectbox("Sample", samples, format_func=sample_label)
        invent = st.toggle("Make the AI invent one value", help="Shows grounding at work")
        if st.button("Process", type="primary", width="stretch"):
            kind = truth_of(pick)["document"]["doc_type"]
            field_name = "closing_balance" if kind == "bank_statement" else "total"
            with st.spinner("Reading, extracting, finding every value, proving the math..."):
                st.session_state["custom_browse"] = run_sample(
                    "browse",
                    sample_label(pick),
                    "Fintech",
                    "A synthetic document with exact ground truth standing in for the AI model.",
                    pick,
                    field_name if invent else None,
                )
    elif choice == "upload":
        upload = st.file_uploader(
            "PDF or image (synthetic or public data only)", type=UPLOAD_EXTENSIONS
        )
        full = st.toggle(
            "Full extraction (needs an LLM)",
            help="Off: read with OCR only. On: fields, receipts and checks.",
        )
        if upload is not None and st.button("Process", type="primary", width="stretch"):
            story = "Your document, processed live."
            try:
                if full:
                    from ledgerlens.llm import get_llm_client

                    with st.spinner("Running the full pipeline with your LLM..."):
                        st.session_state["custom_upload"] = run_full(
                            "upload",
                            upload.name,
                            "Your",
                            story,
                            to_pdf(upload.getvalue()),
                            get_llm_client(),
                        )
                else:
                    with st.spinner("Reading the text (OCR for scans and photos)..."):
                        st.session_state["custom_upload"] = run_read(
                            "upload", upload.name, "Your", story, upload.getvalue()
                        )
            except UnsupportedFile as exc:
                st.error(str(exc))
            except Exception as exc:  # show the reason instead of a stack trace
                st.error(
                    f"Couldn't process it ({type(exc).__name__}: {exc}). Full extraction "
                    "needs an LLM (see .env.example); OCR-only works without one."
                )

    st.divider()
    if ALLOW_UPLOAD:
        st.caption("Uploads are on. Use synthetic or public documents only.")
    else:
        st.caption(
            "Public demo: synthetic documents only (fake names and numbers). Ground "
            "truth stands in for the AI model, so no data leaves this page."
        )
        with st.expander("Turn on uploads"):
            st.markdown(
                "Only on a **private** app or your own machine.\n\n"
                "- **Streamlit Cloud:** Manage app → ⋮ → Settings → **Secrets**, add\n"
                '  `LEDGERLENS_ALLOW_UPLOAD = "1"`, save, then reboot the app.\n'
                "- **Locally:** set `LEDGERLENS_ALLOW_UPLOAD=1` before `streamlit run`."
            )


# --- main ----------------------------------------------------------------------------------------

html(ui.hero())

view: View | None = (
    scenario_view(by_key[choice]) if choice in by_key else st.session_state.get(f"custom_{choice}")
)
if view is None:
    st.info("Choose a document in the sidebar and press **Process**.")
    st.stop()

html(ui.story(view.sector, view.story))


def page_picker(pages: int, default: int, key: str) -> int:
    if pages <= 1:
        return 1
    return int(st.number_input("Page", 1, pages, value=default, key=key))


def _remember(state_key: str, table_key: str, names: list[str]) -> None:
    rows = st.session_state[table_key].selection.rows
    st.session_state[state_key] = names[rows[0]] if rows else None


def show_full(v: View) -> None:
    res, doc = v.result, v.doc
    assert res is not None and doc is not None
    s = stats(doc, res.grounding)
    html(ui.result_kpis(s, v.seconds))
    if v.invented and s.removed:
        html(ui.compare(*v.invented))
    html(ui.steps(pipeline_steps(res.trace)))
    if "replay" in res.model:
        st.caption(
            "AI stand-in: replays the synthetic ground truth, so this demo needs no "
            "model and no data leaves the page. Everything after extraction is real."
        )

    failed = [r for r in doc.validation if r.status is RuleStatus.FAIL]
    flagged = frozenset(i for r in failed for i in r.rows)
    if failed:
        html(
            ui.caught(
                proof(doc), [(RULE_NAMES.get(r.rule, r.rule), r.detail, r.rows) for r in failed]
            )
        )

    selected_key = f"selected_{v.key}"
    left, right = st.columns([6, 5], gap="large")
    with right:
        rows_name = "Transactions" if rows_attr(doc) == "transactions" else "Line items"
        tab_r, tab_rows, tab_p, tab_rev, tab_h = st.tabs(
            ["Receipts", rows_name, "All checks", "Review", "JSON"]
        )
        with tab_r:
            st.caption("Click a row: its receipt lights up on the page.")
            items = [
                (n, f)
                for n, f in field_items(doc)
                if f.value is not None or f.status is not FieldStatus.MISSING
            ]
            table = [
                {
                    "Field": n.replace("_", " "),
                    "Value": "" if f.value is None else str(f.value),
                    "Status": STATUS_LABEL[f.status],
                }
                for n, f in items
            ]
            names = [n for n, _ in items]
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                selection_mode="single-row",
                key=f"tbl_f_{v.key}",
                on_select=partial(_remember, selected_key, f"tbl_f_{v.key}", names),
            )
        with tab_rows:
            st.caption("Click a row to see it on the page.")
            records = row_records(doc)
            for rec in records:
                rec["receipt"] = "✅" if rec["receipt"] == "yes" else "⛔ not found"
                if rec["#"] in flagged:
                    rec["receipt"] += " ❌ breaks a check"
            st.dataframe(
                records,
                hide_index=True,
                width="stretch",
                selection_mode="single-row",
                key=f"tbl_r_{v.key}",
                on_select=partial(
                    _remember,
                    selected_key,
                    f"tbl_r_{v.key}",
                    [f"row {i}" for i in range(len(records))],
                ),
            )
        with tab_p:
            p = proof(doc)
            if p:
                html(ui.proof_card(p))
            st.markdown("**Every check run on this document**")
            for r in doc.validation:
                line = f"{RULE_ICON[r.status]} {RULE_NAMES.get(r.rule, r.rule)}"
                if r.status is RuleStatus.FAIL and r.detail:
                    line += f"  \n<small>{r.detail}"
                    if r.rows:
                        line += f" (rows {', '.join(map(str, r.rows))})"
                    line += "</small>"
                st.markdown(line, unsafe_allow_html=True)
        with tab_rev:
            show_review(v)
        with tab_h:
            payload = {
                **doc.model_dump_doc(exclude={"markdown"}),
                "provenance": {
                    "model": res.model,
                    "prompt_version": res.prompt_version,
                    "attempts": res.attempts,
                },
            }
            text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            st.download_button(
                "Download the JSON (what the API returns)",
                text,
                file_name=f"{v.key}.json",
                mime="application/json",
            )
            st.caption("Step-by-step trace")
            st.json(res.trace, expanded=False)
            with st.expander("The text the AI model was given (Markdown, tables kept)"):
                st.code(res.parsed.markdown, language="markdown")

    with left:
        selected = st.session_state.get(selected_key)
        hl = highlights(doc, selected, flagged)
        default = next((h.page for h in hl if h.selected), 1)
        page = page_picker(len(res.parsed.pages), default, f"page_{v.key}_{selected}")
        st.image(image_bytes(render_page(v.pdf, page, hl, scale=2.0)), width="stretch")
        chosen = next((h for h in hl if h.selected), None)
        if chosen is not None:
            label = str(selected).replace("_", " ")
            st.markdown(f"**Receipt close-up: {label}**")
            st.image(
                image_bytes(receipt_closeup(v.pdf, chosen.page, chosen.bbox)),
                caption=f"Page {chosen.page}, box "
                f"[{', '.join(f'{c:.0f}' for c in chosen.bbox)}] in PDF points",
                width="stretch",
            )
        html(
            ui.legend(
                [
                    ("#16A34A", "found on the page"),
                    ("#2563EB", "corrected"),
                    ("#64748B", "table row"),
                    ("#DC2626", "breaks a check"),
                    ("#9333EA", "selected"),
                ]
            )
        )


def show_review(v: View) -> None:
    doc, res = v.doc, v.result
    assert doc is not None and res is not None
    attention = needs_attention(doc)
    if attention:
        st.write("Fix a value if it's wrong. Corrections go through the same checks.")
        for name in attention:
            current = getattr(getattr(doc, "fields"), name)  # noqa: B009
            with st.form(f"fix-{v.key}-{name}"):
                text = st.text_input(
                    f"{name.replace('_', ' ')} ({STATUS_LABEL[current.status]})",
                    value="" if current.value is None else str(current.value),
                )
                if st.form_submit_button("Apply correction"):
                    new_doc, error = apply_correction(doc, name, text)
                    if error:
                        st.error(error)
                    else:
                        v.doc = new_doc
                        v.corrections.append(Correction(field=name, value=text))
                        st.rerun()
    else:
        st.success("Nothing needs correcting.")
    st.divider()
    with st.form(f"decide-{v.key}"):
        reviewer = st.text_input("Reviewer")
        comment = st.text_area("Comment")
        a, b = st.columns(2)
        approve = a.form_submit_button("Approve", type="primary", width="stretch")
        reject = b.form_submit_button("Reject", width="stretch")
    if approve or reject:
        decision = make_decision(
            doc,
            res.parsed.sha256,
            "approved" if approve else "rejected",
            reviewer,
            comment,
            v.corrections,
        )
        v.saved = str(save_decision(decision, doc, REVIEWS_DIR))
    if v.saved:
        st.success(f"Decision recorded for the audit log: {Path(v.saved).name}")


def show_read(v: View) -> None:
    parsed = v.parsed
    assert parsed is not None
    pages = len(parsed.pages)
    scanned = sum(p.kind == "scanned" for p in parsed.pages)
    ocr = [s for s in parsed.spans if s.origin == "ocr"]
    avg = sum(s.confidence for s in ocr) / len(ocr) if ocr else 1.0
    low = sum(s.confidence < 0.8 for s in ocr)
    guess = asyncio.run(classify(parsed.markdown))
    html(
        ui.kpis(
            [
                ui.kpi("Words located", f"{len(parsed.spans)}", "each with its exact box", "good"),
                ui.kpi("Read with OCR", f"{scanned} / {pages} pages", "scans and photos", "good"),
                ui.kpi(
                    "OCR confidence",
                    f"{avg:.0%}",
                    f"{low} words below 80%",
                    "good" if low <= max(3, len(ocr) // 50) else "warn",
                ),
                ui.kpi("Looks like", guess.doc_type.replace("_", " "), "keyword cues, no AI"),
                ui.kpi("Processing time", f"{v.seconds:.1f} s", "OCR on CPU"),
            ]
        )
    )
    left, right = st.columns([5, 6], gap="large")
    with right:
        query = st.text_input(
            "Search the page", key=f"q_{v.key}", placeholder="Try: total, balance, glucose, patient"
        )
        hits = set(search_spans(parsed, query))
        if query:
            st.caption(f"{len(hits)} matching word(s) highlighted on the page.")
        tab_t, tab_w, tab_pg = st.tabs(["Text (tables kept)", "Every word", "Pages"])
        with tab_t:
            st.code(parsed.markdown, language="markdown")
        with tab_w:
            st.dataframe(span_rows(parsed), hide_index=True, width="stretch")
        with tab_pg:
            st.dataframe(page_summary(parsed), hide_index=True, width="stretch")
    with left:
        first_hit = min((parsed.spans[i].page for i in hits), default=1)
        page = page_picker(pages, first_hit, f"page_{v.key}_{query}")
        hl = [
            Highlight(
                s.page,
                s.bbox,
                (220, 38, 38) if s.confidence < 0.8 else ORIGIN_COLOR[s.origin],
                i in hits,
            )
            for i, s in enumerate(parsed.spans)
            if s.page == page
        ]
        st.image(image_bytes(render_page(v.pdf, page, hl, scale=2.0)), width="stretch")
        html(
            ui.legend(
                [
                    ("#16A34A", "read with OCR"),
                    ("#2563EB", "digital text"),
                    ("#DC2626", "OCR unsure"),
                    ("#9333EA", "search match"),
                ]
            )
        )


if view.result is not None:
    show_full(view)
else:
    show_read(view)
