"""End-to-end document ingestion: extract → chunk → tokenize → embed → persist.

Synchronous core. The HTTP layer wraps these calls in a thread pool and updates
the `ingestion_job` table via the `progress_callback` hook.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
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
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OLE_FREE_SECT = 0xFFFFFFFF
_OLE_END_OF_CHAIN = 0xFFFFFFFE


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
    if ext == "doc":
        return _extract_doc(content_bytes, filename)
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


class _OleCompoundFile:
    """Minimal CFBF reader for legacy Word .doc streams."""

    def __init__(self, data: bytes):
        if not data.startswith(_OLE_MAGIC):
            raise IngestionError("invalid legacy doc file: missing OLE header")
        self.data = data
        self.sector_size = 1 << int.from_bytes(data[30:32], "little")
        self.mini_sector_size = 1 << int.from_bytes(data[32:34], "little")
        self.first_dir_sector = self._u32(48)
        self.mini_cutoff = self._u32(56)
        self.first_mini_fat_sector = self._u32(60)
        self.num_mini_fat_sectors = self._u32(64)
        self.first_difat_sector = self._u32(68)
        self.num_difat_sectors = self._u32(72)
        self.fat: list[int] = []
        self.mini_fat: list[int] = []
        self.streams: dict[str, tuple[int, int]] = {}
        self._mini_stream = b""
        self._load_fat()
        self._load_directory()
        self._load_mini_fat()

    def _u32(self, offset: int) -> int:
        return int.from_bytes(self.data[offset:offset + 4], "little")

    def _sector(self, sector_id: int) -> bytes:
        if sector_id < 0:
            return b""
        start = (sector_id + 1) * self.sector_size
        end = start + self.sector_size
        if start >= len(self.data):
            raise IngestionError(f"invalid OLE sector offset: {sector_id}")
        sector = self.data[start:min(end, len(self.data))]
        if len(sector) < self.sector_size:
            sector += b"\x00" * (self.sector_size - len(sector))
        return sector

    def _load_fat(self) -> None:
        fat_sector_ids = [
            int.from_bytes(self.data[offset:offset + 4], "little")
            for offset in range(76, 76 + 109 * 4, 4)
        ]
        fat_sector_ids = [
            item for item in fat_sector_ids
            if item not in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN)
        ]

        next_difat = self.first_difat_sector
        for _ in range(self.num_difat_sectors):
            if next_difat in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN):
                break
            sector = self._sector(next_difat)
            entries = [
                int.from_bytes(sector[offset:offset + 4], "little")
                for offset in range(0, self.sector_size - 4, 4)
            ]
            fat_sector_ids.extend(
                item for item in entries
                if item not in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN)
            )
            next_difat = int.from_bytes(
                sector[self.sector_size - 4:self.sector_size],
                "little",
            )

        for sector_id in fat_sector_ids:
            sector = self._sector(sector_id)
            self.fat.extend(
                int.from_bytes(sector[offset:offset + 4], "little")
                for offset in range(0, self.sector_size, 4)
            )

    def _read_chain(self, start_sector: int, *, limit: int | None = None) -> bytes:
        if start_sector in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN):
            return b""
        chunks: list[bytes] = []
        seen: set[int] = set()
        sector_id = start_sector
        while sector_id not in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN):
            if sector_id in seen or sector_id >= len(self.fat):
                raise IngestionError("invalid OLE FAT chain")
            seen.add(sector_id)
            chunks.append(self._sector(sector_id))
            sector_id = self.fat[sector_id]
        payload = b"".join(chunks)
        return payload[:limit] if limit is not None else payload

    def _load_directory(self) -> None:
        directory = self._read_chain(self.first_dir_sector)
        root_stream: tuple[int, int] | None = None
        for offset in range(0, len(directory) - 127, 128):
            entry = directory[offset:offset + 128]
            name_len = int.from_bytes(entry[64:66], "little")
            obj_type = entry[66]
            if name_len < 2:
                continue
            name_raw = entry[:name_len - 2]
            try:
                name = name_raw.decode("utf-16le", errors="ignore")
            except UnicodeDecodeError:
                continue
            start_sector = int.from_bytes(entry[116:120], "little")
            size = int.from_bytes(entry[120:128], "little")
            if obj_type == 2:
                self.streams[name] = (start_sector, size)
            elif obj_type == 5:
                root_stream = (start_sector, size)
        if root_stream:
            self._mini_stream = self._read_chain(root_stream[0], limit=root_stream[1])

    def _load_mini_fat(self) -> None:
        if self.first_mini_fat_sector in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN):
            return
        mini_fat_bytes = self._read_chain(self.first_mini_fat_sector)
        if self.num_mini_fat_sectors:
            mini_fat_bytes = mini_fat_bytes[:self.num_mini_fat_sectors * self.sector_size]
        self.mini_fat = [
            int.from_bytes(mini_fat_bytes[offset:offset + 4], "little")
            for offset in range(0, len(mini_fat_bytes) - 3, 4)
        ]

    def _read_mini_chain(self, start_sector: int, size: int) -> bytes:
        chunks: list[bytes] = []
        seen: set[int] = set()
        sector_id = start_sector
        while sector_id not in (_OLE_FREE_SECT, _OLE_END_OF_CHAIN):
            if sector_id in seen or sector_id >= len(self.mini_fat):
                raise IngestionError("invalid OLE mini-FAT chain")
            seen.add(sector_id)
            start = sector_id * self.mini_sector_size
            chunks.append(self._mini_stream[start:start + self.mini_sector_size])
            sector_id = self.mini_fat[sector_id]
        return b"".join(chunks)[:size]

    def read_stream(self, name: str) -> bytes:
        if name not in self.streams:
            raise KeyError(name)
        start_sector, size = self.streams[name]
        if size < self.mini_cutoff and self._mini_stream and self.mini_fat:
            return self._read_mini_chain(start_sector, size)
        return self._read_chain(start_sector, limit=size)


def _extract_doc(data: bytes, filename: str) -> ExtractedDocument:
    converted = _convert_doc_to_docx(data, filename)
    if converted:
        extracted = _extract_docx(converted, filename)
        extracted.warnings.append("legacy .doc converted via LibreOffice")
        return extracted

    try:
        streams = _OleCompoundFile(data)
        word_document = streams.read_stream("WordDocument")
    except Exception as exc:
        raise IngestionError(
            "legacy .doc requires LibreOffice conversion or a valid WordDocument stream"
        ) from exc

    table_stream = b""
    flags = int.from_bytes(word_document[10:12], "little") if len(word_document) >= 12 else 0
    preferred_table = "1Table" if flags & 0x0200 else "0Table"
    for name in (preferred_table, "0Table", "1Table"):
        try:
            table_stream = streams.read_stream(name)
            break
        except KeyError:
            continue

    text = _extract_doc_text_from_streams(word_document, table_stream)
    if not text.strip():
        raise IngestionError(
            "no extractable text in legacy .doc; install LibreOffice for conversion"
        )
    return ExtractedDocument(
        content=text,
        source_format="markdown",
        warnings=["legacy .doc extracted from WordDocument stream"],
    )


def _convert_doc_to_docx(data: bytes, filename: str) -> bytes | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None

    safe_name = Path(filename).name or "upload.doc"
    if not safe_name.lower().endswith(".doc"):
        safe_name = f"{safe_name}.doc"

    with tempfile.TemporaryDirectory(prefix="kb-doc-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / safe_name
        source.write_bytes(data)
        command = [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(tmp_path),
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(tmp_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("legacy doc conversion failed for %s: %s", filename, exc)
            return None

        converted = source.with_suffix(".docx")
        if completed.returncode != 0 or not converted.exists():
            stderr = completed.stderr.decode("utf-8", errors="ignore").strip()
            logger.warning("legacy doc conversion failed for %s: %s", filename, stderr)
            return None
        return converted.read_bytes()


def _extract_doc_text_from_streams(word_document: bytes, table_stream: bytes) -> str:
    candidates: list[str] = []
    for clx in _doc_clx_candidates(word_document, table_stream):
        text = _extract_doc_piece_table_text(word_document, clx)
        if _is_readable_doc_text(text):
            candidates.append(text)
    if candidates:
        return max(candidates, key=len)

    fallback = _extract_readable_binary_text(word_document)
    return fallback if _is_readable_doc_text(fallback) else ""


def _doc_clx_candidates(word_document: bytes, table_stream: bytes) -> list[bytes]:
    candidates: list[bytes] = []
    if len(word_document) >= 0x01AA and table_stream:
        fc_clx = int.from_bytes(word_document[0x01A2:0x01A6], "little")
        lcb_clx = int.from_bytes(word_document[0x01A6:0x01AA], "little")
        if lcb_clx and fc_clx + lcb_clx <= len(table_stream):
            candidates.append(table_stream[fc_clx:fc_clx + lcb_clx])
    if table_stream:
        candidates.append(table_stream)
    return candidates


def _extract_doc_piece_table_text(word_document: bytes, clx: bytes) -> str:
    parts: list[str] = []
    for pcdt in _iter_doc_piece_tables(clx):
        if len(pcdt) < 16 or (len(pcdt) - 4) % 12:
            continue
        piece_count = (len(pcdt) - 4) // 12
        cp_values = [
            int.from_bytes(pcdt[offset:offset + 4], "little")
            for offset in range(0, (piece_count + 1) * 4, 4)
        ]
        if any(cp_values[idx] > cp_values[idx + 1] for idx in range(piece_count)):
            continue

        pcd_offset = (piece_count + 1) * 4
        for index in range(piece_count):
            cp_start = cp_values[index]
            cp_end = cp_values[index + 1]
            if cp_end <= cp_start:
                pcd_offset += 8
                continue
            fc_compressed = int.from_bytes(pcdt[pcd_offset + 2:pcd_offset + 6], "little")
            is_compressed = bool(fc_compressed & 0x40000000)
            fc = fc_compressed & 0x3FFFFFFF
            if is_compressed:
                start = fc // 2
                raw = word_document[start:start + (cp_end - cp_start)]
                parts.append(_decode_doc_single_byte(raw))
            else:
                start = fc
                raw = word_document[start:start + ((cp_end - cp_start) * 2)]
                parts.append(raw.decode("utf-16le", errors="ignore"))
            pcd_offset += 8
    return _clean_extracted_doc_text("\n".join(parts))


def _iter_doc_piece_tables(clx: bytes):
    positions = [0]
    positions.extend(idx for idx, value in enumerate(clx) if value == 0x02)
    seen: set[int] = set()
    for start in positions:
        if start in seen:
            continue
        seen.add(start)
        pos = start
        while pos < len(clx):
            marker = clx[pos]
            if marker == 0x01 and pos + 3 <= len(clx):
                grpprl_size = int.from_bytes(clx[pos + 1:pos + 3], "little")
                pos += 3 + grpprl_size
                continue
            if marker == 0x02 and pos + 5 <= len(clx):
                size = int.from_bytes(clx[pos + 1:pos + 5], "little")
                end = pos + 5 + size
                if 0 < size and end <= len(clx):
                    yield clx[pos + 5:end]
                break
            pos += 1


def _decode_doc_single_byte(raw: bytes) -> str:
    best = ""
    for encoding in ("gb18030", "cp1252", "latin-1"):
        text = raw.decode(encoding, errors="ignore")
        cleaned = _clean_extracted_doc_text(text)
        if _is_readable_doc_text(cleaned) and len(cleaned) > len(best):
            best = cleaned
    return best or raw.decode("latin-1", errors="ignore")


def _extract_readable_binary_text(data: bytes) -> str:
    candidates: list[str] = []
    for encoding in ("utf-16le", "gb18030", "utf-8", "latin-1"):
        text = data.decode(encoding, errors="ignore")
        cleaned = _clean_extracted_doc_text(text)
        if _is_readable_doc_text(cleaned):
            candidates.append(cleaned)
    return max(candidates, key=len) if candidates else ""


def _clean_extracted_doc_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("\x0b", "\n").replace("\x0c", "\n")
    cleaned_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in ("\n", "\t"):
            cleaned_chars.append(ch)
        elif code >= 32 and not (0xE000 <= code <= 0xF8FF):
            cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _is_readable_doc_text(text: str) -> bool:
    if len(text.strip()) < 2:
        return False
    useful = 0
    for ch in text:
        if ch.isspace() or ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch in "，。！？；：、,.!?;:()[]-_/":
            useful += 1
    return useful / max(1, len(text)) >= 0.55


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
