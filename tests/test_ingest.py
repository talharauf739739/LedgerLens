"""Uploads: images become OCR-able PDF pages; the whole pipeline then works on photos."""

import io
import json
from typing import Any

import pypdfium2 as pdfium
import pytest
from PIL import Image

from ledgerlens.pipeline import ingest
from ledgerlens.pipeline.ingest import PAGE_WIDTH_PT, UnsupportedFile, is_pdf, to_pdf
from ledgerlens.pipeline.parse import parse_pdf
from ledgerlens.pipeline.process import process_pdf
from ledgerlens.schemas import RuleStatus
from ledgerlens.schemas.base import FieldStatus
from synth import GENERATORS
from tests.helpers import perfect_draft


def _encode(img: Image.Image, fmt: str, **kw: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def _page_sizes(pdf: bytes) -> list[tuple[float, float]]:
    doc = pdfium.PdfDocument(pdf)
    try:
        return [(round(p.get_width(), 1), round(p.get_height(), 1)) for p in doc]
    finally:
        doc.close()


def _photo_of(pdf: bytes, dpi: int = 200, fmt: str = "PNG") -> bytes:
    """A 'scan' of page 1: render the PDF to an image, dropping its text layer."""
    doc = pdfium.PdfDocument(pdf)
    try:
        img = doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()
    return _encode(img, fmt, **({"quality": 90} if fmt == "JPEG" else {}))


def test_pdf_passes_through_unchanged() -> None:
    pdf = GENERATORS["invoice"](1, "t").pdf
    assert is_pdf(pdf) and to_pdf(pdf) is pdf


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "BMP", "WEBP", "TIFF"])
def test_image_becomes_one_a4_width_page(fmt: str) -> None:
    pdf = to_pdf(_encode(Image.new("RGB", (1240, 1754), "white"), fmt))
    assert is_pdf(pdf)
    [(width, height)] = _page_sizes(pdf)
    assert width == PAGE_WIDTH_PT and height == pytest.approx(PAGE_WIDTH_PT * 1754 / 1240, 0.01)


def test_multipage_tiff_keeps_every_page() -> None:
    frames = [Image.new("RGB", (600, 800), c) for c in ("white", "gray", "black")]
    data = _encode(frames[0], "TIFF", save_all=True, append_images=frames[1:])
    assert len(_page_sizes(to_pdf(data))) == 3


def test_phone_rotation_is_applied() -> None:
    img = Image.new("RGB", (800, 600), "white")  # stored landscape...
    exif = Image.Exif()
    exif[0x0112] = 6  # ...shown rotated 90 degrees: portrait
    [(width, height)] = _page_sizes(to_pdf(_encode(img, "JPEG", exif=exif)))
    assert height > width


def test_rejects_non_documents_and_huge_images(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsupportedFile, match="Not a PDF"):
        to_pdf(b"PK\x03\x04 this is a zip, not a document")
    monkeypatch.setattr(ingest, "MAX_PIXELS", 1000)
    with pytest.raises(UnsupportedFile, match="too large"):
        to_pdf(_encode(Image.new("RGB", (100, 100)), "PNG"))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_photo_is_read_with_ocr(fmt: str) -> None:
    gen = GENERATORS["bank_statement"](3, "t")
    parsed = parse_pdf(_photo_of(gen.pdf, fmt=fmt))
    assert [p.kind for p in parsed.pages] == ["scanned"]
    words = {s.text for s in parsed.spans}
    assert gen.meta.printed["closing_balance"] in words
    assert all(s.origin == "ocr" for s in parsed.spans)


async def test_photo_runs_the_full_pipeline_with_receipts() -> None:
    gen = GENERATORS["bank_statement"](3, "t")
    draft = perfect_draft(gen)

    class Oracle:
        model = "oracle"

        async def chat(self, messages: list[dict[str, Any]], **_: Any) -> str:
            return json.dumps(draft)

    # Every page "scanned" into one multi-page TIFF: rows on page 2 need their own receipts.
    doc_in = pdfium.PdfDocument(gen.pdf)
    try:
        pages = [p.render(scale=200 / 72).to_pil().convert("RGB") for p in doc_in]
    finally:
        doc_in.close()
    assert len(pages) > 1
    photo = _encode(
        pages[0], "TIFF", save_all=True, append_images=pages[1:], compression="tiff_lzw"
    )
    result = await process_pdf(photo, None, Oracle())
    assert [p.kind for p in result.parsed.pages] == ["scanned"] * len(pages)
    assert result.grounding.ungrounded == [] and result.grounding.rows_ungrounded == []
    doc = result.document
    assert doc.doc_type == "bank_statement" and result.classification.method == "cues"
    assert doc.fields.closing_balance.status is FieldStatus.GROUNDED
    assert all(r.status is not RuleStatus.FAIL for r in doc.validation)

    # The receipt lands where the value is printed, in the photo page's coordinates.
    scale = PAGE_WIDTH_PT / _page_sizes(gen.pdf)[0][0]
    truth = gen.document.fields.closing_balance.source.bbox
    got = doc.fields.closing_balance.source.bbox
    assert got[0] == pytest.approx(truth[0] * scale, abs=4)
    assert got[1] == pytest.approx(truth[1] * scale, abs=4)
