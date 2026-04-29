"""Sparse recall via SQLite FTS5 BM25 over jieba-tokenized child chunks."""

from __future__ import annotations

import logging
import re

import jieba

from core import db


logger = logging.getLogger(__name__)


# FTS5 reserves these characters; either escape via double-quoting (which we
# do per token) or strip them entirely from the token to be safe.
_FTS_BAD_CHARS = re.compile(r"""[\"'()*+\-:^]""")


def search(
    query_texts: list[str],
    *,
    top_k: int = 100,
    filters: dict | None = None,
) -> list[tuple[int, float, int]]:
    """Run BM25 against a list of query texts (the original + synonym variants),
    aggregate by union of hits, return up to top_k unique candidates.

    Returns a list of (chunk_id, normalized_score, rank). Scores are flipped to
    higher-is-better and min-max normalized within this call.
    """
    if not query_texts:
        return []

    match_query = _build_match_query(query_texts)
    if not match_query:
        return []

    where, params = _filter_clauses(filters)
    sql = f"""
        SELECT cc.id AS chunk_id, bm25(child_fts) AS bm25_score
        FROM child_fts
        JOIN child_chunk cc ON cc.id = child_fts.rowid
        JOIN document d ON d.id = cc.document_id
        WHERE child_fts MATCH ?
          AND cc.archived_at IS NULL
          AND d.archived_at IS NULL
          {where}
        ORDER BY bm25_score
        LIMIT ?
    """
    args = [match_query, *params, top_k]

    with db.connect() as conn:
        rows = conn.execute(sql, args).fetchall()

    if not rows:
        return []

    # FTS5 bm25() returns negative-magnitude scores (lower = more relevant).
    # Flip + min-max normalize to [0, 1] so the fusion stage sees comparable units.
    raw = [(r["chunk_id"], -float(r["bm25_score"])) for r in rows]
    scores = [s for _, s in raw]
    s_min, s_max = min(scores), max(scores)
    span = s_max - s_min or 1.0

    return [
        (cid, (s - s_min) / span, rank)
        for rank, (cid, s) in enumerate(raw)
    ]


def _build_match_query(query_texts: list[str]) -> str:
    """Tokenize all query variants with jieba, OR them together. Tokens are
    quoted so FTS5 doesn't interpret special characters."""
    tokens: list[str] = []
    seen: set[str] = set()

    for text in query_texts:
        if not text:
            continue
        for tok in jieba.cut_for_search(text):
            tok = _FTS_BAD_CHARS.sub(" ", tok).strip()
            if not tok or tok in seen:
                continue
            seen.add(tok)
            tokens.append(f'"{tok}"')

    return " OR ".join(tokens)


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
