"""Dense recall via sqlite-vec KNN over normalized embedding vectors."""

from __future__ import annotations

import logging
import math

import sqlite_vec  # type: ignore

from core import db


logger = logging.getLogger(__name__)


def normalize(vec: list[float]) -> list[float]:
    """L2-normalize so vec0's default L2 distance ranks equivalently to cosine."""
    if not vec:
        return vec
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0.0:
        return vec
    return [x / norm for x in vec]


def search(
    query_vector: list[float],
    *,
    top_k: int = 100,
    filters: dict | None = None,
) -> list[tuple[int, float, int]]:
    """Find top_k nearest child chunks to query_vector. Returns
    (chunk_id, normalized_score, rank). Score is in [0, 1] with higher = closer.

    To honor filters (which join through child_chunk and document) we over-fetch
    by 3x and post-filter in SQL — this keeps the KNN pure while still letting
    callers narrow by source_scope / document_ids.
    """
    if not query_vector:
        return []

    qvec = normalize(query_vector)
    qbytes = sqlite_vec.serialize_float32(qvec)

    where, params = _filter_clauses(filters)
    fetch_k = top_k * 3 if filters else top_k

    sql = f"""
        SELECT cc.id AS chunk_id, cv.distance AS distance
        FROM child_vec cv
        JOIN child_chunk cc ON cc.id = cv.chunk_id
        JOIN document d ON d.id = cc.document_id
        WHERE cv.embedding MATCH ?
          AND cc.archived_at IS NULL
          AND d.archived_at IS NULL
          {where}
        ORDER BY cv.distance
        LIMIT ?
    """
    args = [qbytes, *params, fetch_k]

    with db.connect() as conn:
        rows = conn.execute(sql, args).fetchall()

    if not rows:
        return []

    # vec0 default metric is L2. For unit-normalized vectors, L2² = 2(1 - cos),
    # so similarity = 1 - L2²/2. Clamp into [0, 1] for fusion-friendly units.
    out: list[tuple[int, float, int]] = []
    for rank, r in enumerate(rows[:top_k]):
        l2_sq = float(r["distance"]) ** 2
        sim = max(0.0, min(1.0, 1.0 - l2_sq / 2.0))
        out.append((r["chunk_id"], sim, rank))
    return out


def _filter_clauses(filters: dict | None) -> tuple[str, list]:
    if not filters:
        return "", []

    clauses: list[str] = []
    params: list = []

    scope = filters.get("source_scope")
    if scope:
        clauses.append("d.source_scope = ?")
        params.append(scope)

    stype = filters.get("source_type")
    if stype:
        clauses.append("d.source_type = ?")
        params.append(stype)

    doc_ids = filters.get("document_ids")
    if doc_ids:
        placeholders = ",".join("?" * len(doc_ids))
        clauses.append(f"d.id IN ({placeholders})")
        params.extend(doc_ids)

    return (" AND " + " AND ".join(clauses), params) if clauses else ("", [])
