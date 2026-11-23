"""Generate a synthetic dataset.

    uv run python -m synth --count 20
    uv run python -m synth --doc-type invoice --count 5 --variants clean tampered

Writes data/synth/<doc_type>/<id>[_noisy|_tampered].pdf + .truth.json (data/ is git-ignored).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from synth import GENERATORS
from synth.common import Generated
from synth.noise import make_noisy


def _write(out_dir: Path, gen: Generated) -> None:
    (out_dir / f"{gen.meta.id}.pdf").write_bytes(gen.pdf)
    (out_dir / f"{gen.meta.id}.truth.json").write_text(
        json.dumps(gen.truth_json(), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m synth", description=__doc__.splitlines()[0])
    p.add_argument("--doc-type", nargs="+", choices=sorted(GENERATORS), default=sorted(GENERATORS))
    p.add_argument("--count", type=int, default=10, help="base documents per type")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument(
        "--variants",
        nargs="+",
        choices=["clean", "noisy", "tampered"],
        default=["clean", "noisy", "tampered"],
    )
    p.add_argument("--out", type=Path, default=Path("data/synth"))
    args = p.parse_args(argv)

    for doc_type in args.doc_type:
        out_dir = args.out / doc_type
        out_dir.mkdir(parents=True, exist_ok=True)
        generate = GENERATORS[doc_type]
        for i in range(args.count):
            seed = args.seed * 1_000_000 + i
            doc_id = f"{doc_type}_{i:05d}"
            clean = generate(seed, doc_id)
            if "clean" in args.variants:
                _write(out_dir, clean)
            if "noisy" in args.variants:
                _write(out_dir, make_noisy(clean, seed))
            if "tampered" in args.variants:
                tampered = generate(seed, doc_id, tamper=True)
                tampered.meta.id = f"{doc_id}_tampered"
                _write(out_dir, tampered)
        print(
            f"{doc_type}: {args.count} base documents x {len(args.variants)} variants -> {out_dir}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
