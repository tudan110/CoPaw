"""Bridge between QwenPaw's portal_backend and the knowledge-base skill engine.

Adds the skill root to sys.path, bootstraps the schema, and exposes a stable
public surface that ``portal_backend.py`` relies on. All internal queries hit
the new schema (``document`` / ``parent_chunk`` / ``child_chunk``); response
shapes go through ``api/serializers.py`` so the portal frontend gets exactly
what it expects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_ENGINE_LOCK = threading.Lock()
_ENGINE_READY = False
_INGEST_POOL: ThreadPoolExecutor | None = None
_EMBEDDING_RUNTIME_ENABLED = True


# ---------- Path resolution ----------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def skill_root() -> Path:
    configured = os.getenv("QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    working_dir = os.getenv("QWENPAW_WORKING_DIR", "").strip()
    if working_dir:
        candidate = (
            Path(working_dir).expanduser()
            / "workspaces"
            / "knowledge"
            / "skills"
            / "knowledge-base"
        ).resolve()
        if candidate.exists():
            return candidate

    runtime_candidate = (
        Path.home()
        / ".qwenpaw"
        / "workspaces"
        / "knowledge"
        / "skills"
        / "knowledge-base"
    ).resolve()
    if runtime_candidate.exists():
        return runtime_candidate

    return (
        _repo_root()
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "knowledge"
        / "skills"
        / "knowledge-base"
    )


def data_dir() -> Path:
    configured = (
        os.getenv("QWENPAW_KNOWLEDGE_BASE_DATA_DIR")
        or os.getenv("KNOWLEDGE_BASE_DATA_DIR")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (skill_root() / "data").resolve()


# ---------- Engine bootstrap ----------


def _ensure_engine() -> None:
    """Idempotent: make sure the skill modules are importable and the schema
    is bootstrapped. Every public function calls this first."""
    global _ENGINE_READY, _INGEST_POOL
    if _ENGINE_READY:
        return
    with _ENGINE_LOCK:
        if _ENGINE_READY:
            return

        root = skill_root()
        if not root.exists():
            raise FileNotFoundError(f"knowledge-base skill not found: {root}")

        os.environ.setdefault("KNOWLEDGE_BASE_DATA_DIR", str(data_dir()))
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        # First-time imports load jieba, sqlite-vec, tiktoken — let any
        # ImportError surface clearly so the operator sees what's missing.
        from core import db as _db  # noqa: WPS433

        _db.init_db()

        if _INGEST_POOL is None:
            _INGEST_POOL = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="kb-ingest"
            )

        _ENGINE_READY = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_embedding_enabled() -> bool:
    if (
        os.environ.get("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "").lower()
        == "false"
    ):
        return False
    from providers import embedding as _embedding

    if not _embedding.is_available():
        return False
    return _EMBEDDING_RUNTIME_ENABLED


# ---------- /health ----------


def health() -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from providers import llm as _llm

    h = _db.health_check()
    env_forced_off = (
        os.environ.get("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "").lower()
        == "false"
    )
    return {
        "status": "ok" if _ENGINE_READY else "initializing",
        "storage": {
            "skillRoot": str(skill_root()),
            "dataDir": str(data_dir()),
            "dbPath": h["db_path"],
        },
        "llm": {
            "enabled": _llm.is_available("deepseek"),
            "provider": "deepseek",
        },
        "embedding": {
            "enabled": _is_embedding_enabled(),
            "key_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
            "env_forced_off": env_forced_off,
            "provider": "dashscope",
        },
    }


# ---------- /query ----------


def query_knowledge(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    body = payload or {}
    query = str(body.get("query") or "").strip()
    if not query:
        raise ValueError("missing query")

    from core import retrieval as _retrieval
    from api import serializers as _serializers

    resp = _retrieval.query(query, filters=body.get("filters") or {})
    return _serializers.serialize_query_response(resp)


# ---------- /rag-synthesize ----------


def _extract_model_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    fragments.append(str(text))
            elif getattr(item, "text", None):
                fragments.append(str(getattr(item, "text")))
        return "\n".join(f.strip() for f in fragments if f).strip()
    text = getattr(payload, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(payload).strip()


async def _consume_model_text(response: Any) -> str:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_model_text(chunk)
            if not text:
                continue
            if text.startswith(accumulated):
                accumulated = text
            else:
                accumulated += text
        return accumulated.strip()
    return _extract_model_text(response)


def _resolve_active_model_metadata(
    agent_id: str | None = None,
) -> dict[str, str]:
    try:
        from qwenpaw.config.config import load_agent_config
        from qwenpaw.providers import ProviderManager

        manager = ProviderManager.get_instance()
        model_slot = None
        source = "global"
        normalized_agent_id = str(agent_id or "").strip()
        if normalized_agent_id:
            try:
                agent_config = load_agent_config(normalized_agent_id)
                candidate = agent_config.active_model
                if candidate and candidate.provider_id and candidate.model:
                    model_slot = candidate
                    source = "agent"
            except Exception:
                pass

        if not model_slot:
            model_slot = manager.get_active_model()
            source = "global"

        if not model_slot:
            return {}

        provider_id = str(getattr(model_slot, "provider_id", "") or "")
        model_id = str(getattr(model_slot, "model", "") or "")
        provider_name = provider_id
        model_name = model_id
        try:
            provider = (
                manager.get_provider(provider_id) if provider_id else None
            )
            if provider:
                provider_name = str(
                    getattr(provider, "name", "") or provider_id
                )
                for item in list(getattr(provider, "models", []) or []) + list(
                    getattr(provider, "extra_models", []) or []
                ):
                    if str(getattr(item, "id", "") or "") == model_id:
                        model_name = str(getattr(item, "name", "") or model_id)
                        break
        except Exception:
            pass

        return {
            "provider": provider_id,
            "provider_name": provider_name,
            "model": model_id,
            "model_name": model_name,
            "model_label": " / ".join(
                p for p in [provider_name, model_name] if p
            ),
            "model_source": source,
        }
    except Exception:
        return {}


async def synthesize_answer(
    payload: dict[str, Any] | None, *, agent_id: str | None = None
) -> dict[str, Any]:
    _ensure_engine()
    body = payload or {}
    query = str(body.get("query") or "").strip()
    evidence_ids = body.get("evidence_ids") or body.get("evidenceIds") or []
    if not query:
        raise ValueError("missing query")
    if not isinstance(evidence_ids, list):
        evidence_ids = []

    int_ids: list[int] = []
    for x in evidence_ids:
        try:
            int_ids.append(int(x))
        except (TypeError, ValueError):
            continue

    from core import db as _db

    rows = []
    if int_ids:
        placeholders = ",".join("?" * len(int_ids))
        with _db.connect() as conn:
            rows = conn.execute(
                f"""SELECT cc.id,
                          pc.section_path AS title,
                          pc.content AS context,
                          pc.locator,
                          d.filename
                   FROM child_chunk cc
                   JOIN parent_chunk pc ON pc.id = cc.parent_id
                   JOIN document d ON d.id = cc.document_id
                   WHERE cc.id IN ({placeholders})
                     AND cc.archived_at IS NULL""",
                int_ids,
            ).fetchall()

    blocks: list[str] = []
    ordered_ids: list[str] = []
    for idx, row in enumerate(rows, start=1):
        ordered_ids.append(str(row["id"]))
        locator = (row["locator"] or "").strip()
        source = f"{row['filename']}{(' · ' + locator) if locator else ''}"
        title = row["title"] or row["filename"]
        blocks.append(f"[{idx}] {title}\n来源: {source}\n内容:\n{row['context']}")

    system_prompt = (
        "你是知识库问答的最终总结助手。你会先参考命中的知识片段，再结合通用运维知识作答。"
        "如果证据足够，直接给出可执行、准确的答案；如果证据不足，也要说明证据不足，"
        "再基于相似线索和通用经验给出审慎推断。不要编造不存在的引用来源。"
        "输出使用简洁中文，包含：结论、依据、建议下一步。"
    )
    evidence_text = "\n\n".join(blocks) if blocks else "本次知识库没有返回可直接引用的证据片段。"
    user_prompt = (
        f"用户问题：{query}\n\n" f"知识库证据：\n{evidence_text}\n\n" "请给出 AI 总结。"
    )

    from qwenpaw.agents.model_factory import create_model_and_formatter
    from agentscope.message import Msg, TextBlock

    model_agent_id = str(agent_id or "").strip() or "knowledge"
    model_metadata = _resolve_active_model_metadata(model_agent_id)
    model, _ = create_model_and_formatter(agent_id=model_agent_id)
    # agentscope's ChatModelBase expects Msg objects (it applies the formatter
    # internally). Passing role/content dicts raises "Expected Msg object, got
    # dict" — the same trap the big-screen pipeline hit; convert first.
    messages = [
        Msg(
            name=role,
            role=role,
            content=[TextBlock(type="text", text=text)],
        )
        for role, text in (
            ("system", system_prompt),
            ("user", user_prompt),
        )
    ]
    response = await model(messages)
    answer = await asyncio.wait_for(_consume_model_text(response), timeout=120)
    return {
        "answer": answer,
        **model_metadata,
        "evidence_ids": ordered_ids,
        "created_at": _now_iso(),
    }


# ---------- /sources ----------


def list_sources(
    *,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from api import serializers as _serializers

    f = filters or {}
    clauses: list[str] = []
    params: list = []
    if not include_archived:
        clauses.append("d.archived_at IS NULL")
    if f.get("filename"):
        clauses.append("d.filename LIKE ?")
        params.append(f"%{f['filename']}%")
    if f.get("source_scope"):
        clauses.append("d.source_scope = ?")
        params.append(f["source_scope"])
    if f.get("source_type"):
        clauses.append("d.source_type = ?")
        params.append(f["source_type"])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with _db.connect() as conn:
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
            [*params, int(limit), int(offset)],
        ).fetchall()

    return {
        "items": [
            _serializers.serialize_source_record(r, unit_count=r["unit_count"])
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def source_detail(
    source_record_id: int, *, include_archived: bool = False
) -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from api import serializers as _serializers

    sid = int(source_record_id)
    with _db.connect() as conn:
        doc = conn.execute(
            "SELECT * FROM document WHERE id = ?", (sid,)
        ).fetchone()
        if doc is None:
            raise LookupError("source record not found")
        if doc["archived_at"] and not include_archived:
            raise LookupError("source record is archived")

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
            (sid,),
        ).fetchall()

        unit_count = conn.execute(
            "SELECT COUNT(*) AS n FROM child_chunk WHERE document_id=? AND archived_at IS NULL",
            (sid,),
        ).fetchone()["n"]

    payload = _serializers.serialize_source_record(doc, unit_count=unit_count)
    payload["storage_path"] = doc["storage_path"]
    payload["units"] = [_serializers.serialize_unit_row(u) for u in units]
    return payload


# ---------- /manual-entry ----------


def manual_entry(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    body = payload or {}
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    if not title or not content:
        raise ValueError("title and content are required")
    if len(title) > 120:
        raise ValueError("title must be 120 characters or less")

    tags = body.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        tags = []

    meta = {
        "manually_entered": True,
        "tags": tags,
        "scope_label": "运行时沉淀",
        "display_title": title,
    }
    src_query = str(
        body.get("source_query") or body.get("sourceQuery") or ""
    ).strip()
    if src_query:
        meta["source_query"] = src_query

    from core import ingestion as _ingestion

    try:
        result = _ingestion.ingest_manual(
            title=title,
            content=content,
            source_scope="runtime_curated",
            meta=meta,
        )
    except _ingestion.IngestionError as exc:
        raise ValueError(str(exc))

    return {
        "id": result.document_id,
        "filename": title,
        "source_type": "document",
        "source_scope": "runtime_curated",
        "uploaded_at": _now_iso(),
        "unit_count": result.child_count,
        "meta": meta,
    }


# ---------- /sources/update | archive | unarchive ----------


def update_source(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    body = payload or {}
    src_id = body.get("source_record_id") or body.get("sourceRecordId")
    if src_id is None or src_id == "":
        raise ValueError("missing source_record_id")
    src_id = int(src_id)

    display_title = str(
        body.get("display_title") or body.get("displayTitle") or ""
    ).strip()
    tags = body.get("tags")
    note = str(body.get("note") or "").strip()
    scope = str(
        body.get("source_scope") or body.get("sourceScope") or ""
    ).strip()

    from core import db as _db

    with _db.connect() as conn:
        row = conn.execute(
            "SELECT meta_json, source_scope FROM document WHERE id = ?",
            (src_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"document {src_id} not found")
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except Exception:
            meta = {}
        if display_title:
            meta["display_title"] = display_title
        if tags is not None:
            meta["tags"] = list(tags)
        if note:
            meta["note"] = note
        new_scope = scope or row["source_scope"]
        conn.execute(
            "UPDATE document SET meta_json = ?, source_scope = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), new_scope, src_id),
        )
    return {"updated": True, "source_record_id": src_id}


def archive_sources(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    body = payload or {}
    ids = body.get("source_record_ids") or body.get("sourceRecordIds") or []
    reason = str(body.get("reason") or "portal archive").strip()
    return _archive_helper(ids, reason, archived=True)


def unarchive_sources(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    body = payload or {}
    ids = body.get("source_record_ids") or body.get("sourceRecordIds") or []
    return _archive_helper(ids, None, archived=False)


def _archive_helper(ids, reason, *, archived: bool) -> dict[str, Any]:
    int_ids: list[int] = []
    for x in ids:
        try:
            int_ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if not int_ids:
        return {"archived" if archived else "unarchived": 0, "ids": []}

    placeholders = ",".join("?" * len(int_ids))
    from core import db as _db

    if archived:
        now = _now_iso()
        with _db.connect() as conn:
            conn.execute(
                f"""UPDATE document SET archived_at=?, archive_reason=?
                   WHERE id IN ({placeholders}) AND archived_at IS NULL""",
                [now, reason, *int_ids],
            )
            conn.execute(
                f"""UPDATE parent_chunk SET archived_at=?
                   WHERE document_id IN ({placeholders}) AND archived_at IS NULL""",
                [now, *int_ids],
            )
            conn.execute(
                f"""UPDATE child_chunk SET archived_at=?
                   WHERE document_id IN ({placeholders}) AND archived_at IS NULL""",
                [now, *int_ids],
            )
        return {"archived": len(int_ids), "ids": int_ids}

    with _db.connect() as conn:
        conn.execute(
            f"""UPDATE document SET archived_at=NULL, archive_reason=NULL
               WHERE id IN ({placeholders})""",
            int_ids,
        )
        conn.execute(
            f"""UPDATE parent_chunk SET archived_at=NULL
               WHERE document_id IN ({placeholders})""",
            int_ids,
        )
        conn.execute(
            f"""UPDATE child_chunk SET archived_at=NULL
               WHERE document_id IN ({placeholders})""",
            int_ids,
        )
    return {"unarchived": len(int_ids), "ids": int_ids}


def delete_sources(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Permanently delete sources — unlike archive, this is irreversible.

    Removes document / parent_chunk / child_chunk rows (FTS and vector
    entries are cleaned up by the ``child_fts_ad`` / ``child_vec_ad``
    AFTER DELETE triggers) and best-effort removes the uploaded source
    file under ``data/uploads/``.
    """
    _ensure_engine()
    body = payload or {}
    ids = body.get("source_record_ids") or body.get("sourceRecordIds") or []
    reason = str(body.get("reason") or "portal delete").strip()

    int_ids: list[int] = []
    for x in ids:
        try:
            int_ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if not int_ids:
        return {"deleted": 0, "ids": [], "removed_files": 0}

    placeholders = ",".join("?" * len(int_ids))
    from core import db as _db

    with _db.connect() as conn:
        rows = conn.execute(
            f"""SELECT id, filename, storage_path FROM document
               WHERE id IN ({placeholders})""",
            int_ids,
        ).fetchall()
        existing_ids = [int(row["id"]) for row in rows]
        storage_paths = [
            str(row["storage_path"]) for row in rows if row["storage_path"]
        ]
        if existing_ids:
            ph = ",".join("?" * len(existing_ids))
            conn.execute(
                f"DELETE FROM child_chunk WHERE document_id IN ({ph})",
                existing_ids,
            )
            conn.execute(
                f"DELETE FROM parent_chunk WHERE document_id IN ({ph})",
                existing_ids,
            )
            conn.execute(
                f"DELETE FROM document WHERE id IN ({ph})",
                existing_ids,
            )

    # Best-effort removal of the uploaded originals. Only files inside the
    # knowledge data dir are touched, so a corrupted storage_path can never
    # delete anything outside the knowledge base.
    removed_files = 0
    uploads_root = (data_dir()).resolve()
    for raw_path in storage_paths:
        try:
            path = Path(raw_path).resolve()
            if path.is_file() and path.is_relative_to(uploads_root):
                path.unlink()
                removed_files += 1
        except (OSError, ValueError) as exc:
            logger.warning(
                "knowledge_base: failed to remove source file %s: %s",
                raw_path,
                exc,
            )

    logger.info(
        "knowledge_base: permanently deleted %d source(s) "
        "(%d file(s) removed, reason=%s)",
        len(existing_ids),
        removed_files,
        reason,
    )
    return {
        "deleted": len(existing_ids),
        "ids": existing_ids,
        "removed_files": removed_files,
    }


