"""`ledgerlens` command line. Phase 0: `hello` (LLM smoke test) and `init-storage`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


async def _hello() -> int:
    from ledgerlens.llm import get_llm_client

    llm = get_llm_client()
    reply = await llm.chat(
        [
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Reply with exactly: LedgerLens is alive."},
        ],
        max_tokens=20,
        temperature=0,
    )
    print(f"[{llm.provider} / {llm.model}] {reply.strip()}")
    return 0


async def _init_storage() -> int:
    from ledgerlens.config import get_settings
    from ledgerlens.storage import ensure_resources

    settings = get_settings()
    await ensure_resources(settings)
    print(f"Ready: container '{settings.blob_container}', queue '{settings.jobs_queue}'")
    return 0


async def _extract(data: bytes, doc_type: str | None) -> str:
    import json

    from ledgerlens.llm import get_llm_client
    from ledgerlens.pipeline.process import process_pdf

    result = await process_pdf(data, doc_type, get_llm_client())
    payload = {
        **result.document.model_dump_doc(exclude={"markdown"}),
        "review": {
            "needs_review": result.needs_review,
            "ungrounded_fields": result.grounding.ungrounded,
            "ungrounded_rows": result.grounding.rows_ungrounded,
            "issues": result.issues,
        },
        "classification": {
            "doc_type": result.classification.doc_type,
            "method": result.classification.method,
            "confidence": result.classification.confidence,
        },
        "provenance": {
            "model": result.model,
            "prompt_version": result.prompt_version,
            "attempts": result.attempts,
            "trace": result.trace,
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerlens")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hello", help="Send one prompt to the configured LLM provider")
    sub.add_parser("init-storage", help="Create the blob container and jobs queue")
    ex = sub.add_parser("extract", help="Parse, extract, ground and validate one PDF")
    ex.add_argument("pdf")
    ex.add_argument(
        "--doc-type",
        choices=["auto", "bank_statement", "invoice"],
        default="auto",
        help="default: let the classifier decide",
    )
    ex.add_argument("-o", "--out", help="write JSON here instead of stdout")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if args.command == "extract":
        from pathlib import Path

        doc_type = None if args.doc_type == "auto" else args.doc_type
        text = asyncio.run(_extract(Path(args.pdf).read_bytes(), doc_type))
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"Written to {args.out}")
        else:
            print(text)
        return 0
    commands = {"hello": _hello, "init-storage": _init_storage}
    return asyncio.run(commands[args.command]())


if __name__ == "__main__":
    sys.exit(main())
