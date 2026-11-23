"""Rules that apply to every document type."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ledgerlens.rules.base import failed, passed, skipped
from ledgerlens.schemas.base import BaseDocument, Field, FieldStatus, RuleResult

# Active ISO-4217 codes (2026). Funds/metal/test codes (XAU, XTS...) deliberately excluded.
ISO_4217 = frozenset(
    """AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
    CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP
    GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD
    KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN
    NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP
    SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND
    VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG""".split()
)


def _fields(doc: BaseDocument) -> dict[str, Field[object]]:
    fields = getattr(doc, "fields", None)
    if not isinstance(fields, BaseModel):
        return {}
    return {
        name: f
        for name in type(fields).model_fields
        if isinstance(f := getattr(fields, name), Field)
    }


def all_values_grounded(doc: BaseDocument) -> RuleResult:
    """Every non-null value must carry a source span (the 'receipt')."""
    rule = "all_values_grounded"
    bad = [n for n, f in _fields(doc).items() if f.value is not None and f.source is None]
    rows_attr: list[Any] = next(
        (getattr(doc, a) for a in ("transactions", "line_items") if hasattr(doc, a)), []
    )
    bad_rows = [i for i, r in enumerate(rows_attr) if getattr(r, "source", None) is None]
    if bad or bad_rows:
        return failed(rule, f"no source for: {', '.join(bad) or '-'}", bad_rows)
    ungrounded = [n for n, f in _fields(doc).items() if f.status is FieldStatus.UNGROUNDED]
    if ungrounded:
        return failed(rule, f"ungrounded (needs review): {', '.join(ungrounded)}")
    return passed(rule)


def currency_is_iso4217(doc: BaseDocument) -> RuleResult:
    rule = "currency_iso4217"
    f = _fields(doc).get("currency")
    if f is None or f.value is None:
        return skipped(rule, "currency")
    code = str(f.value)
    return passed(rule) if code in ISO_4217 else failed(rule, f"{code!r} is not an ISO-4217 code")
