"""'Scanned' variants: render -> rotate 1-3 deg -> speckle/blur -> JPEG -> image-only PDF.

The truth bboxes are transformed through the same rotation, so they stay exact. The
output page keeps the original size in points, so coordinates stay in the same space.
"""

from __future__ import annotations

import io
import math
import random
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageFilter

from synth.common import Generated

DPI = 200


def rotate_point(x: float, y: float, cx: float, cy: float, degrees: float) -> tuple[float, float]:
    """Where (x, y) lands (top-left origin, y down) after PIL's `Image.rotate(degrees)`,
    which turns the image counter-clockwise about its centre."""
    t = math.radians(degrees)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(t) + dy * math.sin(t), cy - dx * math.sin(t) + dy * math.cos(t)


def rotate_bbox(
    bbox: tuple[float, float, float, float], cx: float, cy: float, degrees: float
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    pts = [rotate_point(x, y, cx, cy, degrees) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2))


def _transform_sources(
    obj: Any, angles: dict[int, float], sizes: dict[int, tuple[float, float]]
) -> Any:
    if isinstance(obj, dict):
        if set(obj) == {"page", "bbox"}:
            page = obj["page"]
            w, h = sizes[page]
            return {
                "page": page,
                "bbox": rotate_bbox(tuple(obj["bbox"]), w / 2, h / 2, angles[page]),
            }
        return {k: _transform_sources(v, angles, sizes) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_transform_sources(v, angles, sizes) for v in obj]
    return obj


def make_noisy(gen: Generated, seed: int) -> Generated:
    rng = random.Random(seed)
    pdf = pdfium.PdfDocument(gen.pdf)
    images: list[Image.Image] = []
    angles: dict[int, float] = {}
    sizes: dict[int, tuple[float, float]] = {}
    quality = rng.randint(30, 65)
    for i, page in enumerate(pdf, start=1):
        sizes[i] = (page.get_width(), page.get_height())
        img = page.render(scale=DPI / 72).to_pil().convert("L")
        angle = round(rng.uniform(1, 3) * rng.choice([-1, 1]), 2)
        angles[i] = angle
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
        speckle = Image.effect_noise(img.size, rng.uniform(8, 18))
        img = Image.blend(img, speckle, alpha=0.12)
        if rng.random() < 0.5:
            img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        images.append(Image.open(io.BytesIO(buf.getvalue())))
    pdf.close()

    out = io.BytesIO()
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=DPI)

    doc_dict = gen.document.model_dump(mode="json")
    doc = type(gen.document).model_validate(_transform_sources(doc_dict, angles, sizes))
    meta = gen.meta.model_copy(
        update={
            "id": gen.meta.id + "_noisy",
            "variant": "noisy",
            "noise": {"dpi": DPI, "jpeg_quality": quality, "rotation_deg": angles},
        }
    )
    return Generated(pdf=out.getvalue(), document=doc, meta=meta)
