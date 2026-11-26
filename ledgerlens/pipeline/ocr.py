"""OCR for scanned pages with RapidOCR (Apache-2.0, ONNX Runtime, small bundled models).

Returns word spans in PDF points (top-left origin), the same space as the text layer,
so grounding doesn't care which path produced the evidence.
"""

from __future__ import annotations

import logging
import math
import statistics
from functools import lru_cache
from typing import Any

from PIL import Image

from ledgerlens.pipeline.spans import Span

log = logging.getLogger(__name__)

OCR_DPI = 200
MIN_SCORE = 0.5  # below this, a recognised word is treated as noise


@lru_cache(maxsize=1)
def _engine() -> Any:
    # Imported lazily: loading the ONNX models takes a few seconds and ~200 MB of RAM,
    # which born-digital documents never need.
    from rapidocr import RapidOCR

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return RapidOCR()


def _poly_to_bbox(poly: Any, scale: float) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return (
        round(min(xs) / scale, 2),
        round(min(ys) / scale, 2),
        round(max(xs) / scale, 2),
        round(max(ys) / scale, 2),
    )


def estimate_skew(line_polys: Any, min_width_px: float = 80) -> float:
    """Page skew in degrees from OCR line boxes: median slope of their top edges
    (positive = text slopes down to the right, y-down). 0 when there's too little text."""
    angles = []
    for poly in line_polys:
        (x0, y0), (x1, y1) = poly[0], poly[1]
        if x1 - x0 >= min_width_px:
            angles.append(math.degrees(math.atan2(float(y1 - y0), float(x1 - x0))))
    return round(statistics.median(angles), 3) if len(angles) >= 3 else 0.0


def ocr_page(image: Image.Image, page: int, dpi: int = OCR_DPI) -> tuple[list[Span], float]:
    """Word-level spans for one rendered page image, plus its estimated skew (degrees)."""
    scale = dpi / 72
    out = _engine()(image, return_word_box=True)
    spans: list[Span] = []
    if not out.txts:
        return spans, 0.0
    word_results = out.word_results or ()
    for i, (line_poly, line_text, line_score) in enumerate(
        zip(out.boxes, out.txts, out.scores, strict=True)
    ):
        words = word_results[i] if i < len(word_results) else ()
        if words:
            for text, score, poly in words:
                if text.strip() and poly is not None and score >= MIN_SCORE:
                    spans.append(
                        Span(
                            text=text.strip(),
                            page=page,
                            bbox=_poly_to_bbox(poly, scale),
                            origin="ocr",
                            confidence=round(float(score), 4),
                        )
                    )
        elif line_text.strip() and line_score >= MIN_SCORE:
            # No word boxes for this line: keep the whole line as one span.
            spans.append(
                Span(
                    text=line_text.strip(),
                    page=page,
                    bbox=_poly_to_bbox(line_poly, scale),
                    origin="ocr",
                    confidence=round(float(line_score), 4),
                )
            )
    return spans, estimate_skew(out.boxes)
