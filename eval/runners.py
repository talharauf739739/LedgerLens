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
    fields: PRF = field(default_factory=PRF)
    rows: PRF = field(default_factory=PRF)
    docs: int = 0
    failed: int = 0
    rule_fail_docs: int = 0
    seconds: list[float] = field(default_factory=list)
    per_field: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))


def _row_key(doc_type: str, row: Any) -> tuple[Any, ...]:
    if doc_type == "bank_statement":
        return (row.date, row.amount, row.direction, row.balance)
    return (row.quantity, row.unit_price, row.amount)


async def eval_extract(samples: list[Sample], llm: Any) -> dict[str, ExtractStats]:
    from ledgerlens.agents.extractor import ExtractionError, extract

    stats: dict[str, ExtractStats] = defaultdict(ExtractStats)
    for sample in samples:
        doc_type = sample.meta["doc_type"]
        st = stats[f"{doc_type}/{sample.meta['variant']}"]
        st.docs += 1
        truth = sample.document
        t = time.perf_counter()
        try:
            parsed = parse_pdf(sample.pdf.read_bytes())
            result = await extract(llm, doc_type, parsed.markdown)
        except (ExtractionError, ValueError):
            st.failed += 1
            continue
        finally:
            st.seconds.append(time.perf_counter() - t)
        pred = result.document
        for name in type(truth.fields).model_fields:  # type: ignore[attr-defined]
            t_val = getattr(truth.fields, name)  # type: ignore[attr-defined]
            p_val = getattr(pred.fields, name)  # type: ignore[attr-defined]
            if not hasattr(t_val, "value"):
                continue
            r = field_prf(t_val.value, p_val.value)
            st.fields.add(r)
            st.per_field[name].add(r)
        rows_attr = "transactions" if doc_type == "bank_statement" else "line_items"
        st.rows.add(
            multiset_prf(
                (_row_key(doc_type, r) for r in getattr(truth, rows_attr)),
                (_row_key(doc_type, r) for r in getattr(pred, rows_attr)),
            )
        )
        arithmetic = {r.rule for r in validate(pred) if r.status is RuleStatus.FAIL} - {
            "all_values_grounded"
        }  # grounding comes in phase 3
        expected = set(sample.meta["expected_failures"])
        if arithmetic != expected:
            st.rule_fail_docs += 1
    return dict(stats)


def extract_report(stats: dict[str, ExtractStats], model: str) -> str:
    lines = [
        f"Model: `{model}`",
        "",
        "| Set | Docs | Rejected | Field P / R / F1 | Row P / R / F1 | Rules disagree "
        "| Sec/doc (median) |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, st in sorted(stats.items()):
        f, r = st.fields, st.rows
        lines.append(
            f"| {key} | {st.docs} | {st.failed} | "
            f"{f.precision:.1%} / {f.recall:.1%} / **{f.f1:.1%}** | "
            f"{r.precision:.1%} / {r.recall:.1%} / **{r.f1:.1%}** | "
            f"{st.rule_fail_docs} | {statistics.median(st.seconds) if st.seconds else 0:.1f} |"
        )
    worst: dict[str, PRF] = defaultdict(PRF)
    for st in stats.values():
        for name, prf in st.per_field.items():
            worst[name].add(prf)
    lines += ["", "Per-field F1 (all sets):", "", "| Field | F1 |", "|---|---|"]
    lines += [f"| {n} | {p.f1:.1%} |" for n, p in sorted(worst.items(), key=lambda kv: kv[1].f1)]
    return "\n".join(lines)
