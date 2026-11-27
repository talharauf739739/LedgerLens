"""HTML building blocks for the demo screen (brand colours from the logo).

Pure functions returning HTML strings, rendered with `st.html` / `st.markdown`. Every piece
of data is escaped. Layouts use CSS grid with auto-fit, so they reflow on phones.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

from ui.demo import Proof, Stats, Step

NAVY, TEAL, TEAL_DARK = "#0A1426", "#2DD4BF", "#0F766E"

CSS = f"""
<style>
.ll-hero {{ background: linear-gradient(135deg, {NAVY} 0%, #12305A 100%); color: #F4F7FB;
  border-radius: 18px; padding: 26px 30px; margin: 0 0 14px; }}
.ll-hero .title {{ color: #F4F7FB; font-size: 30px; line-height: 1.2; margin: 0 0 6px;
  padding: 0; font-weight: 750; }}
.ll-hero .title span {{ color: {TEAL}; }}
.ll-hero p.lead {{ color: #C4CEDC; font-size: 15.5px; margin: 0 0 16px; max-width: 900px; }}
.ll-problems {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px; }}
.ll-problem {{ background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12);
  border-radius: 12px; padding: 12px 14px; }}
.ll-problem b {{ color: #F4F7FB; font-size: 14px; }}
.ll-problem .fix {{ color: {TEAL}; font-size: 13.5px; margin-top: 3px; }}
.ll-pills {{ margin-top: 14px; }}
.ll-pill {{ display: inline-block; border: 1px solid rgba(45,212,191,.55); color: {TEAL};
  border-radius: 999px; padding: 2px 11px; font-size: 12px; margin: 0 6px 4px 0; }}

.ll-story {{ border-left: 4px solid {TEAL_DARK}; background: #F0FDFA; color: #134E4A;
  padding: 12px 16px; border-radius: 0 12px 12px 0; margin: 4px 0 14px; font-size: 15px; }}
.ll-story .tag {{ display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: {TEAL_DARK}; margin-bottom: 2px; }}

.ll-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px; margin-bottom: 14px; }}
.ll-kpi {{ border: 1px solid #E2E8F0; border-radius: 14px; padding: 14px 16px; background: #fff;
  border-top: 4px solid #CBD5E1; }}
.ll-kpi.good {{ border-top-color: #16A34A; }}
.ll-kpi.bad {{ border-top-color: #DC2626; }}
.ll-kpi.warn {{ border-top-color: #D97706; }}
.ll-kpi .label {{ font-size: 11.5px; color: #64748B; text-transform: uppercase;
  letter-spacing: .05em; font-weight: 600; }}
.ll-kpi .value {{ font-size: 28px; font-weight: 750; color: #0F172A; line-height: 1.25; }}
.ll-kpi .sub {{ font-size: 12.5px; color: #475569; }}
.ll-kpi.verdict .value {{ font-size: 24px; }}
.ll-kpi.verdict.good .value {{ color: #15803D; }}
.ll-kpi.verdict.bad .value {{ color: #B91C1C; }}

.ll-steps {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px; margin-bottom: 16px; }}
.ll-step {{ position: relative; background: #F8FAFC; border: 1px solid #E2E8F0;
  border-radius: 12px; padding: 10px 12px; }}
.ll-step.flag {{ background: #FFFBEB; border-color: #F59E0B; }}
.ll-step .n {{ font-weight: 700; color: #0F172A; font-size: 13.5px; }}
.ll-step .n i {{ font-style: normal; color: #94A3B8; font-weight: 600; margin-right: 6px; }}
.ll-step .ms {{ float: right; color: #64748B; font-size: 12px; }}
.ll-step .what {{ font-size: 12.5px; color: #334155; margin-top: 2px; }}

.ll-compare {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px; margin-bottom: 16px; }}
.ll-side {{ border-radius: 14px; padding: 14px 16px; border: 1px solid; }}
.ll-side.typical {{ background: #FEF2F2; border-color: #FECACA; }}
.ll-side.ours {{ background: #F0FDF4; border-color: #BBF7D0; }}
.ll-side h4 {{ margin: 0 0 6px; font-size: 14px; padding: 0; }}
.ll-side.typical h4 {{ color: #B91C1C; }}
.ll-side.ours h4 {{ color: #15803D; }}
.ll-side code {{ font-size: 13px; }}
.ll-side p {{ margin: 4px 0 0; font-size: 13.5px; color: #334155; }}

.ll-proof {{ border: 1px solid #E2E8F0; border-radius: 14px; padding: 14px 18px; }}
.ll-proof h4 {{ margin: 0 0 8px; padding: 0; font-size: 15px; }}
.ll-proof .row {{ display: flex; justify-content: space-between; gap: 12px; padding: 4px 0;
  font-size: 14px; color: #334155; }}
.ll-proof .row .amt {{ font-variant-numeric: tabular-nums; font-weight: 600; color: #0F172A; }}
.ll-proof .row.total {{ border-top: 1px solid #CBD5E1; margin-top: 4px; padding-top: 8px; }}
.ll-proof .verdict {{ margin-top: 10px; padding: 8px 12px; border-radius: 10px;
  font-weight: 650; font-size: 14px; }}
.ll-proof .verdict.ok {{ background: #DCFCE7; color: #166534; }}
.ll-proof .verdict.bad {{ background: #FEE2E2; color: #991B1B; }}
.ll-proof .verdict.na {{ background: #FEF3C7; color: #92400E; }}

.ll-caught {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px; margin-bottom: 16px; }}
.ll-caught-list {{ background: #FEF2F2; border: 1px solid #FECACA; border-radius: 14px;
  padding: 14px 18px; }}
.ll-caught-list h4 {{ margin: 0 0 8px; padding: 0; color: #B91C1C; font-size: 15px; }}
.ll-caught-list ul {{ margin: 0; padding-left: 18px; }}
.ll-caught-list li {{ margin: 0 0 8px; font-size: 14px; color: #1F2937; }}
.ll-caught-list li span {{ color: #6B7280; font-size: 13px; }}
.ll-legend {{ font-size: 12.5px; color: #475569; }}
.ll-legend span {{ display: inline-block; width: 11px; height: 11px; border-radius: 3px;
  margin: 0 5px -1px 10px; }}
</style>
"""


def hero() -> str:
    problems = [
        ("AI makes up numbers", "Every value must be found on the page, or it is removed"),
        ("Fraud hides in the arithmetic", "Finance rules redo the maths on every document"),
        ("No audit trail", "Every value keeps a receipt: page and exact box"),
    ]
    cards = "".join(
        f'<div class="ll-problem"><b>{escape(p)}</b><div class="fix">&rarr; {escape(f)}</div></div>'
        for p, f in problems
    )
    pills = "".join(
        f'<span class="ll-pill">{escape(p)}</span>'
        for p in ("Fintech", "Healthcare", "OCR + AI agents", "Self-hostable", "Open source")
    )
    return (
        '<div class="ll-hero"><div class="title">'
        "Every extracted number has a <span>receipt</span>.</div>"
        '<p class="lead">LedgerLens reads bank statements, invoices and medical documents with '
        "OCR and AI, then proves every value: found on the page, checked by finance rules, or "
        f'sent to a person. Nothing is guessed.</p><div class="ll-problems">{cards}</div>'
        f'<div class="ll-pills">{pills}</div></div>'
    )


def story(sector: str, text: str) -> str:
    return (
        f'<div class="ll-story"><div class="tag">{escape(sector)} demo</div>'
        f"<div>{escape(text)}</div></div>"
    )


def kpi(label: str, value: str, sub: str = "", tone: str = "", extra: str = "") -> str:
    return (
        f'<div class="ll-kpi {tone} {extra}"><div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div><div class="sub">{escape(sub)}</div></div>'
    )


def kpis(cards: list[str]) -> str:
    return f'<div class="ll-kpis">{"".join(cards)}</div>'


def result_kpis(s: Stats, seconds: float) -> str:
    rows = s.rows_total
    return kpis(
        [
            kpi(
                "Verdict",
                "Ready to approve" if s.ready else "Needs review",
                "every value proven" if s.ready else "a person must look at this",
                "good" if s.ready else "bad",
                "verdict",
            ),
            kpi(
                "Values with a receipt",
                f"{s.fields_proven} / {s.fields_total}",
                f"{len(s.removed)} removed: not on the page"
                if s.removed
                else "all found on the page",
                "good" if not s.removed else "bad",
            ),
            kpi(
                "Table rows proven",
                f"{s.rows_proven} / {rows}",
                "each row boxed on the page",
                "good" if s.rows_proven == rows else "warn",
            ),
            kpi(
                "Finance checks",
                f"{s.checks_passed} / {s.checks_run}",
                "passed" if s.checks_passed == s.checks_run else "failed checks shown below",
                "good" if s.checks_passed == s.checks_run else "bad",
            ),
            kpi("Processing time", f"{seconds:.1f} s", "read, extract, prove"),
        ]
    )


def steps(items: list[Step]) -> str:
    tiles = "".join(
        f'<div class="ll-step{" flag" if s.flag else ""}"><span class="ms">{s.ms} ms</span>'
        f'<div class="n"><i>{i}</i>{escape(s.name)}</div>'
        f'<div class="what">{escape(s.what)}</div></div>'
        for i, s in enumerate(items, 1)
    )
    return f'<div class="ll-steps">{tiles}</div>'


def compare(field: str, invented: str) -> str:
    name = escape(field.replace("_", " "))
    return (
        '<div class="ll-compare">'
        '<div class="ll-side typical"><h4>Typical AI pipeline</h4>'
        f"<code>{escape(field)}: {escape(invented)}</code>"
        f"<p>The model sounds sure, so the invented {name} goes straight into the ledger. "
        "Nobody notices until reconciliation fails weeks later.</p></div>"
        '<div class="ll-side ours"><h4>LedgerLens</h4>'
        f"<code>{escape(field)}: null (not on the page)</code>"
        f"<p>The {name} wasn't printed anywhere. LedgerLens asked the model once more, still "
        "couldn't find it, removed it and sent the document to review.</p></div></div>"
    )


def _money(d: Decimal | None) -> str:
    return "no receipt" if d is None else f"{d:,.2f}"


def proof_card(p: Proof) -> str:
    rows = "".join(
        f'<div class="row"><span>{escape(line.sign)} {escape(line.label)}</span>'
        f'<span class="amt">{_money(line.amount)}</span></div>'
        for line in p.lines
    )
    rows += (
        f'<div class="row total"><span>= {escape(p.computed_label)}</span>'
        f'<span class="amt">{_money(p.computed)}</span></div>'
        f'<div class="row"><span>{escape(p.printed_label)}</span>'
        f'<span class="amt">{_money(p.printed)}</span></div>'
    )
    if p.ok is None:
        verdict = ("na", "Can't be proven: a value has no receipt on the page")
    elif p.ok:
        verdict = ("ok", "Proven: the printed numbers add up")
    else:
        diff = (p.computed or Decimal(0)) - (p.printed or Decimal(0))
        verdict = ("bad", f"Doesn't add up: off by {abs(diff):,.2f}")
    return (
        f'<div class="ll-proof"><h4>{escape(p.title)}</h4>{rows}'
        f'<div class="verdict {verdict[0]}">{escape(verdict[1])}</div></div>'
    )


def caught(p: Proof | None, failures: list[tuple[str, str, list[int]]]) -> str:
    """What the checks stopped: failed rules in plain words, next to the recomputed maths."""
    items = "".join(
        f"<li><b>{escape(name)}</b><br><span>{escape(detail)}"
        + (
            f" (table rows {escape(', '.join(map(str, rows)))}, marked red on the page)"
            if rows
            else ""
        )
        + "</span></li>"
        for name, detail, rows in failures
    )
    card = proof_card(p) if p is not None and p.ok is False else ""
    return (
        '<div class="ll-caught"><div class="ll-caught-list"><h4>What LedgerLens caught</h4>'
        f"<ul>{items}</ul></div>{card}</div>"
    )


def legend(items: list[tuple[str, str]]) -> str:
    return (
        '<div class="ll-legend">'
        + "".join(f'<span style="background:{c}"></span>{escape(t)}' for c, t in items)
        + "</div>"
    )
