"""Text spans with positions: the evidence every extracted value is grounded against.

Same coordinate space as `Source`: PDF points, top-left origin, 1-based pages. Spans from
the PDF text layer and from OCR are interchangeable downstream.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ledgerlens.schemas.base import Source

Origin = Literal["pdf", "ocr"]
PageKind = Literal["digital", "scanned"]


class Span(BaseModel):
    """A word (PDF text layer) or text fragment (OCR)."""

    model_config = ConfigDict(frozen=True)

    text: str
    page: int
    bbox: tuple[float, float, float, float]
    origin: Origin
    confidence: float = 1.0

    @property
    def source(self) -> Source:
        return Source(page=self.page, bbox=self.bbox)

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


class Line(BaseModel):
    """Spans sharing a baseline, left to right.

    `xs` holds each span's horizontal extent in *deskewed* page space, used for column
    layout; the spans' own bboxes stay in real page space (what grounding needs).
    """

    model_config = ConfigDict(frozen=True)

    page: int
    spans: tuple[Span, ...]
    xs: tuple[tuple[float, float], ...]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.spans)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(s.bbox[0] for s in self.spans),
            min(s.bbox[1] for s in self.spans),
            max(s.bbox[2] for s in self.spans),
            max(s.bbox[3] for s in self.spans),
        )

    def cells(self, gap: float = 12.0) -> list[tuple[str, float, float]]:
        """Split into cells wherever the (deskewed) horizontal gap exceeds `gap` points."""
        out: list[tuple[str, float, float]] = []
        for span, (x0, x1) in zip(self.spans, self.xs, strict=True):
            if out and x0 - out[-1][2] <= gap:
                text, c0, _ = out[-1]
                out[-1] = (f"{text} {span.text}", c0, x1)
            else:
                out.append((span.text, x0, x1))
        return out


class Page(BaseModel):
    number: int
    width: float
    height: float
    kind: PageKind
    skew_deg: float = 0.0
    spans: list[Span]
    lines: list[Line]


class ParsedDocument(BaseModel):
    sha256: str
    pages: list[Page]
    markdown: str
    markdown_engine: str

    @property
    def spans(self) -> list[Span]:
        return [s for p in self.pages for s in p.spans]


def deskew_point(x: float, y: float, cx: float, cy: float, skew_deg: float) -> tuple[float, float]:
    """Undo a skew of `skew_deg` (text sloping down to the right is positive, y-down)."""
    t = math.radians(skew_deg)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(t) + dy * math.sin(t), cy - dx * math.sin(t) + dy * math.cos(t)


def group_lines(
    spans: list[Span], page: int, *, skew_deg: float = 0.0, size: tuple[float, float] = (0, 0)
) -> list[Line]:
    """Cluster spans into lines by vertical position in deskewed space, then order each
    line left to right. A span joins a line when its centre lies within half a
    line-height of the line's running centre."""
    cx, cy = size[0] / 2, size[1] / 2

    def straight(s: Span) -> tuple[float, float, float]:
        x0, ymid = deskew_point(s.bbox[0], s.cy, cx, cy, skew_deg)
        x1, _ = deskew_point(s.bbox[2], s.cy, cx, cy, skew_deg)
        return x0, x1, ymid

    placed = [(s, *straight(s)) for s in spans]
    lines: list[list[tuple[Span, float, float, float]]] = []
    centres: list[float] = []
    for item in sorted(placed, key=lambda it: (it[3], it[1])):
        s, _, _, ymid = item
        tol = max(s.height * 0.5, 2.0)
        for i, c in enumerate(centres):
            if abs(ymid - c) <= tol:
                lines[i].append(item)
                centres[i] = sum(it[3] for it in lines[i]) / len(lines[i])
                break
        else:
            lines.append([item])
            centres.append(ymid)
    out = []
    for _, items in sorted(zip(centres, lines, strict=True), key=lambda cl: cl[0]):
        items.sort(key=lambda it: it[1])
        out.append(
            Line(
                page=page,
                spans=tuple(it[0] for it in items),
                xs=tuple((round(it[1], 2), round(it[2], 2)) for it in items),
            )
        )
    return out


_NUMERIC_CELL = re.compile(r"^[-(+]?[$£€]?\s?[\d][\d.,\s]*[)\-]?(\s?[$£€])?$")


def _is_numeric(text: str) -> bool:
    return bool(_NUMERIC_CELL.match(text.strip())) or bool(
        re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", text)
    )


def _assign(
    cells: list[tuple[str, float, float]], cols: list[tuple[float, float]]
) -> list[str] | None:
    """Put each cell under the header column it overlaps most (nearest centre if none).
    Returns None if two cells would land in one column or the order would break."""
    row = [""] * len(cols)
    last = -1
    for text, x0, x1 in cells:
        overlaps = [max(0.0, min(x1, c1) - max(x0, c0)) for c0, c1 in cols]
        best = max(range(len(cols)), key=lambda k: overlaps[k])
        if overlaps[best] == 0:
            mid = (x0 + x1) / 2
            best = min(range(len(cols)), key=lambda k: abs(mid - (cols[k][0] + cols[k][1]) / 2))
        if best <= last or row[best]:
            return None
        row[best], last = text, best
    return row


def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def lines_to_markdown(lines: list[Line]) -> str:
    """Layout-preserving Markdown.

    A line with 3+ cells and no numbers starts a table (its cells define the columns);
    following rows that contain numbers are placed under those columns, keeping empty
    cells, so a value's column (e.g. money in vs out) survives. Other lines are plain
    text with ' | ' between widely separated cells.
    """
    out: list[str] = []
    cols: list[tuple[float, float]] | None = None
    for line in lines:
        cells = line.cells()
        texts = [c[0] for c in cells]
        if len(cells) >= 3 and not any(_is_numeric(t) for t in texts):
            cols = [(c[1], c[2]) for c in cells]
            out += ["", _md_row(texts), _md_row(["---"] * len(cells))]
            continue
        if cols is not None and any(_is_numeric(t) for t in texts):
            row = _assign(cells, cols)
            if row is not None:
                out.append(_md_row(row))
                continue
        if cols is not None:
            out.append("")
            cols = None
        out.append(" | ".join(texts))
    return "\n".join(out).strip()
