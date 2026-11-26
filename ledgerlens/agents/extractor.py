"""Baseline extractor: document Markdown -> draft JSON (values as printed) -> typed document.

One LLM call per document, schema in the prompt, JSON parsed and validated against the
draft model. Invalid JSON gets one repair attempt; after that the output is rejected.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from pydantic import ValidationError

from ledgerlens.agents.drafts import DRAFTS, to_document
from ledgerlens.llm import LLMClient
from ledgerlens.schemas import BaseDocument

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


class ExtractionError(RuntimeError):
    pass


@dataclass
class Extraction:
    document: BaseDocument
    draft: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION
    model: str = ""


def load_prompt(doc_type: str, version: str = PROMPT_VERSION) -> str:
    template = (
        resources.files("ledgerlens.agents")
        .joinpath(f"prompts/extractor/{doc_type}/{version}.md")
        .read_text(encoding="utf-8")
    )
    schema = json.dumps(DRAFTS[doc_type].model_json_schema(), indent=1)
    return template.replace("{schema}", schema)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates ``` fences and chatter)."""
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    start = candidate.find("{")
    if start == -1:
        raise ValueError("no JSON object in reply")
    obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


def _wrap_document(markdown: str) -> str:
    # Clear delimiters so the model can tell data from instructions.
    return f"<document>\n{markdown}\n</document>"


async def extract(
    llm: LLMClient, doc_type: str, markdown: str, *, max_tokens: int = 8192
) -> Extraction:
    draft_model = DRAFTS[doc_type]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": load_prompt(doc_type)},
        {"role": "user", "content": _wrap_document(markdown)},
    ]
    last_error = ""
    for attempt in range(2):
        reply = await llm.chat(messages, temperature=0, max_tokens=max_tokens)
        try:
            raw = parse_json_object(reply)
            draft = draft_model.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:500]
            log.warning("extractor attempt %d: invalid output: %s", attempt + 1, last_error)
            messages += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": "That was not a valid JSON object for the schema "
                    f"({last_error}). Reply with only the corrected JSON object.",
                },
            ]
            continue
        document, issues = to_document(doc_type, draft)
        return Extraction(
            document=document, draft=draft.model_dump(), issues=issues, model=llm.model
        )
    raise ExtractionError(f"model output rejected after 2 attempts: {last_error}")
