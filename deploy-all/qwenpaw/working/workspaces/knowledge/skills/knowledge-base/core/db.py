"""SQLite + sqlite-vec + FTS5 storage layer for the knowledge base.

Single source of truth for: connection management, sqlite-vec extension loading,
schema bootstrap, and pragma tuning.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import sqlite_vec


SCHEMA_VERSION = 1

EMBEDDING_DIM = int(os.getenv("KNOWLEDGE_BASE_EMBEDDING_DIM", "1024"))


def get_data_dir() -> Path:
    """Resolve the data directory. Honors env overrides, defaults to skill_dir/data/."""
    base = os.getenv("KNOWLEDGE_BASE_DATA_DIR") or os.getenv(
        "QWENPAW_KNOWLEDGE_BASE_DATA_DIR"
    )
    if base:
        path = Path(base).expanduser().resolve()
    else:
        # core/db.py → skill_dir = parent.parent
        path = Path(__file__).resolve().parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    return get_data_dir() / "knowledge.db"


def _open_connection(db_path: Path) -> sqlite3.Connection:
    """Open a fresh connection with sqlite-vec loaded and pragmas applied."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        conn.close()
        raise RuntimeError(
            "sqlite-vec extension load failed. The host Python's sqlite3 module "
            "must be built with --enable-loadable-sqlite-extensions."
        ) from exc

    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;
        PRAGMA temp_store=MEMORY;
        PRAGMA cache_size=-65536;
        """
    )
    return conn


_LOCAL = threading.local()


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    """Yield a thread-local connection. Commits on success, rolls back on error."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = _open_connection(get_db_path())
        _LOCAL.conn = conn

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_thread_connection() -> None:
    """Close the connection associated with the current thread, if any."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _LOCAL.conn = None


SCHEMA_SQL = f"""
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Source documents (file uploads, manual entries, builtin packs).
-- INTEGER PK so the portal frontend's KnowledgeSourceRecord.id (number) maps
-- 1:1 — no string/integer translation layer needed.
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_scope TEXT NOT NULL DEFAULT 'tenant_private',
    storage_path TEXT,
    extracted_text_length INTEGER,
    uploaded_at TEXT NOT NULL,
    archived_at TEXT,
    archive_reason TEXT,
    meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_document_scope ON document(source_scope);
CREATE INDEX IF NOT EXISTS idx_document_type ON document(source_type);
CREATE INDEX IF NOT EXISTS idx_document_archived ON document(archived_at);

-- Parent chunks: large context returned to the LLM (~1500 tokens)
CREATE TABLE IF NOT EXISTS parent_chunk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    section_path TEXT,
    locator TEXT,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT,
    meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_parent_doc ON parent_chunk(document_id);
CREATE INDEX IF NOT EXISTS idx_parent_archived ON parent_chunk(archived_at);

-- Child chunks: retrieval grain (~300 tokens). The integer id is the
-- canonical rowid shared by FTS5 and sqlite-vec virtual tables.
CREATE TABLE IF NOT EXISTS child_chunk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL REFERENCES parent_chunk(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_tokenized TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_child_parent ON child_chunk(parent_id);
CREATE INDEX IF NOT EXISTS idx_child_doc ON child_chunk(document_id);
CREATE INDEX IF NOT EXISTS idx_child_archived ON child_chunk(archived_at);

-- BM25 inverted index over the jieba-tokenized child content
CREATE VIRTUAL TABLE IF NOT EXISTS child_fts USING fts5(
    content_tokenized,
    content='child_chunk',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 0'
);

-- FTS5 sync triggers (external content table pattern)
CREATE TRIGGER IF NOT EXISTS child_fts_ai AFTER INSERT ON child_chunk BEGIN
    INSERT INTO child_fts(rowid, content_tokenized)
        VALUES (new.id, new.content_tokenized);
END;

CREATE TRIGGER IF NOT EXISTS child_fts_ad AFTER DELETE ON child_chunk BEGIN
    INSERT INTO child_fts(child_fts, rowid, content_tokenized)
        VALUES ('delete', old.id, old.content_tokenized);
END;

CREATE TRIGGER IF NOT EXISTS child_fts_au AFTER UPDATE OF content_tokenized ON child_chunk BEGIN
    INSERT INTO child_fts(child_fts, rowid, content_tokenized)
        VALUES ('delete', old.id, old.content_tokenized);
    INSERT INTO child_fts(rowid, content_tokenized)
        VALUES (new.id, new.content_tokenized);
END;

-- HNSW vector index over child chunks (sqlite-vec)
CREATE VIRTUAL TABLE IF NOT EXISTS child_vec USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[{EMBEDDING_DIM}]
);

