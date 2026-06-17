"""HTTP entrypoint for the knowledge-base skill.

Thin routing layer over `core/` + `providers/`. Wire format must stay
byte-compatible with `portal/src/api/knowledgeBase.ts` — every response shape
flows through `api/serializers.py`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import sqlite_vec  # type: ignore

from core import db, ingestion
from core import retrieval as retrieval_module
from api import serializers
from providers import embedding, llm


# ----------------------------- Configuration ------------------------------

DEFAULT_HOST = os.environ.get("KNOWLEDGE_BASE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("KNOWLEDGE_BASE_PORT", "8765"))
MAX_UPLOAD_BYTES = int(os.environ.get(
    "KNOWLEDGE_BASE_MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)
))
# Streaming buffer for reading the request body / scanning multipart parts.
_UPLOAD_CHUNK = 1 << 20  # 1 MiB
INGEST_WORKERS = int(os.environ.get("KNOWLEDGE_BASE_INGEST_WORKERS", "2"))
ENV_EMBEDDING_FORCED_OFF = (
    os.environ.get("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "").lower() == "false"
)


logging.basicConfig(
    level=os.environ.get("KNOWLEDGE_BASE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("knowledge-base.server")


# Skill root used in /health response so operators can see where this skill
# is actually running from.
SKILL_ROOT = Path(__file__).resolve().parent


# Process-global runtime toggles (the env var is the persistent counterpart).
_embedding_runtime_enabled = True
_runtime_lock = threading.Lock()


# Background pool for async ingestion jobs.
_ingest_pool = ThreadPoolExecutor(
    max_workers=INGEST_WORKERS, thread_name_prefix="kb-ingest"
)


# ----------------------------- Multipart parsing ---------------------------

def parse_uploaded_file(handler: BaseHTTPRequestHandler) -> dict | None:
    """Pull the first uploaded file out of a multipart/form-data POST.

    Streams the request body to a temp file and reads back only the first file
    part's payload, so peak memory is ~one copy of that file rather than the
    3-4 copies the stdlib email parser held (the previous OOM cause on large
    uploads). Returns None if the Content-Type isn't multipart or no file part
    is present.
    """
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        return None

    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return None
    if length > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"upload exceeds max size {MAX_UPLOAD_BYTES} bytes (got {length})"
        )

    boundary = _multipart_boundary(content_type)
    if not boundary:
        return None

    with tempfile.NamedTemporaryFile(prefix="kb-upload-", delete=False) as tmp:
        tmp_path = tmp.name
        remaining = length
        while remaining > 0:
            chunk = handler.rfile.read(min(remaining, _UPLOAD_CHUNK))
            if not chunk:
                break
            tmp.write(chunk)
            remaining -= len(chunk)
    try:
        return _read_first_file_part(tmp_path, boundary)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _multipart_boundary(content_type: str) -> bytes | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            value = part[len("boundary="):].strip().strip('"')
            return value.encode("latin-1") if value else None
    return None


_MULTIPART_HEADER_SEP = b"\r\n\r\n"


def _scan_file(fh, needle: bytes, start: int) -> int:
    """Find `needle` in an open binary file from offset `start`, reading in
    bounded chunks (so memory stays flat for huge bodies). Returns the absolute
    offset, or -1 if not found."""
    overlap = len(needle) - 1
    fh.seek(start)
    buf = b""
    base = start
    while True:
        chunk = fh.read(_UPLOAD_CHUNK)
        if not chunk:
            return -1
        buf += chunk
        idx = buf.find(needle)
        if idx != -1:
            return base + idx
        if overlap > 0 and len(buf) > overlap:
            base += len(buf) - overlap
            buf = buf[-overlap:]
        elif overlap <= 0:
            base += len(buf)
            buf = b""


def _read_at(fh, offset: int, size: int) -> bytes:
    fh.seek(offset)
    return fh.read(size)


def _read_first_file_part(path: str, boundary: bytes) -> dict | None:
    """Walk the multipart parts in the temp file and return the first one that
    carries a filename, reading only its payload bytes into memory."""
    delim = b"--" + boundary
    with open(path, "rb") as fh:
        pos = _scan_file(fh, delim, 0)
        while pos != -1:
            after = pos + len(delim)
            marker = _read_at(fh, after, 2)
            if marker == b"--":
                break  # closing boundary "--boundary--"
            header_start = after + 2  # skip the CRLF after the delimiter
            sep = _scan_file(fh, _MULTIPART_HEADER_SEP, header_start)
            if sep == -1:
                break
            headers = _read_at(fh, header_start, sep - header_start)
            payload_start = sep + len(_MULTIPART_HEADER_SEP)
            nxt = _scan_file(fh, b"\r\n" + delim, payload_start)
            if nxt == -1:
                break
            filename = _multipart_filename(headers)
            if filename:
                return {
                    "filename": filename,
                    "mime_type": _multipart_content_type(headers),
                    "raw": _read_at(fh, payload_start, nxt - payload_start),
                }
            pos = _scan_file(fh, delim, nxt)
    return None


def _multipart_filename(headers: bytes) -> str | None:
    """Extract the filename from a part's Content-Disposition header. Browsers
    send UTF-8; RFC 5987 `filename*=UTF-8''...` is also handled. Any path
    components are stripped for safety."""
    text = headers.decode("utf-8", "replace")
    m = re.search(r"filename\*\s*=\s*([^;\r\n]+)", text)
    if m:
        value = m.group(1).strip()
        if "''" in value:
            value = value.split("''", 1)[1]
        name = unquote(value)
        if name:
            return Path(name).name
    m = re.search(r'filename\s*=\s*"([^"]*)"', text)
    if m and m.group(1).strip():
        return Path(m.group(1)).name
    m = re.search(r"filename\s*=\s*([^;\r\n]+)", text)
    if m and m.group(1).strip():
        return Path(m.group(1).strip().strip('"')).name
    return None


def _multipart_content_type(headers: bytes) -> str:
    text = headers.decode("utf-8", "replace")
    m = re.search(r"(?im)^Content-Type:\s*([^\r\n;]+)", text)
    return m.group(1).strip() if m else "application/octet-stream"


# ----------------------------- Background ingestion -----------------------

def submit_ingestion_job(
    job_id: str,
    filename: str,
    content_bytes: bytes,
    *,
    source_type: str,
    source_scope: str,
) -> None:
    """Run ingest_file() on the background pool and stream progress into the
    `ingestion_job` row so /progress polls reflect real status."""

    def _runner() -> None:
        def _progress(stage: str, pct: float) -> None:
            try:
                with db.connect() as conn:
                    conn.execute(
                        """UPDATE ingestion_job
                           SET status='running', current_stage=?,
                               progress_pct=?, updated_at=?
                           WHERE id=?""",
                        (stage, pct * 100.0, _now_iso(), job_id),
                    )
            except Exception:
                logger.exception("progress update failed for job %s", job_id)

        try:
            result = ingestion.ingest_file(
                filename, content_bytes,
                source_type=source_type,
                source_scope=source_scope,
                progress_callback=_progress,
            )
            with db.connect() as conn:
                conn.execute(
                    """UPDATE ingestion_job
                       SET status='success', current_stage='success',
                           progress_pct=100, parent_count=?, child_count=?,
                           document_id=?, finished_at=?, updated_at=?
                       WHERE id=?""",
                    (
                        result.parent_count, result.child_count,
                        result.document_id, _now_iso(), _now_iso(), job_id,
                    ),
                )
        except Exception as exc:
            logger.exception("ingestion job %s failed", job_id)
            with db.connect() as conn:
                conn.execute(
                    """UPDATE ingestion_job
                       SET status='failed', current_stage='failed',
                           error_message=?, finished_at=?, updated_at=?
                       WHERE id=?""",
                    (str(exc), _now_iso(), _now_iso(), job_id),
                )

    _ingest_pool.submit(_runner)


# ----------------------------- HTTP handler -------------------------------

# Route table. Each entry is (method, pattern, handler_method_name).
# `pattern` is either a literal path (no path params) or a compiled regex
# whose match groups are forwarded to the handler.
_ROUTES: list[tuple[str, object, str]] = [
    ("GET",  "/knowledge-base/health", "_health"),
    ("POST", "/knowledge-base/query", "_query"),
    ("POST", "/knowledge-base/rag-synthesize", "_rag_synthesize"),
    ("GET",  "/knowledge-base/sources", "_list_sources"),
    ("GET",  re.compile(r"^/knowledge-base/sources/(\d+)$"), "_source_detail"),
    ("POST", "/knowledge-base/sources/archive", "_archive_sources"),
    ("POST", "/knowledge-base/sources/unarchive", "_unarchive_sources"),
    ("POST", "/knowledge-base/sources/update", "_update_source"),
    ("POST", "/knowledge-base/ingest", "_ingest"),
    ("GET",  re.compile(r"^/knowledge-base/ingestion-jobs/([^/]+)/progress$"),
             "_ingest_progress"),
    ("GET",  "/knowledge-base/ingestion-jobs", "_list_ingestion_jobs"),
    ("POST", "/knowledge-base/manual-entry", "_manual_entry"),
    ("POST", "/knowledge-base/embedding/toggle", "_toggle_embedding"),
    ("POST", "/knowledge-base/embeddings/reindex", "_reindex_embeddings"),
    ("GET",  "/knowledge-base/source-summary", "_source_summary"),
    ("GET",  "/knowledge-base/units", "_list_units"),
    ("GET",  "/knowledge-base/builtin-packs", "_list_builtin_packs"),
    ("POST", "/knowledge-base/builtin-packs/reload", "_reload_builtin_packs"),
]


class KBHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args) -> None:
        # Route stdlib's BaseHTTPRequestHandler logs through our logger so the
        # access lines and JSON business logs share a stream.
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            for m, pattern, handler_name in _ROUTES:
                if m != method:
                    continue
                if isinstance(pattern, str):
                    if pattern == path:
                        getattr(self, handler_name)(parsed)
                        return
                else:
                    match = pattern.match(path)
                    if match:
                        getattr(self, handler_name)(parsed, *match.groups())
                        return
            self._write_error(404, "not_found", f"no route for {method} {path}")
        except _ClientError as exc:
            self._write_error(exc.status, exc.code, exc.message)
        except Exception as exc:
            logger.exception("unhandled error in %s %s", method, path)
            self._write_error(500, "server_error", str(exc) or repr(exc))

    # ---- Response helpers ----

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Agent-Id")

    def _write_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _write_error(self, status: int, code: str, message: str) -> None:
        self._write_json(
            {"error": {"code": code, "message": message}}, status=status
        )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _ClientError(400, "bad_json", f"invalid JSON body: {exc}")

    # ---- Endpoint handlers ----

    def _health(self, parsed) -> None:
        self._write_json({
            "status": "ok",
            "storage": {
                "skillRoot": str(SKILL_ROOT),
                "dataDir": str(db.get_data_dir()),
                "dbPath": str(db.get_db_path()),
            },
            "llm": {
                "enabled": llm.is_available("deepseek"),
                "provider": "deepseek",
            },
            "embedding": {
                "enabled": _is_embedding_enabled(),
                "key_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
                "env_forced_off": ENV_EMBEDDING_FORCED_OFF,
                "provider": "dashscope",
            },
            "schema": db.health_check(),
            "rerank_strategy": os.environ.get(
                "KNOWLEDGE_BASE_RERANKER", "heuristic"
            ),
            "hyde_enabled": retrieval_module.HYDE_ENABLED,
        })

    def _query(self, parsed) -> None:
        body = self._read_json()
        query_text = (body.get("query") or "").strip()
        if not query_text:
            raise _ClientError(400, "missing_query", "field 'query' is required")
        filters = body.get("filters") or {}
        top_k = int(body.get("top_k") or retrieval_module.DEFAULT_TOP_K)

        resp = retrieval_module.query(query_text, filters=filters, top_k=top_k)
        self._write_json(serializers.serialize_query_response(resp))

    def _rag_synthesize(self, parsed) -> None:
        body = self._read_json()
        query_text = (body.get("query") or "").strip()
        evidence_ids = body.get("evidence_ids") or []
        if not query_text or not evidence_ids:
            self._write_json({
                "answer": "",
                "skipped": True,
                "reason": "missing_query_or_evidence",
                "evidence_ids": evidence_ids,
            })
            return

        # Coerce string ids to int (frontend treats them opaquely).
        try:
            int_ids = [int(x) for x in evidence_ids]
        except (TypeError, ValueError):
            raise _ClientError(400, "bad_evidence_ids", "evidence_ids must be numeric")

        contexts = _fetch_evidence_for_synthesis(int_ids)
        if not contexts:
            self._write_json({
                "answer": "",
                "skipped": True,
                "reason": "evidence_not_found",
                "evidence_ids": evidence_ids,
            })
            return

        if not llm.is_available("deepseek"):
            self._write_json({
                "answer": "",
                "skipped": True,
                "reason": "llm_unavailable",
                "evidence_ids": evidence_ids,
            })
            return

        prompt = _build_synthesis_prompt(query_text, contexts)
        try:
            result = llm.call_llm(
                "deepseek",
                messages=[{"role": "user", "content": prompt}],
                request_id="rag-synth",
                timeout_s=60.0,
            )
        except llm.LLMError as exc:
            self._write_json({
                "answer": "",
                "skipped": True,
                "reason": exc.reason,
                "evidence_ids": evidence_ids,
            })
            return

        self._write_json({
            "answer": result["answer"],
            "provider": result.get("provider"),
            "model": result.get("model"),
            "model_label": result.get("model"),
            "model_source": "skill_default",
            "evidence_ids": evidence_ids,
            "latency_ms": result.get("latency_ms"),
        })

    def _list_sources(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        limit = _qs_int(qs, "limit", 50, 1, 500)
        offset = _qs_int(qs, "offset", 0, 0, 1_000_000)
        include_archived = _qs_bool(qs, "include_archived", False)
        filename = _qs_str(qs, "filename")
        scope = _qs_str(qs, "source_scope")
        stype = _qs_str(qs, "source_type")

        clauses = []
        params: list = []
        if not include_archived:
            clauses.append("d.archived_at IS NULL")
        if filename:
            clauses.append("d.filename LIKE ?")
            params.append(f"%{filename}%")
        if scope:
            clauses.append("d.source_scope = ?")
            params.append(scope)
        if stype:
            clauses.append("d.source_type = ?")
            params.append(stype)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM document d {where}", params
            ).fetchone()["n"]

            rows = conn.execute(
                f"""SELECT d.*,
                          (SELECT COUNT(*) FROM child_chunk cc
                           WHERE cc.document_id = d.id AND cc.archived_at IS NULL)
                          AS unit_count
                    FROM document d
                    {where}
                    ORDER BY d.uploaded_at DESC
                    LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()

        items = [
            serializers.serialize_source_record(r, unit_count=r["unit_count"])
            for r in rows
        ]
        self._write_json({
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    def _source_detail(self, parsed, source_id_str: str) -> None:
        qs = parse_qs(parsed.query)
        include_archived = _qs_bool(qs, "include_archived", False)
        try:
            source_id = int(source_id_str)
        except ValueError:
            raise _ClientError(400, "bad_id", f"invalid source id: {source_id_str}")

        with db.connect() as conn:
            doc = conn.execute(
                "SELECT * FROM document WHERE id = ?", (source_id,)
            ).fetchone()
            if doc is None:
                raise _ClientError(404, "not_found", f"document {source_id} not found")
            if doc["archived_at"] and not include_archived:
                raise _ClientError(404, "archived", "document is archived")

            unit_clause = "" if include_archived else "AND cc.archived_at IS NULL"
            units = conn.execute(
                f"""SELECT cc.id, cc.content, cc.created_at,
                          pc.section_path, pc.locator,
                          d.filename, d.source_type, d.source_scope, d.uploaded_at
                    FROM child_chunk cc
                    JOIN parent_chunk pc ON pc.id = cc.parent_id
                    JOIN document d ON d.id = cc.document_id
                    WHERE cc.document_id = ? {unit_clause}
                    ORDER BY cc.id ASC""",
                (source_id,),
            ).fetchall()

            unit_count = conn.execute(
                "SELECT COUNT(*) AS n FROM child_chunk WHERE document_id=? AND archived_at IS NULL",
                (source_id,),
            ).fetchone()["n"]

        payload = serializers.serialize_source_record(doc, unit_count=unit_count)
        payload["storage_path"] = doc["storage_path"]
        payload["units"] = [serializers.serialize_unit_row(u) for u in units]
        self._write_json(payload)

    def _archive_sources(self, parsed) -> None:
        body = self._read_json()
        ids = body.get("source_record_ids") or []
        reason = body.get("reason") or "portal archive"
        ints = _coerce_int_list(ids)
        if not ints:
            self._write_json({"archived": 0})
            return
        placeholders = ",".join("?" * len(ints))
        now = _now_iso()
        with db.connect() as conn:
            conn.execute(
                f"""UPDATE document SET archived_at = ?, archive_reason = ?
                   WHERE id IN ({placeholders}) AND archived_at IS NULL""",
                [now, reason, *ints],
            )
            conn.execute(
                f"""UPDATE parent_chunk SET archived_at = ?
                   WHERE document_id IN ({placeholders}) AND archived_at IS NULL""",
                [now, *ints],
            )
            conn.execute(
                f"""UPDATE child_chunk SET archived_at = ?
                   WHERE document_id IN ({placeholders}) AND archived_at IS NULL""",
                [now, *ints],
            )
        self._write_json({"archived": len(ints), "ids": ints})

    def _unarchive_sources(self, parsed) -> None:
        body = self._read_json()
        ids = body.get("source_record_ids") or []
        ints = _coerce_int_list(ids)
        if not ints:
            self._write_json({"unarchived": 0})
            return
        placeholders = ",".join("?" * len(ints))
        with db.connect() as conn:
            conn.execute(
                f"""UPDATE document SET archived_at = NULL, archive_reason = NULL
                   WHERE id IN ({placeholders})""",
                ints,
            )
            conn.execute(
                f"""UPDATE parent_chunk SET archived_at = NULL
                   WHERE document_id IN ({placeholders})""",
                ints,
            )
            conn.execute(
                f"""UPDATE child_chunk SET archived_at = NULL
                   WHERE document_id IN ({placeholders})""",
                ints,
            )
        self._write_json({"unarchived": len(ints), "ids": ints})

    def _update_source(self, parsed) -> None:
        body = self._read_json()
        try:
            source_id = int(body["source_record_id"])
        except (KeyError, ValueError, TypeError):
            raise _ClientError(400, "bad_id", "source_record_id is required (int)")

        display_title = (body.get("display_title") or "").strip()
        tags = body.get("tags") or []
        note = body.get("note") or ""
        scope = body.get("source_scope") or ""

        with db.connect() as conn:
            row = conn.execute(
                "SELECT meta_json, source_scope FROM document WHERE id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                raise _ClientError(404, "not_found", f"document {source_id} not found")

            meta = serializers._safe_json(row["meta_json"]) or {}
            if display_title:
                meta["display_title"] = display_title
            if tags is not None:
                meta["tags"] = list(tags)
            if note:
                meta["note"] = note

            new_scope = scope or row["source_scope"]
            conn.execute(
                "UPDATE document SET meta_json = ?, source_scope = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), new_scope, source_id),
            )
        self._write_json({"updated": True, "source_record_id": source_id})

    def _ingest(self, parsed) -> None:
        try:
            uploaded = parse_uploaded_file(self)
        except ValueError as exc:
            raise _ClientError(413, "upload_too_large", str(exc))
        if not uploaded:
            raise _ClientError(400, "missing_file", "no 'file' field in multipart body")

        filename = uploaded["filename"]
        source_type = _detect_source_type(filename, uploaded.get("mime_type"))
        job_id = str(uuid.uuid4())
        now = _now_iso()

        with db.connect() as conn:
            conn.execute(
                """INSERT INTO ingestion_job
                   (id, filename, source_type, status, current_stage,
                    progress_pct, created_at, updated_at)
                   VALUES (?, ?, ?, 'queued', 'queued', 0, ?, ?)""",
                (job_id, filename, source_type, now, now),
            )

        submit_ingestion_job(
            job_id, filename, uploaded["raw"],
            source_type=source_type,
            source_scope="tenant_private",
        )

        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_job WHERE id = ?", (job_id,)
            ).fetchone()
        self._write_json(serializers.serialize_ingest_job(row))

    def _ingest_progress(self, parsed, job_id: str) -> None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_job WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise _ClientError(404, "not_found", f"job {job_id} not found")
            existing = db.existing_document_ids(conn, [row["document_id"]])
        self._write_json(
            serializers.serialize_ingest_job(row, existing_doc_ids=existing)
        )

    def _list_ingestion_jobs(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        limit = _qs_int(qs, "limit", 20, 1, 200)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ingestion_job ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            existing = db.existing_document_ids(
                conn, [r["document_id"] for r in rows]
            )
        self._write_json({
            "items": [
                serializers.serialize_ingest_job(r, existing_doc_ids=existing)
                for r in rows
            ]
        })

    def _manual_entry(self, parsed) -> None:
        body = self._read_json()
        title = (body.get("title") or "").strip()
        content = (body.get("content") or "").strip()
        tags = body.get("tags") or []
        if not title or not content:
            raise _ClientError(400, "bad_request", "'title' and 'content' are required")

        try:
            result = ingestion.ingest_manual(
                title=title, content=content,
                meta={"display_title": title, "tags": tags},
            )
        except ingestion.IngestionError as exc:
            raise _ClientError(400, "ingest_failed", str(exc))

        self._write_json({
            "document_id": result.document_id,
            "parent_count": result.parent_count,
            "child_count": result.child_count,
            "embedded": result.embedded,
        })

    def _toggle_embedding(self, parsed) -> None:
        body = self._read_json()
        requested = bool(body.get("enabled"))
        global _embedding_runtime_enabled

        reject_reason: str | None = None
        if requested and not embedding.is_available():
            reject_reason = "DASHSCOPE_API_KEY not configured"
        elif requested and ENV_EMBEDDING_FORCED_OFF:
            reject_reason = "embedding is forced off via env (KNOWLEDGE_BASE_EMBEDDING_ENABLED=false)"

        changed = False
        if reject_reason is None:
            with _runtime_lock:
                if _embedding_runtime_enabled != requested:
                    _embedding_runtime_enabled = requested
                    changed = True

        self._write_json({
            "enabled": _is_embedding_enabled(),
            "key_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
            "env_forced_off": ENV_EMBEDDING_FORCED_OFF,
            "provider": "dashscope",
            "changed": changed,
            "reject_reason": reject_reason,
        })

    def _reindex_embeddings(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        force = _qs_bool(qs, "force", False)
        if not _is_embedding_enabled():
            raise _ClientError(409, "embedding_disabled", "enable embeddings first")

        with db.connect() as conn:
            if force:
                rows = conn.execute(
                    "SELECT id, content FROM child_chunk WHERE archived_at IS NULL"
                ).fetchall()
                conn.execute("DELETE FROM child_vec")
            else:
                rows = conn.execute(
                    """SELECT id, content FROM child_chunk
                       WHERE archived_at IS NULL
                         AND id NOT IN (SELECT chunk_id FROM child_vec)"""
                ).fetchall()

        if not rows:
            self._write_json({"reindexed": 0, "force": force})
            return

        chunk_ids = [r["id"] for r in rows]
        texts = [r["content"] for r in rows]

        try:
            vectors = embedding.embed_batched(texts, batch_id="reindex")
        except embedding.EmbeddingError as exc:
            raise _ClientError(503, exc.reason, str(exc))

        # Re-normalize at insert (matches ingestion path).
        from retrieval.recall_dense import normalize as _normalize
        with db.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO child_vec(chunk_id, embedding) VALUES (?, ?)",
                [
                    (cid, sqlite_vec.serialize_float32(_normalize(vec)))
                    for cid, vec in zip(chunk_ids, vectors)
                ],
            )

        self._write_json({"reindexed": len(rows), "force": force})

    def _source_summary(self, parsed) -> None:
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT d.source_scope, d.source_type,
                          COUNT(DISTINCT d.id) AS source_count,
                          COUNT(cc.id) AS unit_count,
                          MAX(d.uploaded_at) AS latest_created_at
                   FROM document d
                   LEFT JOIN child_chunk cc
                     ON cc.document_id = d.id AND cc.archived_at IS NULL
                   WHERE d.archived_at IS NULL
                   GROUP BY d.source_scope, d.source_type
                   ORDER BY d.source_scope, d.source_type"""
            ).fetchall()
        self._write_json({
            "items": [serializers.serialize_summary_row(r) for r in rows]
        })

    def _list_units(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        limit = _qs_int(qs, "limit", 50, 1, 500)
        include_archived = _qs_bool(qs, "include_archived", False)
        filename = _qs_str(qs, "filename")
        scope = _qs_str(qs, "source_scope")
        stype = _qs_str(qs, "source_type")

        clauses = []
        params: list = []
        if not include_archived:
            clauses.append("cc.archived_at IS NULL")
            clauses.append("d.archived_at IS NULL")
        if filename:
            clauses.append("d.filename LIKE ?")
            params.append(f"%{filename}%")
        if scope:
            clauses.append("d.source_scope = ?")
            params.append(scope)
        if stype:
            clauses.append("d.source_type = ?")
            params.append(stype)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with db.connect() as conn:
            rows = conn.execute(
                f"""SELECT cc.id, cc.content, cc.created_at,
                          pc.section_path, pc.locator,
                          d.filename, d.source_type, d.source_scope, d.uploaded_at
                    FROM child_chunk cc
                    JOIN parent_chunk pc ON pc.id = cc.parent_id
                    JOIN document d ON d.id = cc.document_id
                    {where}
                    ORDER BY cc.id DESC
                    LIMIT ?""",
                [*params, limit],
            ).fetchall()
        self._write_json({"items": [serializers.serialize_unit_row(r) for r in rows]})

    def _list_builtin_packs(self, parsed) -> None:
        # Builtin packs were a feature of the old skill (pre-shipped knowledge
        # bundles). The new system has no first-class concept yet — return an
        # empty list so the portal's admin UI degrades cleanly.
        self._write_json({"items": []})

    def _reload_builtin_packs(self, parsed) -> None:
        self._write_json({"reloaded": 0, "note": "builtin packs not supported in the new pipeline yet"})


# ----------------------------- Helpers ------------------------------------

class _ClientError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _is_embedding_enabled() -> bool:
    if ENV_EMBEDDING_FORCED_OFF:
        return False
    if not embedding.is_available():
        return False
    return _embedding_runtime_enabled


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _qs_int(qs: dict, key: str, default: int, lo: int, hi: int) -> int:
    val = qs.get(key, [str(default)])[0]
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _qs_bool(qs: dict, key: str, default: bool) -> bool:
    val = qs.get(key, [str(default).lower()])[0]
    return val.lower() in ("1", "true", "yes", "y", "on")


def _qs_str(qs: dict, key: str) -> str | None:
    val = qs.get(key, [""])[0].strip()
    return val or None


def _coerce_int_list(items) -> list[int]:
    out: list[int] = []
    for x in items or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _detect_source_type(filename: str, mime_type: str | None) -> str:
    lowered = (filename or "").lower()
    if lowered.endswith(".pdf") or mime_type == "application/pdf":
        return "pdf"
    if lowered.endswith((".docx",)):
        return "docx"
    if lowered.endswith((".doc",)):
        return "doc"
    if lowered.endswith(".pptx") or mime_type == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ):
        return "pptx"
    if lowered.endswith((".md", ".markdown")):
        return "markdown"
    if lowered.endswith((".txt",)):
        return "plain"
    if mime_type and mime_type.startswith("image/"):
        return "image"
    if lowered.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")):
        return "image"
    if lowered.endswith(".eml"):
        return "email"
    return "document"


# ----------------------------- RAG synthesis ------------------------------

def _fetch_evidence_for_synthesis(child_ids: list[int]) -> list[dict]:
    if not child_ids:
        return []
    placeholders = ",".join("?" * len(child_ids))
    sql = f"""
        SELECT cc.id, cc.content AS child_content,
               pc.content AS parent_content,
               pc.section_path, pc.locator,
               d.filename, d.source_scope
        FROM child_chunk cc
        JOIN parent_chunk pc ON pc.id = cc.parent_id
        JOIN document d ON d.id = cc.document_id
        WHERE cc.id IN ({placeholders})
          AND cc.archived_at IS NULL
    """
    with db.connect() as conn:
        rows = conn.execute(sql, child_ids).fetchall()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "section_path": r["section_path"] or "",
            "locator": r["locator"] or "",
            "context": r["parent_content"],
        }
        for r in rows
    ]


def _build_synthesis_prompt(query: str, contexts: list[dict]) -> str:
    blocks = []
    for i, ctx in enumerate(contexts, 1):
        header = f"【证据 {i}】来源：{ctx['filename']}"
        if ctx["section_path"]:
            header += f" / {ctx['section_path']}"
        if ctx["locator"]:
            header += f" / {ctx['locator']}"
        blocks.append(f"{header}\n{ctx['context']}")
    evidence_block = "\n\n".join(blocks)
    return (
        "你是运维知识库助手。仅基于下方知识库证据回答用户问题。"
        "如证据不足以支撑明确结论，请直接说明，不要编造。\n\n"
        f"用户问题：{query}\n\n"
        f"知识库证据：\n{evidence_block}\n\n"
        "回答要求：\n"
        "1. 给出可执行的步骤或结论；\n"
        "2. 在关键结论后用括号标注引用的证据编号，例如（证据1）；\n"
        "3. 控制在 300 字以内。"
    )


# ----------------------------- Entrypoint ---------------------------------

def main() -> None:
    db.init_db()
    httpd = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), KBHandler)
    health = db.health_check()
    logger.info(
        "knowledge-base server starting on %s:%d (db=%s, schema_v=%d, dim=%d)",
        DEFAULT_HOST, DEFAULT_PORT, health["db_path"],
        health["schema_version"], health["embedding_dim"],
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        _ingest_pool.shutdown(wait=False)
        httpd.server_close()


if __name__ == "__main__":
    main()
