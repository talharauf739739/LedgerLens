"""The extraction workflow (Microsoft Agent Framework): a fixed, auditable graph.

    Parse -> Classify -> Extract -> Ground -> Validate -> result
                           ^          |
                           +----------+  one retry for values grounding couldn't find

Agents (classifier, extractor) only propose. Grounding and the finance rules decide what is
kept. Every step appends to `Job.trace`, which becomes the job's audit log.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agent_framework import Executor, Workflow, WorkflowBuilder, WorkflowContext, handler

from ledgerlens.agents.classifier import Classification, classify
from ledgerlens.agents.drafts import DRAFTS, draft_key, to_document
from ledgerlens.agents.extractor import PROMPT_VERSION, Feedback, extract
from ledgerlens.pipeline.ground import GroundingReport, ground_document
from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.pipeline.spans import ParsedDocument
from ledgerlens.rules import validate
from ledgerlens.schemas import REGISTRY, BaseDocument, RuleStatus

MAX_EXTRACT_ATTEMPTS = 2


class UnsupportedDocument(ValueError):
    pass


@dataclass
class Job:
    """Everything one document accumulates on its way through the graph."""

    data: bytes
    doc_type: str | None = None
    parsed: ParsedDocument | None = None
    classification: Classification | None = None
    draft: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    document: BaseDocument | None = None
    grounding: GroundingReport | None = None
    attempts: int = 0
    model: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)

    def log(self, step: str, started: float, **detail: Any) -> None:
        self.trace.append(
            {"step": step, "ms": round((time.perf_counter() - started) * 1000), **detail}
        )

    @property
    def needs_review(self) -> bool:
        g, d = self.grounding, self.document
        return bool(
            (g and (g.ungrounded or g.rows_ungrounded))
            or (d and any(r.status is RuleStatus.FAIL for r in d.validation))
        )


# Message types: the edges route on these.
@dataclass
class Parsed:
    job: Job


@dataclass
class Classified:
    job: Job


@dataclass
class Retry:
    job: Job
    feedback: Feedback


@dataclass
class Grounded:
    job: Job


class ParseStep(Executor):
    @handler
    async def run(self, job: Job, ctx: WorkflowContext[Parsed]) -> None:
        t = time.perf_counter()
        job.parsed = parse_pdf(job.data)
        kinds = [p.kind for p in job.parsed.pages]
        job.log("parse", t, pages=len(kinds), scanned=kinds.count("scanned"))
        await ctx.send_message(Parsed(job))


class ClassifyStep(Executor):
    def __init__(self, llm: Any, id: str = "classify") -> None:
        super().__init__(id=id)
        self.llm = llm

    @handler
    async def run(self, msg: Parsed, ctx: WorkflowContext[Classified]) -> None:
        job, t = msg.job, time.perf_counter()
        assert job.parsed is not None
        if job.doc_type is None:
            job.classification = await classify(job.parsed.markdown, self.llm)
            job.doc_type = job.classification.doc_type
        else:
            job.classification = Classification(job.doc_type, 1.0, "given", {})
        if job.doc_type not in REGISTRY:
            raise UnsupportedDocument(f"unsupported document type: {job.doc_type!r}")
        c = job.classification
        job.log("classify", t, doc_type=job.doc_type, method=c.method, confidence=c.confidence)
        await ctx.send_message(Classified(job))


class ExtractStep(Executor):
    def __init__(self, llm: Any, id: str = "extract") -> None:
        super().__init__(id=id)
        self.llm = llm

    @handler
    async def run(self, msg: Classified | Retry, ctx: WorkflowContext[Grounded]) -> None:
        job, t = msg.job, time.perf_counter()
        assert job.parsed is not None and job.doc_type is not None
        feedback = msg.feedback if isinstance(msg, Retry) else None
        result = await extract(self.llm, job.doc_type, job.parsed.markdown, feedback=feedback)
        job.attempts += 1
        job.model = result.model
        if feedback is None:
            job.draft, job.issues = result.draft, result.issues
        else:
            # Only the values that weren't found are replaced; grounded ones stay as they were.
            for key in feedback.not_found:
                job.draft[key] = result.draft.get(key)
        draft_model = DRAFTS[job.doc_type].model_validate(job.draft)
        job.document, issues = to_document(job.doc_type, draft_model)
        if feedback is not None:
            job.issues = issues
        job.log("extract", t, attempt=job.attempts, model=result.model, prompt=PROMPT_VERSION)
        await ctx.send_message(Grounded(job))


class GroundStep(Executor):
    """Grounds the proposal; loops back to the extractor once if values weren't found."""

    @handler
    async def run(self, msg: Grounded, ctx: WorkflowContext[Grounded | Retry]) -> None:
        job, t = msg.job, time.perf_counter()
        assert job.document is not None and job.parsed is not None
        job.document, job.grounding = ground_document(job.document, job.draft, job.parsed)
        g = job.grounding
        job.log(
            "ground",
            t,
            grounded=len(g.grounded),
            ungrounded=list(g.ungrounded),
            rows_grounded=g.rows_grounded,
            rows_ungrounded=list(g.rows_ungrounded),
        )
        if g.ungrounded and job.attempts < MAX_EXTRACT_ATTEMPTS:
            not_found = [draft_key(name) for name in g.ungrounded]
            await ctx.send_message(Retry(job, Feedback(dict(job.draft), not_found)))
        else:
            await ctx.send_message(Grounded(job))


class ValidateStep(Executor):
    @handler
    async def run(self, msg: Grounded, ctx: WorkflowContext[None, Job]) -> None:
        job, t = msg.job, time.perf_counter()
        assert job.document is not None and job.parsed is not None
        results = validate(job.document)
        job.document = job.document.model_copy(
            update={"validation": results, "markdown": job.parsed.markdown}
        )
        failed = [r.rule for r in results if r.status is RuleStatus.FAIL]
        job.log("validate", t, failed=failed, needs_review=job.needs_review)
        await ctx.yield_output(job)


def build_workflow(llm: Any) -> Workflow:
    parse = ParseStep(id="parse")
    classify_ = ClassifyStep(llm)
    extract_ = ExtractStep(llm)
    ground = GroundStep(id="ground")
    validate_ = ValidateStep(id="validate")
    return (
        WorkflowBuilder(
            name="ledgerlens-extraction",
            description="parse -> classify -> extract -> ground -> validate",
            start_executor=parse,
        )
        .add_edge(parse, classify_)
        .add_edge(classify_, extract_)
        .add_edge(extract_, ground)
        .add_edge(ground, extract_, condition=lambda m: isinstance(m, Retry))
        .add_edge(ground, validate_, condition=lambda m: isinstance(m, Grounded))
        .build()
    )


async def run_workflow(data: bytes, llm: Any, doc_type: str | None = None) -> Job:
    """Process one PDF. `doc_type=None` lets the classifier decide."""
    result = await build_workflow(llm).run(Job(data=data, doc_type=doc_type))
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError(f"workflow produced no result (state: {result.get_final_state()})")
    job: Job = outputs[-1]
    return job
