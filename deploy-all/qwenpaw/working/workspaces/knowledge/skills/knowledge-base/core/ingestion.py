"""End-to-end document ingestion: extract → chunk → tokenize → embed → persist.

Synchronous core. The HTTP layer wraps these calls in a thread pool and updates
the `ingestion_job` table via the `progress_callback` hook.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import message_from_bytes
from email.policy import default as email_policy
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

import jieba
import sqlite_vec  # type: ignore

from core import db
from core.chunking import ParentPiece, chunk_document
from providers import embedding
from retrieval.recall_dense import normalize as _normalize_vec


logger = logging.getLogger(__name__)


_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_W = f"{{{_DOCX_NS}}}"
_PPTX_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PPTX_A = f"{{{_PPTX_A_NS}}}"
_PPTX_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


class IngestionError(Exception):
    """Wraps any ingestion failure; HTTP layer maps to 4xx/5xx as appropriate."""


@dataclass
class ExtractedDocument:
    content: str
    source_format: str  # "markdown" | "plain" | "pdf" | "docx" | "image" | "email"
    pages: list[tuple[int, str]] | None = None  # populated for PDFs only
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestionResult:
    document_id: int
    parent_count: int
    child_count: int
    embedded: bool


ProgressCallback = Callable[[str, float], None]


def _emit_progress(cb: ProgressCallback | None, stage: str, pct: float) -> None:
    if cb is None:
        return
    try:
        cb(stage, pct)
    except Exception:
        logger.exception("progress callback raised")


# ---------- Public entry points ----------

def ingest_file(
    filename: str,
    content_bytes: bytes,
    *,
    source_type: str = "file_upload",
    source_scope: str = "tenant_private",
    storage_path: str | None = None,
    meta: dict | None = None,
    progress_callback: ProgressCallback | None = None,
) -> IngestionResult:
    """Extract the file, chunk, embed, and persist. Returns the new document id."""
    _emit_progress(progress_callback, "extracting", 0.05)
    extracted = extract(filename, content_bytes)
    if not extracted.content.strip():
        raise IngestionError(f"no extractable text in {filename}")
    return _persist_extracted(
        filename=filename,
        extracted=extracted,
        source_type=source_type,
        source_scope=source_scope,
        storage_path=storage_path,
        meta=meta,
        progress_callback=progress_callback,
    )


def ingest_manual(
    title: str,
    content: str,
    *,
    source_scope: str = "tenant_private",
    meta: dict | None = None,
    progress_callback: ProgressCallback | None = None,
) -> IngestionResult:
    """Persist a manually-typed knowledge entry (no file, no extractor)."""
    if not content or not content.strip():
        raise IngestionError("manual entry content is empty")
    extracted = ExtractedDocument(content=content.strip(), source_format="markdown")
    return _persist_extracted(
        filename=title or "manual_entry",
        extracted=extracted,
        source_type="manual_entry",
        source_scope=source_scope,
        storage_path=None,
        meta=meta,
        progress_callback=progress_callback,
    )


# ---------- Extraction ----------

def extract(filename: str, content_bytes: bytes) -> ExtractedDocument:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("md", "markdown"):
        return _extract_text(content_bytes, source_format="markdown")
    if ext == "txt":
        return _extract_text(content_bytes, source_format="plain")
    if ext == "pdf":
        return _extract_pdf(content_bytes, filename)
    if ext == "docx":
        return _extract_docx(content_bytes, filename)
    if ext == "pptx":
        return _extract_pptx(content_bytes, filename)
    if ext in ("png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"):
        return _extract_image(content_bytes)
    if ext == "eml":
        return _extract_email(content_bytes)
    return _extract_text(content_bytes, source_format="plain")


def _extract_text(data: bytes, *, source_format: str) -> ExtractedDocument:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            text = data.decode(encoding)
            return ExtractedDocument(content=text, source_format=source_format)
        except UnicodeDecodeError:
            continue
    raise IngestionError("could not decode text content with any common encoding")


def _extract_pdf(data: bytes, filename: str) -> ExtractedDocument:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise IngestionError("pypdf is not installed; cannot extract PDF") from exc

    import io
    reader = PdfReader(io.BytesIO(data))
    pages: list[tuple[int, str]] = []
    parts: list[str] = []
    for idx, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("pdf page %d extract failed: %s", idx + 1, exc)
            page_text = ""
        page_text = page_text.strip()
        if page_text:
            pages.append((idx + 1, page_text))
            parts.append(page_text)

    return ExtractedDocument(
        content="\n\n".join(parts),
        source_format="pdf",
        pages=pages,
    )


def _extract_docx(data: bytes, filename: str) -> ExtractedDocument:
    """Extract text from .docx by reading word/document.xml directly. Avoids
    depending on python-docx (works even if pip install missed it)."""
    import io
    paragraphs: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with zf.open("word/document.xml") as fh:
                xml_bytes = fh.read()
    except (zipfile.BadZipFile, KeyError) as exc:
        raise IngestionError(f"invalid docx file: {exc}") from exc

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_DOCX_W}body")
    if body is None:
        return ExtractedDocument(content="", source_format="docx")

    for para in body.iter(f"{_DOCX_W}p"):
        texts = [t.text or "" for t in para.iter(f"{_DOCX_W}t")]
        line = "".join(texts).strip()
        if line:
            style = _docx_paragraph_style(para)
            level = _docx_heading_level_from_style(style)
            if level is not None:
                paragraphs.append(f"{'#' * level} {line}")
            else:
                paragraphs.append(line)

    return ExtractedDocument(
        content="\n\n".join(paragraphs),
        source_format="markdown",
    )


def _extract_pptx(data: bytes, filename: str) -> ExtractedDocument:
    """Extract text from .pptx slides by reading slide XML directly.

    PowerPoint files are ZIP packages. Treating them as plain text yields the
    PK header and package XML names, so this extractor only reads slide parts.
    """
    import io

    slides: list[tuple[int, str]] = []
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            slide_names = sorted(
                (
                    (int(match.group(1)), name)
                    for name in zf.namelist()
                    if (match := _PPTX_SLIDE_RE.match(name))
                ),
                key=lambda item: item[0],
            )
            if not slide_names:
                raise IngestionError("invalid pptx file: no slide XML parts found")

            for slide_no, name in slide_names:
                try:
                    paragraphs = _pptx_paragraphs_from_xml(zf.read(name))
                except ET.ParseError as exc:
                    warnings.append(f"slide {slide_no} XML parse failed: {exc}")
                    continue
                if paragraphs:
                    slides.append((slide_no, "\n".join(paragraphs)))
    except zipfile.BadZipFile as exc:
        raise IngestionError(f"invalid pptx file: {exc}") from exc

    parts: list[str] = []
    for slide_no, text in slides:
        parts.append(f"# 幻灯片 {slide_no}\n\n{text}")

    return ExtractedDocument(
        content="\n\n".join(parts),
        source_format="markdown",
        warnings=warnings,
    )


def _pptx_paragraphs_from_xml(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for para in root.iter(f"{_PPTX_A}p"):
        texts = [t.text or "" for t in para.iter(f"{_PPTX_A}t")]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return paragraphs


def _docx_paragraph_style(para: ET.Element) -> str:
    pPr = para.find(f"{_DOCX_W}pPr")
    if pPr is None:
        return ""
    pStyle = pPr.find(f"{_DOCX_W}pStyle")
    if pStyle is None:
        return ""
    return pStyle.get(f"{_DOCX_W}val") or ""


def _docx_heading_level_from_style(style: str) -> int | None:
    if not style:
        return None
    m = re.match(r"(?:Heading|标题)\s*(\d+)", style)
    if m:
        try:
            return max(1, min(6, int(m.group(1))))
        except ValueError:
            return None
    return None


def _extract_image(data: bytes) -> ExtractedDocument:
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise IngestionError(
            "PIL/pytesseract not installed; cannot OCR images"
        ) from exc

    import io
    try:
        img = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception as exc:
        raise IngestionError(f"OCR failed: {exc}") from exc

    return ExtractedDocument(content=text.strip(), source_format="plain")


def _extract_email(data: bytes) -> ExtractedDocument:
    try:
        msg = message_from_bytes(data, policy=email_policy)
    except Exception as exc:
        raise IngestionError(f"could not parse email: {exc}") from exc

    parts: list[str] = []
    subject = msg.get("Subject", "")
    if subject:
        parts.append(f"# {subject}")
    sender = msg.get("From", "")
    if sender:
        parts.append(f"From: {sender}")

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    parts.append(part.get_content())
                except Exception:
                    pass
    else:
        try:
            parts.append(msg.get_content() or "")
        except Exception:
            pass

    return ExtractedDocument(
        content="\n\n".join(p for p in parts if p),
        source_format="markdown",
    )


# ---------- Chunking + persistence ----------

def _build_parents(extracted: ExtractedDocument) -> list[ParentPiece]:
    """Run the chunker. PDFs get per-page locators; other formats get an empty
    locator (the section_path carries enough citation info)."""
    if extracted.pages:
        all_parents: list[ParentPiece] = []
        for page_no, page_text in extracted.pages:
            page_parents = chunk_document(
                page_text,
                source_format="plain",
                locator_prefix=f"第 {page_no} 页",
            )
            for p in page_parents:
                p.chunk_index = len(all_parents)
                all_parents.append(p)
        return all_parents

    return chunk_document(
        extracted.content,
        source_format=extracted.source_format if extracted.source_format in ("markdown", "plain") else "plain",
    )


def _jieba_tokenize(text: str) -> str:
    """Pre-tokenize Chinese text for FTS5 BM25. cut_for_search yields overlapping
    fine-grained tokens — better recall than coarse cut for short queries."""
    if not text:
        return ""
    return " ".join(t for t in jieba.cut_for_search(text) if t.strip())


def _persist_extracted(
    *,
    filename: str,
    extracted: ExtractedDocument,
    source_type: str,
    source_scope: str,
    storage_path: str | None,
    meta: dict | None,
    progress_callback: ProgressCallback | None,
) -> IngestionResult:
    _emit_progress(progress_callback, "chunking", 0.20)
    parents = _build_parents(extracted)
    if not parents:
        raise IngestionError("chunking produced zero pieces")

    # Flatten in iteration order so embedding/persist phases can use a single
    # running index instead of nested lookups. The BM25-indexed text prepends
    # the section_path so heading words ("数据库故障") are searchable even when
    # they appear only in the heading hierarchy, not in the chunk body.
    tokenized_in_order: list[str] = []
    child_texts_for_embed: list[str] = []
    for p in parents:
        for c in p.children:
            search_text = f"{p.section_path} {c.content}" if p.section_path else c.content
            tokenized_in_order.append(_jieba_tokenize(search_text))
            child_texts_for_embed.append(c.content)

    if not child_texts_for_embed:
        raise IngestionError("chunking produced parents but zero children")

    # Embed (batched). Failure aborts the ingest — caller can retry.
    embedded = False
    vectors: list[list[float]] = []
    if embedding.is_available():
        _emit_progress(progress_callback, "embedding", 0.45)
        try:
            vectors = embedding.embed_batched(
                child_texts_for_embed, batch_id=f"ingest:{filename}"
            )
            embedded = True
        except embedding.EmbeddingError as exc:
            logger.warning(
                "embedding failed for %s, continuing BM25-only: %s", filename, exc
            )
            vectors = []
    else:
        logger.info("DASHSCOPE_API_KEY not set; ingesting %s without embeddings", filename)

    if vectors and len(vectors) != len(child_texts_for_embed):
        raise IngestionError(
            f"embedding count mismatch: expected {len(child_texts_for_embed)} got {len(vectors)}"
        )

    # Single transaction: document → parents → children → vectors. We use
    # AUTOINCREMENT integer ids — lastrowid hands them back without a round-trip.
    _emit_progress(progress_callback, "indexing", 0.80)
    now = _now_iso()
    meta_json = json.dumps(meta or {}, ensure_ascii=False)

    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO document
               (filename, source_type, source_scope, storage_path,
                extracted_text_length, uploaded_at, meta_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                filename, source_type, source_scope, storage_path,
                len(extracted.content), now, meta_json,
            ),
        )
        doc_id = cur.lastrowid

        child_id_for_vec: list[tuple[int, list[float]]] = []
        flat_idx = 0

        for p in parents:
            cur = conn.execute(
                """INSERT INTO parent_chunk
                   (document_id, chunk_index, section_path, locator,
                    content, token_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id, p.chunk_index, p.section_path or None,
                    p.locator or None, p.content, p.token_count, now,
                ),
            )
            parent_id = cur.lastrowid
            for c in p.children:
                cur = conn.execute(
                    """INSERT INTO child_chunk
                       (parent_id, document_id, chunk_index, content,
                        content_tokenized, token_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        parent_id, doc_id, c.chunk_index, c.content,
                        tokenized_in_order[flat_idx], c.token_count, now,
                    ),
                )
                child_id = cur.lastrowid
                if vectors:
                    child_id_for_vec.append((child_id, vectors[flat_idx]))
                flat_idx += 1

        # Bulk insert vectors. sqlite-vec serializes Python lists to its binary
        # format via serialize_float32. Vectors are L2-normalized at write time
        # so dense recall's cosine-from-L2 conversion (sim = 1 - L2²/2) is
        # well-defined; the reindex path matches.
        if child_id_for_vec:
            conn.executemany(
                "INSERT INTO child_vec(chunk_id, embedding) VALUES (?, ?)",
                [
                    (cid, sqlite_vec.serialize_float32(_normalize_vec(vec)))
                    for cid, vec in child_id_for_vec
                ],
            )

    _emit_progress(progress_callback, "success", 1.0)
    return IngestionResult(
        document_id=doc_id,
        parent_count=len(parents),
        child_count=len(child_texts_for_embed),
        embedded=embedded,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
