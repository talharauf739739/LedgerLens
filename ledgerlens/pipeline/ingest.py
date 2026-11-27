"""Uploads in any supported format -> PDF bytes, so one pipeline handles everything.

PDFs pass through unchanged. Images (phone photos, scans) become image-only PDF pages:
no text layer, so `parse_pdf` OCRs them like any scanned page. Each page is scaled to A4
width (595 pt) whatever the image's resolution, which keeps OCR input sizes predictable.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

PDF_MAGIC = b"%PDF-"
IMAGE_FORMATS = {"JPEG", "PNG", "TIFF", "BMP", "WEBP", "MPO"}  # MPO: multi-frame JPEG (phones)
UPLOAD_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"]
PAGE_WIDTH_PT = 595.0  # A4
MAX_PIXELS = 60_000_000  # per page; larger images are refused (decompression-bomb guard)


class UnsupportedFile(ValueError):
    """The upload isn't a PDF or a supported image, or it's too large to process."""


def is_pdf(data: bytes) -> bool:
    # The spec allows bytes before the header; real files put it within the first 1 KB.
    return PDF_MAGIC in data[:1024]


def to_pdf(data: bytes, *, max_pages: int = 50) -> bytes:
    if is_pdf(data):
        return data
    try:
        image = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as exc:
        raise UnsupportedFile(
            "Not a PDF or a supported image (PDF, JPEG, PNG, TIFF, BMP, WebP)."
        ) from exc
    if image.format not in IMAGE_FORMATS:
        raise UnsupportedFile(f"Unsupported image format: {image.format}.")

    pages: list[Image.Image] = []
    for frame in ImageSequence.Iterator(image):
        if frame.width * frame.height > MAX_PIXELS:
            raise UnsupportedFile(
                f"Image is too large ({frame.width}x{frame.height} px); "
                f"the limit is {MAX_PIXELS // 1_000_000} megapixels per page."
            )
        pages.append(ImageOps.exif_transpose(frame).convert("RGB"))  # phones store rotation
        if len(pages) > max_pages:
            raise UnsupportedFile(f"Image has more than {max_pages} pages.")
        if image.format in {"JPEG", "MPO"}:
            break  # extra MPO frames are previews/depth maps, not pages
    if not pages:
        raise UnsupportedFile("The image has no pages.")

    out = io.BytesIO()
    dpi = pages[0].width * 72 / PAGE_WIDTH_PT
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=dpi)
    return out.getvalue()
