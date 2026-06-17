"""Internal-type → frontend-contract serializers.

Single source of truth for the wire shape consumed by `portal/src/api/knowledgeBase.ts`.
Keep field names byte-compatible with that file. Extra (unknown) fields are
fine — the TS types don't fail closed on them.
"""

from __future__ import annotations

import json

from core.retrieval import Evidence, QueryResponse


SCOPE_LABELS = {
    "tenant_private": "私域沉淀",
    "system_builtin": "系统内置",
    "runtime_curated": "运行时整理",
}


def serialize_evidence(e: Evidence) -> dict:
    return {
        "evidence_id": str(e.evidence_id),
        "confidence_score": e.confidence_score,
        "confidence_level": e.confidence_level,
        "chunk_summary": e.chunk_summary,
        "chunk_text": e.chunk_text,
        "citation": {
            "source_label": e.citation.get("source_label"),
            "source_scope_label": e.citation.get("source_scope_label"),
            "section_path": e.citation.get("section_path"),
            "locator": e.citation.get("locator"),
        },
        "meta": e.meta,
    }


def serialize_query_response(resp: QueryResponse) -> dict:
    return {
        "query_id": resp.query_id,
        "summary": resp.summary,
        "relevant_evidence": [serialize_evidence(e) for e in resp.relevant_evidence],
        "evidence_boundary_statement": resp.evidence_boundary_statement,
        "flags": resp.flags,
    }


def serialize_source_record(row, *, unit_count: int = 0) -> dict:
    """Map a `document` row to KnowledgeSourceRecord shape."""
    meta = _safe_json(row["meta_json"]) or {}
    return {
        "id": row["id"],
        "filename": row["filename"],
        "source_type": row["source_type"],
        "source_scope": row["source_scope"],
        "uploaded_at": row["uploaded_at"],
        "archived_at": row["archived_at"],
        "archive_reason": row["archive_reason"],
        "unit_count": unit_count,
        "meta": {
            "display_title": meta.get("display_title", ""),
            "tags": meta.get("tags", []) or [],
            "scope_label": SCOPE_LABELS.get(
                row["source_scope"], row["source_scope"]
            ),
        },
    }


def serialize_unit_row(row) -> dict:
    """Map a child_chunk row (joined with parent + document) to KnowledgeUnit
    plus ingest-job-derived fields the listing endpoint exposes."""
    return {
        "id": str(row["id"]),
        "title": row["section_path"] or row["filename"],
        "content": row["content"],
        "locator": row["locator"],
        "source_type": row["source_type"],
        "source_scope": row["source_scope"],
        "filename": row["filename"],
        "uploaded_at": row["uploaded_at"],
        "created_at": row["created_at"],
        "meta": {},
    }


def serialize_ingest_job(row, *, existing_doc_ids: set | None = None) -> dict:
    """Map an `ingestion_job` row to KnowledgeIngestJob shape. The frontend
    polls until status ∈ {success, failed}.

    When `existing_doc_ids` is provided (the set of document ids that still
    exist), a job whose `document_id` is absent from it is flagged
    `document_deleted=True` — its source was hard-deleted but the job row
    remains. Without the set we can't tell, so the flag stays False.
    """
    job_id = row["id"]
    document_id = row["document_id"]
    document_deleted = bool(
        document_id is not None
        and existing_doc_ids is not None
        and document_id not in existing_doc_ids
    )
    return {
        "job_id": job_id,
        "id": job_id,
        "filename": row["filename"],
        "source_type": row["source_type"],
        "status": row["status"],
        "current_stage": row["current_stage"],
        "progress_pct": float(row["progress_pct"] or 0),
        "unit_count": int(row["child_count"] or 0),
        "document_id": document_id,
        "document_deleted": document_deleted,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
        "note": row["error_message"],
        "poll_url": f"/knowledge-base/ingestion-jobs/{job_id}/progress",
    }


def serialize_summary_row(row) -> dict:
    return {
        "source_scope": row["source_scope"],
        "source_type": row["source_type"],
        "unit_count": int(row["unit_count"] or 0),
        "source_count": int(row["source_count"] or 0),
        "latest_created_at": row["latest_created_at"],
    }


def _safe_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None
