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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerlens")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hello", help="Send one prompt to the configured LLM provider")
    sub.add_parser("init-storage", help="Create the blob container and jobs queue")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    commands = {"hello": _hello, "init-storage": _init_storage}
    return asyncio.run(commands[args.command]())


if __name__ == "__main__":
    sys.exit(main())