# ---------- /embedding/toggle | embeddings/reindex ----------


def set_embedding_enabled(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    global _EMBEDDING_RUNTIME_ENABLED
    requested = bool((payload or {}).get("enabled"))

    from providers import embedding as _embedding

    env_forced_off = (
        os.environ.get("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "").lower()
        == "false"
    )
    reject_reason: str | None = None
    if requested and not _embedding.is_available():
        reject_reason = "DASHSCOPE_API_KEY not configured"
    elif requested and env_forced_off:
        reject_reason = "embedding is forced off via env"

    changed = False
    if reject_reason is None:
        if _EMBEDDING_RUNTIME_ENABLED != requested:
            _EMBEDDING_RUNTIME_ENABLED = requested
            changed = True

    return {
        "enabled": _is_embedding_enabled(),
        "key_configured": bool(os.environ.get("DASHSCOPE_API_KEY")),
        "env_forced_off": env_forced_off,
        "provider": "dashscope",
        "changed": changed,
        "reject_reason": reject_reason,
    }


def reindex_embeddings(*, force: bool = False) -> dict[str, Any]:
    _ensure_engine()
    if not _is_embedding_enabled():
        raise RuntimeError("embedding disabled")

    from core import db as _db
    from providers import embedding as _embedding
    from retrieval.recall_dense import normalize as _normalize
    import sqlite_vec  # type: ignore

    with _db.connect() as conn:
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
        return {"requested": 0, "embedded": 0, "force": force}

    chunk_ids = [r["id"] for r in rows]
    texts = [r["content"] for r in rows]
    try:
        vectors = _embedding.embed_batched(texts, batch_id="reindex")
    except _embedding.EmbeddingError as exc:
        raise RuntimeError(f"embedding failed: {exc}")

    with _db.connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO child_vec(chunk_id, embedding) VALUES (?, ?)",
            [
                (cid, sqlite_vec.serialize_float32(_normalize(vec)))
                for cid, vec in zip(chunk_ids, vectors)
            ],
        )

    return {"requested": len(rows), "embedded": len(rows), "force": force}


# ---------- /ingest + /ingestion-jobs ----------


def create_ingest_job(
    filename: str, raw: bytes, mime_type: str | None = None
) -> dict[str, Any]:
    _ensure_engine()
    if not filename:
        raise ValueError("missing filename")
    if not raw:
        raise ValueError("empty file")

    from core import db as _db
    from core import ingestion as _ingestion

    safe_filename = Path(filename).name
    source_type = _detect_source_type(safe_filename, mime_type)
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    created_at = _now_iso()

    upload_dir = data_dir() / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{uuid.uuid4().hex}{Path(safe_filename).suffix}"
    target.write_bytes(raw)

    with _db.connect() as conn:
        conn.execute(
            """INSERT INTO ingestion_job
               (id, filename, source_type, status, current_stage, progress_pct,
                created_at, updated_at)
               VALUES (?, ?, ?, 'queued', 'queued', 0, ?, ?)""",
            (job_id, safe_filename, source_type, created_at, created_at),
        )

    def _progress(stage: str, pct: float) -> None:
        try:
            with _db.connect() as conn:
                conn.execute(
                    """UPDATE ingestion_job
                       SET status='running', current_stage=?,
                           progress_pct=?, updated_at=?
                       WHERE id=?""",
                    (stage, pct * 100, _now_iso(), job_id),
                )
        except Exception:
            logger.exception("progress update failed for job %s", job_id)

    def _runner() -> None:
        try:
            result = _ingestion.ingest_file(
                safe_filename,
                raw,
                source_type=source_type,
                source_scope="tenant_private",
                storage_path=str(target),
                progress_callback=_progress,
            )
            with _db.connect() as conn:
                conn.execute(
                    """UPDATE ingestion_job
                       SET status='success', current_stage='success',
                           progress_pct=100, parent_count=?, child_count=?,
                           document_id=?, finished_at=?, updated_at=?
                       WHERE id=?""",
                    (
                        result.parent_count,
                        result.child_count,
                        result.document_id,
                        _now_iso(),
                        _now_iso(),
                        job_id,
                    ),
                )
        except Exception as exc:
            logger.exception("ingestion job %s failed", job_id)
            with _db.connect() as conn:
                conn.execute(
                    """UPDATE ingestion_job
                       SET status='failed', current_stage='failed',
                           error_message=?, finished_at=?, updated_at=?
                       WHERE id=?""",
                    (str(exc), _now_iso(), _now_iso(), job_id),
                )

    assert _INGEST_POOL is not None
    _INGEST_POOL.submit(_runner)

    return {
        "job_id": job_id,
        "filename": safe_filename,
        "source_type": source_type,
        "status": "queued",
        "unit_count": 0,
        "preview_units": [],
        "note": "已接收，后台处理中",
        "poll_url": f"/api/portal/knowledge-base/ingestion-jobs/{job_id}/progress",
    }


def ingestion_jobs(limit: int = 20) -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from api import serializers as _serializers

    with _db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ingestion_job ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        existing = _db.existing_document_ids(
            conn, [r["document_id"] for r in rows]
        )
    return {
        "items": [
            _serializers.serialize_ingest_job(r, existing_doc_ids=existing)
            for r in rows
        ]
    }


def ingestion_progress(job_id: str) -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from api import serializers as _serializers

    with _db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM ingestion_job WHERE id=?", (job_id,)
        ).fetchone()
        if not row:
            raise LookupError("job not found")
        existing = _db.existing_document_ids(conn, [row["document_id"]])
    return _serializers.serialize_ingest_job(row, existing_doc_ids=existing)


