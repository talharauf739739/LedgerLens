"""PDF or image -> pages of positioned spans -> lines -> Markdown.

Per page: use the PDF text layer when it has real text (born-digital), else render the
page and OCR it. Both paths produce the same `Span`s, so everything downstream (the
extractor's Markdown, grounding) is identical for digital and scanned documents.
"""

from __future__ import annotations

import hashlib
import logging

import pypdfium2 as pdfium

from ledgerlens.pipeline.digital import page_words
from ledgerlens.pipeline.ingest import to_pdf
from ledgerlens.pipeline.ocr import OCR_DPI, ocr_page
from ledgerlens.pipeline.spans import Page, PageKind, ParsedDocument, group_lines, lines_to_markdown

log = logging.getLogger(__name__)

# A page with fewer printable characters than this in its text layer is treated as scanned.
MIN_TEXT_CHARS = 20


def _page_kinds(pdf: pdfium.PdfDocument) -> list[tuple[PageKind, float, float]]:
    kinds: list[tuple[PageKind, float, float]] = []
    for page in pdf:
        text = page.get_textpage().get_text_range()
        printable = sum(1 for ch in text if not ch.isspace())
        kind: PageKind = "digital" if printable >= MIN_TEXT_CHARS else "scanned"
        kinds.append((kind, page.get_width(), page.get_height()))
    return kinds


def parse_pdf(data: bytes, *, max_pages: int = 50) -> ParsedDocument:
    """Accepts a PDF or an image (images are OCRed). `sha256` is of the bytes given."""
    original = data
    data = to_pdf(data, max_pages=max_pages)
    pdf = pdfium.PdfDocument(data)
    try:
        if len(pdf) > max_pages:
            raise ValueError(f"document has {len(pdf)} pages; the limit is {max_pages}")
        kinds = _page_kinds(pdf)
        digital_words = page_words(data) if any(k == "digital" for k, _, _ in kinds) else []
        pages: list[Page] = []
        for i, (kind, width, height) in enumerate(kinds):
            number = i + 1
            skew = 0.0
            if kind == "digital":
                spans = digital_words[i]
            else:
                image = pdf[i].render(scale=OCR_DPI / 72).to_pil()
                spans, skew = ocr_page(image, number)
            pages.append(
                Page(
                    number=number,
                    width=round(width, 2),
                    height=round(height, 2),
                    kind=kind,
                    skew_deg=skew,
                    spans=spans,
                    lines=group_lines(spans, number, skew_deg=skew, size=(width, height)),
                )
            )
    finally:
        pdf.close()

    markdown = "\n\n".join(f"<!-- page {p.number} -->\n{lines_to_markdown(p.lines)}" for p in pages)
    return ParsedDocument(
        sha256=hashlib.sha256(original).hexdigest(),
        pages=pages,
        markdown=markdown,
        markdown_engine="lines",
    )
