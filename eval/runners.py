"""Score the parser and the extractor against synthetic ground truth."""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.metrics import PRF, field_prf, multiset_prf, overlaps, text_found
from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.pipeline.spans import ParsedDocument
from ledgerlens.rules import validate
from ledgerlens.schemas import REGISTRY, BaseDocument, RuleStatus


@dataclass
class Sample:
    pdf: Path
    truth: dict[str, Any]

    @property
    def meta(self) -> dict[str, Any]:
        return self.truth["synthetic"]  # type: ignore[no-any-return]

    @property
    def document(self) -> BaseDocument:
        doc = self.truth["document"]
        return REGISTRY[doc["doc_type"]].model_validate(doc)


def load_samples(root: Path, doc_types: list[str], variants: list[str], limit: int) -> list[Sample]:
    samples: list[Sample] = []
    for doc_type in doc_types:
        found = 0
        for truth_path in sorted((root / doc_type).glob("*.truth.json")):
            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            if truth["synthetic"]["variant"] not in variants:
                continue
            samples.append(
                Sample(truth_path.with_name(truth_path.name.replace(".truth.json", ".pdf")), truth)
            )
            found += 1
            if found >= limit:
                break
    return samples


# --- parse recall ------------------------------------------------------------------------


@dataclass
class ParseStats:
    fields_total: int = 0
    fields_found: int = 0
    rows_total: int = 0
    rows_found: int = 0
    seconds: list[float] = field(default_factory=list)
    pages: int = 0
    misses: list[str] = field(default_factory=list)


def _found_near(parsed: ParsedDocument, text: str, page: int, bbox: tuple[float, ...]) -> bool:
    """Is `text` on a parsed line that overlaps the truth bbox on the right page?"""
    p = parsed.pages[page - 1]
    return any(
        overlaps(line.bbox, bbox) and text_found(text, line.text)  # type: ignore[arg-type]
        for line in p.lines
    )


def eval_parse(samples: list[Sample]) -> dict[str, ParseStats]:
    stats: dict[str, ParseStats] = defaultdict(ParseStats)
    for sample in samples:
        key = f"{sample.meta['doc_type']}/{sample.meta['variant']}"
        st = stats[key]
        t = time.perf_counter()
        parsed = parse_pdf(sample.pdf.read_bytes())
        st.seconds.append(time.perf_counter() - t)
        st.pages += len(parsed.pages)
        doc = sample.document
        for name, printed in sample.meta["printed"].items():
            src = getattr(doc.fields, name).source  # type: ignore[attr-defined]
            st.fields_total += 1
            if _found_near(parsed, printed, src.page, src.bbox):
                st.fields_found += 1
            else:
                st.misses.append(f"{sample.meta['id']}:{name}={printed!r}")
        rows = getattr(doc, "transactions", None) or getattr(doc, "line_items", [])
        for row in rows:
            st.rows_total += 1
            if _found_near(parsed, row.description, row.source.page, row.source.bbox):
                st.rows_found += 1
    return dict(stats)


def parse_report(stats: dict[str, ParseStats]) -> str:
    lines = [
        "| Set | Docs | Pages | Field recall | Row recall | Sec/page (median) |",
        "|---|---|---|---|---|---|",
    ]
    for key, st in sorted(stats.items()):
        per_page = statistics.median(st.seconds) * len(st.seconds) / max(st.pages, 1)
        lines.append(
            f"| {key} | {len(st.seconds)} | {st.pages} | "
            f"{st.fields_found}/{st.fields_total} "
            f"({st.fields_found / max(st.fields_total, 1):.1%}) | "
            f"{st.rows_found}/{st.rows_total} ({st.rows_found / max(st.rows_total, 1):.1%}) | "
            f"{per_page:.2f} |"
        )
    misses = [m for st in stats.values() for m in st.misses]
    if misses:
        lines += ["", f"Missed fields ({len(misses)}, first 20):", ""]
        lines += [f"- `{m}`" for m in misses[:20]]
    return "\n".join(lines)


# --- extraction --------------------------------------------------------------------------


@dataclass
class ExtractStats:
    fields_raw: PRF = field(default_factory=PRF)  # straight from the LLM
    fields: PRF = field(default_factory=PRF)  # after grounding
    rows_raw: PRF = field(default_factory=PRF)
    rows: PRF = field(default_factory=PRF)
    proposed: int = 0  # non-null values the LLM proposed
    hallucinated: int = 0  # ...of which not found on the page (nulled by grounding)
    docs: int = 0
    failed: int = 0
    review: int = 0
    rule_disagree: int = 0
    seconds: list[float] = field(default_factory=list)
    per_field: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))


