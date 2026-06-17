"""Extraction-layer regression gate (offline: no DB, no embedding, no LLM).

Guards the P0/P1 ingestion work: IR blocks, docx/pptx tables (previously
dropped), heading hierarchy, and the embedded-image OCR path degrading
gracefully. Run from the skill root:

    python eval/extraction_cases.py

Exit code is non-zero on the first failed assertion so this can gate CI.
"""
from __future__ import annotations

import io
import os
import sys
import zipfile

# Make the skill packages (core/, providers/) and this eval dir importable
# whether run from the skill root or the eval dir.
_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_EVAL_DIR)
for _p in (_SKILL_ROOT, _EVAL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import ingestion  # noqa: E402
import gold_docs  # noqa: E402


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _png(w: int = 120, h: int = 120) -> bytes:
    from PIL import Image  # type: ignore

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _scanned_pdf_bytes() -> bytes:
    """An image-only ("scanned") PDF: a white page with high-contrast text and
    no text layer, so extraction must go through render + OCR."""
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    try:
        font = ImageFont.load_default(size=64)  # Pillow >= 10
    except TypeError:
        font = ImageFont.load_default()
    img = Image.new("RGB", (1000, 300), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((40, 90), "OCR TEST 400 8443", font=font, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _pdf_ocr_available() -> bool:
    try:
        import pypdfium2  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return ingestion.ocr.is_available()


def _pptx_with_table_and_image() -> bytes:
    slide = f"""<?xml version="1.0"?>
<p:sld xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}">
 <p:cSld><p:spTree>
  <p:sp><p:txBody><a:p><a:r><a:t>系统架构</a:t></a:r></a:p></p:txBody></p:sp>
  <a:tbl><a:tr>
    <a:tc><a:txBody><a:p><a:r><a:t>组件</a:t></a:r></a:p></a:txBody></a:tc>
    <a:tc><a:txBody><a:p><a:r><a:t>状态</a:t></a:r></a:p></a:txBody></a:tc>
   </a:tr><a:tr>
    <a:tc><a:txBody><a:p><a:r><a:t>消息队列</a:t></a:r></a:p></a:txBody></a:tc>
    <a:tc><a:txBody><a:p><a:r><a:t>运行中</a:t></a:r></a:p></a:txBody></a:tc>
   </a:tr></a:tbl>
  <p:pic><p:blipFill><a:blip r:embed="rId1"/></p:blipFill></p:pic>
 </p:spTree></p:cSld>
</p:sld>"""
    rels = f"""<?xml version="1.0"?>
<Relationships xmlns="{_PKG}">
 <Relationship Id="rId1" Type="{_R}/image" Target="../media/image1.png"/>
</Relationships>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        zf.writestr("ppt/media/image1.png", _png())
    return buf.getvalue()


def _docx_image_no_rels() -> bytes:
    """A .docx that references an embedded image but ships no rels/media part —
    the image must be skipped gracefully while the text survives."""
    doc = f"""<?xml version="1.0"?>
<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:a="{_A}">
 <w:body>
  <w:p><w:r><w:t>没有关系文件的图片段落。</w:t></w:r></w:p>
  <w:p><w:r><w:drawing><a:blip r:embed="rId999"/></w:drawing></w:r></w:p>
 </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc)  # no _rels, no media
    return buf.getvalue()


def _empty_pptx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")  # no slide parts
    return buf.getvalue()


def _check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"[{name}] FAILED {detail}")
    print(f"  ok  {name}")


def _check_raises(name: str, fn) -> None:
    try:
        fn()
    except ingestion.IngestionError:
        print(f"  ok  {name}")
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"[{name}] raised {type(exc).__name__}, expected IngestionError"
        ) from exc
    else:
        raise AssertionError(f"[{name}] did not raise")


def run() -> None:
    print(f"OCR engine: {ingestion.ocr.engine_name()}")

    # --- docx: heading + paragraph + table (table previously dropped) ---
    print("docx (heading/paragraph/table):")
    d = ingestion.extract("metrics_report.docx", gold_docs.metrics_report_docx())
    types = [b.type for b in d.blocks]
    _check("docx.has_heading", "heading" in types, types)
    _check("docx.has_table", "table" in types, types)
    _check("docx.heading_rendered", "# 季度运维指标报告" in d.content)
    _check("docx.subheading_rendered", "## 核心指标" in d.content)
    _check("docx.table_markdown", "| 指标 | 数值 |" in d.content, d.content)
    _check("docx.table_cell_value", "2299" in d.content and "3.7 小时" in d.content)
    _check("docx.paragraph_kept", "告警总量同比下降" in d.content)

    # --- pptx: text + table + embedded image (OCR path must not crash) ---
    print("pptx (text/table/image):")
    p = ingestion.extract("deck.pptx", _pptx_with_table_and_image())
    ptypes = [b.type for b in p.blocks]
    _check("pptx.has_table", "table" in ptypes, ptypes)
    _check("pptx.slide_heading", "幻灯片 1" in p.content)
    _check("pptx.text_kept", "系统架构" in p.content)
    _check("pptx.table_markdown", "| 组件 | 状态 |" in p.content, p.content)
    _check("pptx.table_cell", "消息队列" in p.content and "运行中" in p.content)
    _check("pptx.warnings_is_list", isinstance(p.warnings, list))

    # --- scanned PDF: render + OCR (P2) — exercised only when deps present ---
    print("scanned PDF (render + OCR):")
    pdf = ingestion.extract("scan.pdf", _scanned_pdf_bytes())
    _check("pdf.no_crash", isinstance(pdf.content, str))
    _check("pdf.warnings_is_list", isinstance(pdf.warnings, list))
    if _pdf_ocr_available():
        _check("pdf.scanned_ocr_text", "400" in pdf.content,
               f"OCR content={pdf.content!r}")
    else:
        print("  skip pdf.scanned_ocr_text (pypdfium2/OCR engine not installed)")

    # --- markdown: IR fallback still yields blocks ---
    print("markdown (IR fallback):")
    m = ingestion.extract("runbook.md", gold_docs.GATEWAY_RUNBOOK_MD.encode("utf-8"))
    _check("md.blocks_present", len(m.blocks) > 0)
    _check("md.has_heading_block", any(b.type == "heading" for b in m.blocks))
    _check("md.content_intact", "数据库连接池耗尽" in m.content)

    # --- graceful degradation (must never crash a whole ingest) ---
    print("degradation:")
    # corrupt docx (not a zip) -> clear IngestionError, not a raw traceback
    _check_raises(
        "degrade.corrupt_docx",
        lambda: ingestion.extract("bad.docx", b"this is definitely not a zip"),
    )
    # empty pptx (no slide parts) -> clear IngestionError
    _check_raises(
        "degrade.empty_pptx",
        lambda: ingestion.extract("empty.pptx", _empty_pptx()),
    )
    # docx referencing an image with no rels/media -> image skipped, text kept
    nr = ingestion.extract("norels.docx", _docx_image_no_rels())
    _check("degrade.norels_text_kept", "没有关系文件的图片段落" in nr.content)
    _check("degrade.norels_no_image_block",
           not any(b.type == "image" for b in nr.blocks))
    # oversized image -> downscaled, OCR returns without raising
    big = _png(5200, 320)  # long side > MAX_IMAGE_SIDE_PX
    res = ingestion.ocr.ocr_image_bytes(big, min_side_px=0)
    _check("degrade.oversized_image_no_crash", hasattr(res, "skipped_reason"))

    print("\nEXTRACTION REGRESSION: ALL PASSED")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"\nFAILED: {exc}")
        sys.exit(1)
