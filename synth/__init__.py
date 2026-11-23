"""Synthetic fintech documents with ground truth. Fake by construction: never real data."""

from collections.abc import Callable

from synth import bank_statement, invoice
from synth.common import Generated

GENERATORS: dict[str, Callable[..., Generated]] = {
    "bank_statement": bank_statement.generate,
    "invoice": invoice.generate,
}

__all__ = ["GENERATORS", "Generated"]