# ---------- /source-summary | /units ----------


def source_summary() -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from api import serializers as _serializers

    with _db.connect() as conn:
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
    return {"items": [_serializers.serialize_summary_row(r) for r in rows]}


def units(
    *,
    limit: int = 50,
    include_archived: bool = False,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_engine()
    from core import db as _db
    from api import serializers as _serializers

    f = filters or {}
    clauses: list[str] = []
    params: list = []
    if not include_archived:
        clauses.append("cc.archived_at IS NULL")
        clauses.append("d.archived_at IS NULL")
    if f.get("filename"):
        clauses.append("d.filename LIKE ?")
        params.append(f"%{f['filename']}%")
    if f.get("source_scope"):
        clauses.append("d.source_scope = ?")
        params.append(f["source_scope"])
    if f.get("source_type"):
        clauses.append("d.source_type = ?")
        params.append(f["source_type"])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with _db.connect() as conn:
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
            [*params, int(limit)],
        ).fetchall()
    return {"items": [_serializers.serialize_unit_row(r) for r in rows]}


# ---------- /builtin-packs (no-op stubs) ----------


def builtin_packs() -> dict[str, Any]:
    _ensure_engine()
    return {"items": []}


def reload_builtin_pack(payload: dict[str, Any] | None) -> dict[str, Any]:
    _ensure_engine()
    return {
        "reloaded": 0,
        "note": "builtin packs not supported in the new pipeline",
    }


# ---------- helpers ----------


def _detect_source_type(filename: str, mime_type: str | None) -> str:
    lowered = (filename or "").lower()
    if lowered.endswith(".pdf") or mime_type == "application/pdf":
        return "pdf"
    if lowered.endswith(".docx"):
        return "docx"
    if lowered.endswith(".doc"):
        return "doc"
    if lowered.endswith(".pptx") or mime_type == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ):
        return "pptx"
    if lowered.endswith((".md", ".markdown")):
        return "markdown"
    if lowered.endswith(".txt"):
        return "plain"
    if mime_type and mime_type.startswith("image/"):
        return "image"
    if lowered.endswith(
        (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")
    ):
        return "image"
    if lowered.endswith(".eml"):
        return "email"
    if lowered.endswith((".xlsx", ".xlsm", ".xls", ".csv", ".tsv")):
        return "spreadsheet"
    return "document"


def dump_for_cli(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