-- Cascade vec0 delete when the source row is removed
CREATE TRIGGER IF NOT EXISTS child_vec_ad AFTER DELETE ON child_chunk BEGIN
    DELETE FROM child_vec WHERE chunk_id = old.id;
END;

-- Async ingestion job tracking. job id is a UUID string (frontend treats it
-- opaquely); document_id once known is the integer FK to document(id).
CREATE TABLE IF NOT EXISTS ingestion_job (
    id TEXT PRIMARY KEY,
    filename TEXT,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT,
    progress_pct REAL NOT NULL DEFAULT 0,
    document_id INTEGER,
    error_message TEXT,
    parent_count INTEGER NOT NULL DEFAULT 0,
    child_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    finished_at TEXT,
    meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_status ON ingestion_job(status, created_at DESC);

-- Query log for retrieval-quality evaluation
CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL UNIQUE,
    query_text TEXT NOT NULL,
    expanded_text TEXT,
    filters_json TEXT,
    top_evidence_ids TEXT,
    top_score REAL,
    confidence_level TEXT,
    insufficient_evidence INTEGER NOT NULL DEFAULT 0,
    sparse_recall_count INTEGER,
    dense_recall_count INTEGER,
    rerank_strategy TEXT,
    latency_ms INTEGER,
    user_feedback TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at DESC);
"""


def init_db() -> None:
    """Idempotently bootstrap the schema. Safe to call on every start."""
    with connect() as conn:
        conn.executescript(SCHEMA_SQL)

        cur = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        row = cur.fetchone()
        current = row["version"] if row else 0

        if current < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )


def health_check() -> dict:
    """Return basic stats for diagnostics endpoints."""
    with connect() as conn:
        doc_count = conn.execute(
            "SELECT COUNT(*) AS n FROM document WHERE archived_at IS NULL"
        ).fetchone()["n"]
        parent_count = conn.execute(
            "SELECT COUNT(*) AS n FROM parent_chunk WHERE archived_at IS NULL"
        ).fetchone()["n"]
        child_count = conn.execute(
            "SELECT COUNT(*) AS n FROM child_chunk WHERE archived_at IS NULL"
        ).fetchone()["n"]
        vec_count = conn.execute(
            "SELECT COUNT(*) AS n FROM child_vec"
        ).fetchone()["n"]
        version = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return {
            "schema_version": version["version"] if version else 0,
            "embedding_dim": EMBEDDING_DIM,
            "documents": doc_count,
            "parent_chunks": parent_count,
            "child_chunks": child_count,
            "vector_rows": vec_count,
            "sqlite_version": sqlite3.sqlite_version,
            "db_path": str(get_db_path()),
        }


def existing_document_ids(conn, ids) -> set:
    """Return the subset of *ids* that still have a row in `document`.

    Used to flag ingestion jobs whose source was hard-deleted (the job row
    survives the delete, leaving a dangling document_id)."""
    wanted = {int(i) for i in ids if i is not None}
    if not wanted:
        return set()
    placeholders = ",".join("?" * len(wanted))
    rows = conn.execute(
        f"SELECT id FROM document WHERE id IN ({placeholders})",
        tuple(wanted),
    ).fetchall()
    return {row["id"] for row in rows}
