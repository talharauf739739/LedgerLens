"""Process one document end to end. Thin wrapper over the agent workflow
(`ledgerlens.agents.workflow`): parse -> classify -> extract -> ground -> validate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ledgerlens.agents.classifier import Classification
from ledgerlens.agents.extractor import PROMPT_VERSION
from ledgerlens.pipeline.ground import GroundingReport
from ledgerlens.pipeline.spans import ParsedDocument
from ledgerlens.schemas import BaseDocument


@dataclass
class ProcessResult:
    document: BaseDocument
    parsed: ParsedDocument
    grounding: GroundingReport
    classification: Classification
    needs_review: bool
    attempts: int = 1
    issues: list[str] = field(default_factory=list)
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    trace: list[dict[str, Any]] = field(default_factory=list)


async def process_pdf(data: bytes, doc_type: str | None, llm: Any) -> ProcessResult:
    """`doc_type=None` lets the classifier decide."""
    from ledgerlens.agents.workflow import run_workflow

    job = await run_workflow(data, llm, doc_type)
    assert job.document and job.parsed and job.grounding and job.classification
    return ProcessResult(
        document=job.document,
        parsed=job.parsed,
        grounding=job.grounding,
        classification=job.classification,
        needs_review=job.needs_review,
        attempts=job.attempts,
        issues=job.issues,
        model=job.model,
        trace=job.trace,
    )