def _row_key(doc_type: str, row: Any) -> tuple[Any, ...]:
    if doc_type == "bank_statement":
        return (row.date, row.amount, row.direction, row.balance)
    return (row.quantity, row.unit_price, row.amount)


def _score_fields(truth: BaseDocument, pred: BaseDocument) -> dict[str, PRF]:
    out = {}
    for name in type(truth.fields).model_fields:  # type: ignore[attr-defined]
        t_val = getattr(truth.fields, name)  # type: ignore[attr-defined]
        if hasattr(t_val, "value"):
            out[name] = field_prf(t_val.value, getattr(pred.fields, name).value)  # type: ignore[attr-defined]
    return out


def _score_rows(doc_type: str, truth: BaseDocument, pred: BaseDocument, grounded_only: bool) -> PRF:
    attr = "transactions" if doc_type == "bank_statement" else "line_items"
    rows = [r for r in getattr(pred, attr) if not grounded_only or r.source is not None]
    return multiset_prf(
        (_row_key(doc_type, r) for r in getattr(truth, attr)),
        (_row_key(doc_type, r) for r in rows),
    )


async def eval_extract(samples: list[Sample], llm: Any) -> dict[str, ExtractStats]:
    from ledgerlens.agents.extractor import ExtractionError, extract
    from ledgerlens.pipeline.ground import ground_document

    stats: dict[str, ExtractStats] = defaultdict(ExtractStats)
    for sample in samples:
        doc_type = sample.meta["doc_type"]
        st = stats[f"{doc_type}/{sample.meta['variant']}"]
        st.docs += 1
        truth = sample.document
        t = time.perf_counter()
        try:
            parsed = parse_pdf(sample.pdf.read_bytes())
            extraction = await extract(llm, doc_type, parsed.markdown)
            grounded, report = ground_document(extraction.document, extraction.draft, parsed)
        except (ExtractionError, ValueError):
            st.failed += 1
            continue
        finally:
            st.seconds.append(time.perf_counter() - t)

        for prf in _score_fields(truth, extraction.document).values():
            st.fields_raw.add(prf)
        for name, prf in _score_fields(truth, grounded).items():
            st.fields.add(prf)
            st.per_field[name].add(prf)
        st.rows_raw.add(_score_rows(doc_type, truth, extraction.document, grounded_only=False))
        st.rows.add(_score_rows(doc_type, truth, grounded, grounded_only=True))

        st.proposed += len(report.grounded) + len(report.ungrounded)
        st.hallucinated += len(report.ungrounded)

        results = validate(grounded)
        failed = {r.rule for r in results if r.status is RuleStatus.FAIL}
        if failed:
            st.review += 1
        if failed - {"all_values_grounded"} != set(sample.meta["expected_failures"]):
            st.rule_disagree += 1
    return dict(stats)


def _prf(p: PRF) -> str:
    return f"{p.precision:.0%} / {p.recall:.0%} / **{p.f1:.1%}**"


def extract_report(stats: dict[str, ExtractStats], model: str) -> str:
    lines = [
        f"Model: `{model}`. P / R / F1 against the synthetic truth.",
        "",
        "| Set | Docs | Rejected | Fields: raw LLM | Fields: grounded | Rows: raw | "
        "Rows: grounded | Hallucinated (nulled) | Sent to review | Rules wrong | Sec/doc |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, st in sorted(stats.items()):
        halluc = st.hallucinated / st.proposed if st.proposed else 0.0
        lines.append(
            f"| {key} | {st.docs} | {st.failed} | {_prf(st.fields_raw)} | {_prf(st.fields)} | "
            f"{_prf(st.rows_raw)} | {_prf(st.rows)} | {st.hallucinated}/{st.proposed} "
            f"({halluc:.1%}) | {st.review}/{st.docs} | {st.rule_disagree} | "
            f"{statistics.median(st.seconds) if st.seconds else 0:.1f} |"
        )
    totals: dict[str, PRF] = defaultdict(PRF)
    for st in stats.values():
        for name, prf in st.per_field.items():
            totals[name].add(prf)
    lines += [
        "",
        '"Rules wrong" counts documents whose failed finance rules differ from the truth '
        "(clean: none; tampered: exactly the planted ones).",
        "",
        "Per-field F1 after grounding (all sets):",
        "",
        "| Field | F1 |",
        "|---|---|",
    ]
    lines += [f"| {n} | {p.f1:.1%} |" for n, p in sorted(totals.items(), key=lambda kv: kv[1].f1)]
    return "\n".join(lines)
