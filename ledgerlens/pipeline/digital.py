"""Words and boxes straight from a PDF's text layer (born-digital pages)."""

from __future__ import annotations

import io

import pdfplumber

from ledgerlens.pipeline.spans import Span


def page_words(pdf_bytes: bytes) -> list[list[Span]]:
    """One list of word spans per page. pdfplumber already uses points with a top-left
    origin (`top`/`bottom`), the same space as our `Source`."""
    pages: list[list[Span]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            pages.append(
                [
                    Span(
                        text=w["text"],
                        page=number,
                        bbox=(
                            round(float(w["x0"]), 2),
                            round(float(w["top"]), 2),
                            round(float(w["x1"]), 2),
                            round(float(w["bottom"]), 2),
                        ),
                        origin="pdf",
                    )
                    for w in words
                    if w["text"].strip()
                ]
            )
    return pages
