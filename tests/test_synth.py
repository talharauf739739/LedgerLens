"""The generators are the ground truth for every later phase, so they're held to:
clean docs pass every rule; tampered docs fail exactly the rules they claim; and the
text inside each truth bbox is exactly what the truth says was printed."""

import re

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from ledgerlens.rules import validate
from ledgerlens.schemas import REGISTRY, RuleStatus
from synth import GENERATORS
from synth.common import Generated
from synth.noise import make_noisy, rotate_bbox

SEEDS = range(12)  # enough to hit every template, font family and country
CASES = [(t, s) for t in sorted(GENERATORS) for s in SEEDS]


def _text_in_box(pdf: pdfium.PdfDocument, page: int, bbox: tuple[float, ...]) -> str:
    p = pdf[page - 1]
    h = p.get_height()
    x0, y0, x1, y1 = bbox
    pad = 0.5
    return p.get_textpage().get_text_bounded(
        left=x0 - pad, bottom=h - y1 - pad, right=x1 + pad, top=h - y0 + pad
    )


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@pytest.mark.parametrize(("doc_type", "seed"), CASES)
def test_clean_documents_pass_every_rule(doc_type: str, seed: int) -> None:
    gen = GENERATORS[doc_type](seed, "t")
    failures = [r for r in validate(gen.document) if r.status is RuleStatus.FAIL]
    assert failures == [], f"{gen.meta.template}: {failures}"


@pytest.mark.parametrize(("doc_type", "seed"), CASES)
def test_tampered_documents_fail_exactly_the_expected_rules(doc_type: str, seed: int) -> None:
    gen = GENERATORS[doc_type](seed, "t", tamper=True)
    failed = {r.rule for r in validate(gen.document) if r.status is RuleStatus.FAIL}
    assert failed == set(gen.meta.expected_failures)
    assert gen.meta.tampering is not None


@pytest.mark.parametrize(("doc_type", "seed"), CASES)
def test_tampering_changes_only_one_value(doc_type: str, seed: int) -> None:
    clean, tampered = GENERATORS[doc_type](seed, "t"), GENERATORS[doc_type](seed, "t", tamper=True)
    assert clean.document.fields == tampered.document.fields
    rows_attr = "transactions" if doc_type == "bank_statement" else "line_items"
    a, b = getattr(clean.document, rows_attr), getattr(tampered.document, rows_attr)
    assert [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y] == [
        tampered.meta.tampering.row
    ]


@pytest.mark.parametrize(("doc_type", "seed"), CASES)
def test_truth_bboxes_contain_the_printed_text(doc_type: str, seed: int) -> None:
    gen = GENERATORS[doc_type](seed, "t")
    pdf = pdfium.PdfDocument(gen.pdf)
    fields = gen.document.fields
    for name, printed in gen.meta.printed.items():
        src = getattr(fields, name).source
        assert _norm(_text_in_box(pdf, src.page, src.bbox)) == _norm(printed), name
    rows = getattr(gen.document, "transactions", None) or gen.document.line_items
    for row in rows:
        text = _norm(_text_in_box(pdf, row.source.page, row.source.bbox))
        assert row.description in text
    pdf.close()


@pytest.mark.parametrize("doc_type", sorted(GENERATORS))
def test_generation_is_deterministic(doc_type: str) -> None:
    a, b = GENERATORS[doc_type](7, "t"), GENERATORS[doc_type](7, "t")
    assert a.pdf == b.pdf
    assert a.truth_json() == b.truth_json()


@pytest.mark.parametrize("doc_type", sorted(GENERATORS))
def test_truth_json_roundtrips_through_the_schema(doc_type: str) -> None:
    gen = GENERATORS[doc_type](3, "t")
    doc = gen.truth_json()["document"]
    assert REGISTRY[doc["doc_type"]].model_validate(doc) == gen.document


def test_no_raw_identifiers_in_truth() -> None:
    for seed in SEEDS:
        gen: Generated = GENERATORS["bank_statement"](seed, "t")
        stored = str(gen.truth_json()["document"])
        assert gen.meta.printed["account_number_masked"] not in stored


@pytest.mark.parametrize("angle", [-3.0, -1.2, 1.7, 3.0])
def test_rotate_bbox_matches_pil_pixels(angle: float) -> None:
    img = Image.new("L", (400, 300), 255)
    box = (250, 40, 330, 70)
    ImageDraw.Draw(img).rectangle(box, fill=0)
    rotated = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
    actual = Image.eval(rotated, lambda p: 255 if p < 128 else 0).getbbox()
    expected = rotate_bbox(box, 200, 150, angle)
    assert actual is not None
    assert all(abs(a - e) <= 2 for a, e in zip(actual, expected, strict=True)), (actual, expected)


def test_noisy_variant_is_image_only_with_same_page_size() -> None:
    clean = GENERATORS["invoice"](5, "t")
    noisy = make_noisy(clean, 5)
    a, b = pdfium.PdfDocument(clean.pdf), pdfium.PdfDocument(noisy.pdf)
    assert len(a) == len(b)
    assert abs(a[0].get_width() - b[0].get_width()) < 1
    assert b[0].get_textpage().get_text_range().strip() == ""  # OCR must do the work
    assert (
        noisy.meta.variant == "noisy"
        and noisy.document.fields.total.value == clean.document.fields.total.value
    )
    assert noisy.document.fields.total.source != clean.document.fields.total.source  # bbox moved
    a.close()
    b.close()
