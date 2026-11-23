"""Deterministic validation. No LLM here: agents propose, these rules decide."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any, TypeVar

from ledgerlens.schemas.base import BaseDocument, Field, RuleResult, RuleStatus

TOLERANCE = Decimal("0.01")

D = TypeVar("D", bound=BaseDocument)
Rule = Callable[[D], RuleResult]


def money_eq(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


def passed(rule: str, detail: str = "") -> RuleResult:
    return RuleResult(rule=rule, status=RuleStatus.PASS, detail=detail)


def failed(rule: str, detail: str, rows: Iterable[int] = ()) -> RuleResult:
    return RuleResult(rule=rule, status=RuleStatus.FAIL, detail=detail, rows=list(rows))


def warned(rule: str, detail: str, rows: Iterable[int] = ()) -> RuleResult:
    return RuleResult(rule=rule, status=RuleStatus.WARN, detail=detail, rows=list(rows))


def skipped(rule: str, missing: str) -> RuleResult:
    return RuleResult(rule=rule, status=RuleStatus.SKIP, detail=f"missing: {missing}")


def value(f: Field[Any]) -> Any:
    return f.value


def run_rules(doc: D, rules: Iterable[Callable[[D], RuleResult]]) -> list[RuleResult]:
    return [rule(doc) for rule in rules]
