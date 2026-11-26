"""Pure metric functions (no I/O), unit-tested."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Hashable, Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz


def norm_text(s: str) -> str:
    """Case/space/punctuation-insensitive form for text comparison."""
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s\u00a0]+", " ", s).strip()


def compact(s: str) -> str:
    return re.sub(r"\s+", "", norm_text(s))


def text_found(needle: str, haystack: str, *, min_score: float = 90.0) -> bool:
    """Exact (space-insensitive) containment, else fuzzy partial match for OCR noise."""
    n, h = compact(needle), compact(haystack)
    if not n:
        return False
    if n in h:
        return True
    return len(n) >= 4 and fuzz.partial_ratio(n, h) >= min_score


def overlaps(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float], slack: float = 2.0
) -> bool:
    return not (
        a[2] + slack < b[0] or b[2] + slack < a[0] or a[3] + slack < b[1] or b[3] + slack < a[1]
    )


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: PRF) -> None:
        self.tp, self.fp, self.fn = self.tp + other.tp, self.fp + other.fp, self.fn + other.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def field_prf(truth: object | None, pred: object | None) -> PRF:
    """Single-field scoring: a wrong non-null prediction is both a FP and a FN."""
    if truth is None and pred is None:
        return PRF()
    if truth is None:
        return PRF(fp=1)
    if pred is None:
        return PRF(fn=1)
    return PRF(tp=1) if truth == pred else PRF(fp=1, fn=1)


def multiset_prf(truth: Iterable[Hashable], pred: Iterable[Hashable]) -> PRF:
    """Row-level matching as multisets of keys (order-insensitive, duplicates counted)."""
    remaining: dict[Hashable, int] = {}
    for t in truth:
        remaining[t] = remaining.get(t, 0) + 1
    tp = fp = 0
    for p in pred:
        if remaining.get(p, 0) > 0:
            remaining[p] -= 1
            tp += 1
        else:
            fp += 1
    return PRF(tp=tp, fp=fp, fn=sum(remaining.values()))
