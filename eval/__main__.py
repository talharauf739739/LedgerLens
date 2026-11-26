"""Evaluation CLI.

    uv run python -m eval parse                      # parser recall (no LLM needed)
    uv run python -m eval extract --limit 5          # baseline LLM extraction (uses LLM_PROVIDER)

Synthetic data must exist first: `uv run python -m synth --count 20`.
Writes a Markdown report to reports/eval_<date>_<task>.md and prints it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path

from eval.runners import eval_extract, eval_parse, extract_report, load_samples, parse_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m eval")
    p.add_argument("task", choices=["parse", "extract"])
    p.add_argument("--data", type=Path, default=Path("data/synth"))
    p.add_argument("--doc-type", nargs="+", default=["bank_statement", "invoice"])
    p.add_argument("--variants", nargs="+", default=["clean", "noisy"])
    p.add_argument("--limit", type=int, default=10, help="documents per type and variant set")
    p.add_argument("--out", type=Path, default=Path("reports"))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    samples = load_samples(args.data, args.doc_type, args.variants, args.limit * len(args.variants))
    if not samples:
        p.error(f"no samples under {args.data}; run `python -m synth` first")

    if args.task == "parse":
        body = parse_report(eval_parse(samples))
        title = "Parse recall"
    else:
        from ledgerlens.llm import get_llm_client

        llm = get_llm_client()
        body = extract_report(asyncio.run(eval_extract(samples, llm)), llm.model)
        title = "Baseline extraction (no grounding)"

    report = (
        f"# {title}: {date.today().isoformat()}\n\n{len(samples)} synthetic documents.\n\n{body}\n"
    )
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"eval_{date.today().isoformat()}_{args.task}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
