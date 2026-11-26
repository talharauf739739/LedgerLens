"""The whole pipeline for one document: parse -> extract -> ground -> validate.

Agents propose (extract); code decides (ground + rules). The returned document carries
receipts for every value it keeps and the rule results that judged it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgerlens.agents.extractor import extract
from ledgerlens.llm import LLMClient
from ledgerlens.pipeline.ground import GroundingReport, ground_document
from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.pipeline.spans import ParsedDocument
from ledgerlens.rules import validate
from ledgerlens.schemas import BaseDocument, RuleStatus


@dataclass
class ProcessResult:
    document: BaseDocument
    parsed: ParsedDocument
    grounding: GroundingReport
    issues: list[str] = field(default_factory=list)
    model: str = ""
    prompt_version: str = ""

    @property
    def needs_review(self) -> bool:
        """Anything ungrounded or any failed rule sends the document to a human."""
        return bool(
            self.grounding.ungrounded
            or self.grounding.rows_ungrounded
            or any(r.status is RuleStatus.FAIL for r in self.document.validation)
        )


async def process_pdf(data: bytes, doc_type: str, llm: LLMClient) -> ProcessResult:
    parsed = parse_pdf(data)
    extraction = await extract(llm, doc_type, parsed.markdown)
    grounded, report = ground_document(extraction.document, extraction.draft, parsed)
    final = grounded.model_copy(
        update={"validation": validate(grounded), "markdown": parsed.markdown}
    )
    return ProcessResult(
        document=final,
        parsed=parsed,
        grounding=report,
        issues=extraction.issues,
        model=extraction.model,
        prompt_version=extraction.prompt_version,
    )
