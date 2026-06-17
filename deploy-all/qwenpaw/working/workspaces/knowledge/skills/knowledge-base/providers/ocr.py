"""Unified OCR provider.

Prefers RapidOCR (offline ONNX, strong Chinese, CPU-friendly); falls back to
pytesseract. Every entry point degrades gracefully: when no engine is installed
`ocr_image_bytes` returns an empty result with a `skipped_reason` instead of
raising. This matters because embedded-image OCR runs inside document ingestion
and a single bad/undecodable image must never fail the whole document.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Images smaller than this on either side are treated as decorative
# (icons/logos/bullets) and skipped to keep OCR noise out of the index.
MIN_IMAGE_SIDE_PX = 64
# Images larger than this on the long side are downscaled before OCR — bounds
# memory/time on huge embedded images without hurting accuracy on normal text.
MAX_IMAGE_SIDE_PX = 4000

_engine = None  # cached RapidOCR instance (None for pytesseract / unavailable)
_engine_kind: str | None = None  # "rapidocr" | "pytesseract" | None
_init_done = False


@dataclass
class OcrResult:
    text: str = ""
    engine: str = ""  # backend that ran ("rapidocr" | "pytesseract")
    confidence: float | None = None
    skipped_reason: str = ""  # non-empty when no text was produced


def _init_engine() -> None:
    global _engine, _engine_kind, _init_done
    if _init_done:
        return
    _init_done = True
    # 1) RapidOCR — preferred (offline onnx, better Chinese than tesseract).
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _engine = RapidOCR()
        _engine_kind = "rapidocr"
        logger.info("OCR engine: RapidOCR")
        return
    except Exception as exc:  # noqa: BLE001 - any import/init failure -> fallback
        logger.info("RapidOCR unavailable (%s); trying pytesseract", exc)
    # 2) pytesseract — legacy fallback (requires a system tesseract binary).
    try:
        import pytesseract  # type: ignore  # noqa: F401
        from PIL import Image  # type: ignore  # noqa: F401

        _engine_kind = "pytesseract"
        logger.info("OCR engine: pytesseract")
        return
    except Exception as exc:  # noqa: BLE001
        logger.info("pytesseract unavailable (%s); OCR disabled", exc)
        _engine_kind = None


def is_available() -> bool:
    _init_engine()
    return _engine_kind is not None


def engine_name() -> str:
    _init_engine()
    return _engine_kind or "none"


def _load_image(data: bytes):
    from PIL import Image  # type: ignore

    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _downscale_for_ocr(img):
    """Downscale an oversized image so OCR memory/time stays bounded. Returns
    the original image when it's already within MAX_IMAGE_SIDE_PX."""
    width, height = img.size
    longest = max(width, height)
    if longest <= MAX_IMAGE_SIDE_PX:
        return img
    scale = MAX_IMAGE_SIDE_PX / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    try:
        from PIL import Image  # type: ignore

        return img.resize(new_size, Image.LANCZOS)
    except Exception:  # noqa: BLE001 - fall back to the original on any failure
        return img


def ocr_image_bytes(
    data: bytes, *, min_side_px: int = MIN_IMAGE_SIDE_PX
) -> OcrResult:
    """OCR raw image bytes. Never raises.

    Returns an `OcrResult`; when nothing is produced, `skipped_reason` explains
    why (no engine, too small, undecodable, no text). Pass `min_side_px=0` to
    disable the decorative-image size filter (e.g. for an explicit upload).
    """
    if not data:
        return OcrResult(skipped_reason="empty image data")
    _init_engine()
    if _engine_kind is None:
        return OcrResult(skipped_reason="no OCR engine installed")

    try:
        img = _load_image(data)
    except Exception as exc:  # noqa: BLE001
        return OcrResult(skipped_reason=f"cannot open image: {exc}")

    width, height = img.size
    if min_side_px and (width < min_side_px or height < min_side_px):
        return OcrResult(skipped_reason=f"image too small ({width}x{height})")

    img = _downscale_for_ocr(img)

    try:
        if _engine_kind == "rapidocr":
            return _ocr_rapidocr(img)
        return _ocr_pytesseract(img)
    except Exception as exc:  # noqa: BLE001 - OCR must not crash ingestion
        logger.warning("OCR failed: %s", exc)
        return OcrResult(engine=_engine_kind or "", skipped_reason=f"OCR error: {exc}")


def _ocr_rapidocr(img) -> OcrResult:
    import numpy as np  # type: ignore

    arr = np.array(img.convert("RGB"))
    result, _ = _engine(arr)  # type: ignore[misc]
    if not result:
        return OcrResult(engine="rapidocr", skipped_reason="no text detected")
    lines = [row[1] for row in result if len(row) > 1 and row[1]]
    confs = [
        float(row[2])
        for row in result
        if len(row) > 2 and isinstance(row[2], (int, float))
    ]
    text = "\n".join(lines).strip()
    if not text:
        return OcrResult(engine="rapidocr", skipped_reason="no text detected")
    conf = sum(confs) / len(confs) if confs else None
    return OcrResult(text=text, engine="rapidocr", confidence=conf)


def _ocr_pytesseract(img) -> OcrResult:
    import pytesseract  # type: ignore

    text = pytesseract.image_to_string(img, lang="chi_sim+eng").strip()
    if not text:
        return OcrResult(engine="pytesseract", skipped_reason="no text detected")
    return OcrResult(text=text, engine="pytesseract")
