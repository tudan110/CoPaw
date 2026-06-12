# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for permanent source deletion (knowledge_base.delete_sources)."""

import sys
from pathlib import Path

import pytest

KNOWLEDGE_BASE_SKILL_ROOT = (
    Path(__file__).resolve().parents[4]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "knowledge"
    / "skills"
    / "knowledge-base"
)
if str(KNOWLEDGE_BASE_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_BASE_SKILL_ROOT))


from qwenpaw.extensions.integrations import knowledge_base  # noqa: E402


@pytest.fixture()
def kb_env(tmp_path, monkeypatch):
    """Bootstrap the knowledge engine against an isolated temp data dir."""
    data_dir = tmp_path / "kbdata"
    monkeypatch.setenv(
        "QWENPAW_KNOWLEDGE_BASE_SKILL_ROOT",
        str(KNOWLEDGE_BASE_SKILL_ROOT),
    )
    monkeypatch.setenv("QWENPAW_KNOWLEDGE_BASE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNOWLEDGE_BASE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNOWLEDGE_BASE_EMBEDDING_ENABLED", "false")
    monkeypatch.setattr(knowledge_base, "_ENGINE_READY", False)

    from core import db as kb_db  # noqa: WPS433

    kb_db.close_thread_connection()
    try:
        knowledge_base._ensure_engine()
    except (RuntimeError, ImportError) as exc:  # sqlite-vec not loadable
        pytest.skip(f"knowledge engine unavailable in this env: {exc}")

    yield kb_db

    kb_db.close_thread_connection()
    monkeypatch.setattr(knowledge_base, "_ENGINE_READY", False)


def _create_doc(kb_db, *, storage_file: Path | None = None) -> int:
    result = knowledge_base.manual_entry(
        {
            "title": "割接步骤",
            "content": "网络割接需要先做配置备份，再执行变更。",
        },
    )
    doc_id = int(result["id"])
    if storage_file is not None:
        storage_file.parent.mkdir(parents=True, exist_ok=True)
        storage_file.write_bytes(b"original upload")
        with kb_db.connect() as conn:
            conn.execute(
                "UPDATE document SET storage_path=? WHERE id=?",
                (str(storage_file), doc_id),
            )
    return doc_id


def _counts(kb_db, doc_id: int) -> dict:
    with kb_db.connect() as conn:
        doc = conn.execute(
            "SELECT COUNT(*) AS n FROM document WHERE id=?",
            (doc_id,),
        ).fetchone()["n"]
        parents = conn.execute(
            "SELECT COUNT(*) AS n FROM parent_chunk WHERE document_id=?",
            (doc_id,),
        ).fetchone()["n"]
        children = conn.execute(
            "SELECT COUNT(*) AS n FROM child_chunk WHERE document_id=?",
            (doc_id,),
        ).fetchone()["n"]
    return {"doc": doc, "parents": parents, "children": children}


def test_delete_removes_rows_and_upload_file(kb_env, tmp_path):
    storage = tmp_path / "kbdata" / "uploads" / "abc.txt"
    doc_id = _create_doc(kb_env, storage_file=storage)
    before = _counts(kb_env, doc_id)
    assert before["doc"] == 1 and before["children"] >= 1
    assert storage.exists()

    result = knowledge_base.delete_sources({"source_record_ids": [doc_id]})

    assert result["deleted"] == 1
    assert result["ids"] == [doc_id]
    assert result["removed_files"] == 1
    after = _counts(kb_env, doc_id)
    assert after == {"doc": 0, "parents": 0, "children": 0}
    assert not storage.exists()


def test_delete_is_permanent_not_archived(kb_env):
    doc_id = _create_doc(kb_env)
    knowledge_base.delete_sources({"source_record_ids": [doc_id]})

    # unarchive must NOT bring it back (it is gone, not flagged)
    knowledge_base.unarchive_sources({"source_record_ids": [doc_id]})
    assert _counts(kb_env, doc_id)["doc"] == 0


def test_delete_never_touches_files_outside_data_dir(kb_env, tmp_path):
    outside = tmp_path / "outside" / "precious.txt"
    doc_id = _create_doc(kb_env, storage_file=outside)

    result = knowledge_base.delete_sources({"source_record_ids": [doc_id]})

    assert result["deleted"] == 1
    assert result["removed_files"] == 0
    assert outside.exists()  # safety: file outside data dir is untouched


def test_delete_with_unknown_or_bad_ids_is_noop(kb_env):
    result = knowledge_base.delete_sources(
        {"source_record_ids": ["abc", None, 999999]},
    )
    assert result["deleted"] == 0
    assert result["removed_files"] == 0


def test_delete_accepts_camel_case_payload(kb_env):
    doc_id = _create_doc(kb_env)
    result = knowledge_base.delete_sources({"sourceRecordIds": [doc_id]})
    assert result["deleted"] == 1
