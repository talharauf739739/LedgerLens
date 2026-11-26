"""Document type classification: cue phrases decide; the LLM is asked only when unsure."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from ledgerlens.agents.extractor import parse_json_object
from ledgerlens.schemas import REGISTRY

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

# Lower-case cue phrases per type, matched on word boundaries in the first pages' Markdown.
CUES: dict[str, tuple[str, ...]] = {
    "bank_statement": (
        "statement period",
        "opening balance",
        "closing balance",
        "balance brought forward",
        "balance carried forward",
        "account number",
        "withdrawals",
        "deposits",
        "money in",
        "money out",
        "kontoauszug",
        "saldo",
        "verwendungszweck",
        "iban",
    ),
    "invoice": (
        "invoice",
        "invoice no",
        "bill to",
        "subtotal",
        "unit price",
        "total due",
        "vat",
        "due date",
        "qty",
        "rechnung",
        "facture",
        "factuur",
        "line total",
        "payment terms",
    ),
}

DECISIVE_SCORE = 3  # cues needed for the top label...
DECISIVE_MARGIN = 2  # ...and its lead over the runner-up, to skip the LLM


@dataclass(frozen=True)
class Classification:
    doc_type: str  # a REGISTRY key, or "other"
    confidence: float
    method: str  # "cues" | "llm" | "given"
    scores: dict[str, int]


def cue_scores(markdown: str) -> dict[str, int]:
    text = markdown.lower()
    return {
        label: sum(1 for cue in cues if re.search(rf"\b{re.escape(cue)}\b", text))
        for label, cues in CUES.items()
    }


def _first_pages(markdown: str, pages: int = 2) -> str:
    parts = markdown.split("<!-- page ")
    return "<!-- page ".join(parts[: pages + 1])


async def classify(markdown: str, llm: Any | None = None) -> Classification:
    head = _first_pages(markdown)
    scores = cue_scores(head)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top, top_score), (_, second) = ranked[0], ranked[1]
    if top_score >= DECISIVE_SCORE and top_score - second >= DECISIVE_MARGIN:
        return Classification(top, round(top_score / (top_score + second), 3), "cues", scores)

    if llm is not None:
        prompt = (
            resources.files("ledgerlens.agents")
            .joinpath(f"prompts/classifier/{PROMPT_VERSION}.md")
            .read_text(encoding="utf-8")
        )
        reply = await llm.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"<document>\n{head[:6000]}\n</document>"},
            ],
            temperature=0,
            max_tokens=60,
        )
        try:
            obj = parse_json_object(reply)
            label = str(obj.get("doc_type", "other"))
            conf = float(obj.get("confidence", 0.5))
        except (ValueError, TypeError):
            log.warning("classifier: unusable LLM reply")
        else:
            if label in REGISTRY or label == "other":
                return Classification(label, max(0.0, min(conf, 1.0)), "llm", scores)

    # No decisive cues and no usable LLM answer: best cue guess, low confidence.
    label = top if top_score > second else "other"
    return Classification(label, 0.5 if label != "other" else 0.0, "cues", scores)
