"""3-stage retrieval orchestrator: hybrid recall → RRF fusion → reranking.

Public entry: ``query(text, filters, top_k)``. Returns a QueryResponse that the
HTTP layer translates into the frontend's KnowledgeQueryResponse contract.

Side effect: every call appends a row to ``query_log`` for offline evaluation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core import db
from domain import query_expansion
from providers import embedding
from retrieval import fusion as rrf_module
from retrieval import recall_dense, recall_sparse
from retrieval import rerank as rerank_module


logger = logging.getLogger(__name__)


# ---------- Tunables ----------

SPARSE_TOP_K = int(os.environ.get("KNOWLEDGE_BASE_SPARSE_TOP_K", "100"))
DENSE_TOP_K = int(os.environ.get("KNOWLEDGE_BASE_DENSE_TOP_K", "100"))
FUSION_TOP_K = int(os.environ.get("KNOWLEDGE_BASE_FUSION_TOP_K", "50"))
DEFAULT_TOP_K = int(os.environ.get("KNOWLEDGE_BASE_TOP_K", "3"))

HYDE_ENABLED = os.environ.get("KNOWLEDGE_BASE_HYDE_ENABLED", "true").lower() == "true"
QUERY_EMBED_TIMEOUT = float(os.environ.get("KNOWLEDGE_BASE_QUERY_EMBED_TIMEOUT", "5.0"))
HYDE_TIMEOUT = float(os.environ.get("KNOWLEDGE_BASE_HYDE_TIMEOUT", "8.0"))

CHUNK_SUMMARY_CHARS = 220


# ---------- Public types ----------

@dataclass
class Evidence:
    evidence_id: int
    confidence_score: float
    confidence_level: str
    chunk_summary: str
    chunk_text: str
    citation: dict
    meta: dict


@dataclass
class QueryResponse:
    query_id: str
    query_text: str
    summary: str
    relevant_evidence: list[Evidence]
    evidence_boundary_statement: str
    flags: dict
    diagnostic: dict = field(default_factory=dict)


# ---------- Public API ----------

def query(
    query_text: str,
    *,
    filters: dict | None = None,
    top_k: int = DEFAULT_TOP_K,
    enable_hyde: bool | None = None,
) -> QueryResponse:
    """End-to-end retrieval. Always returns a QueryResponse — failures are
    encoded as `flags.insufficient_evidence=True` plus an empty evidence list."""
    started = time.monotonic()
    query_id = str(uuid.uuid4())
    query_text = (query_text or "").strip()
    use_hyde = HYDE_ENABLED if enable_hyde is None else enable_hyde

    diagnostic: dict = {
        "query_id": query_id,
        "rerank_strategy": os.environ.get("KNOWLEDGE_BASE_RERANKER", "heuristic"),
        "hyde_used": False,
    }

    if not query_text:
        return _empty_response(query_id, query_text, "查询为空。", diagnostic)

    # ----- Stage 0: query expansion -----
    variants = query_expansion.expand_with_synonyms(query_text)
    diagnostic["variant_count"] = len(variants)

    hyde_text: str | None = None
    if use_hyde:
        hyde_text = query_expansion.generate_hyde(
            query_text, timeout_s=HYDE_TIMEOUT, request_id=query_id
        )
        diagnostic["hyde_used"] = bool(hyde_text)

    # Embed: prefer HyDE answer when available, else literal query.
    embed_target = hyde_text or query_text
    query_vector: list[float] = []
    if embedding.is_available():
        try:
            query_vector = embedding.embed_query(
                embed_target, timeout_s=QUERY_EMBED_TIMEOUT
            )
        except embedding.EmbeddingError as exc:
            logger.warning("query_id=%s query embed failed: %s", query_id, exc)

    # ----- Stage 1: recall (parallel by intent — sequential here is fine for SQLite) -----
    sparse_hits = recall_sparse.search(
        variants, top_k=SPARSE_TOP_K, filters=filters
    )
    dense_hits: list[tuple[int, float, int]] = []
    if query_vector:
        dense_hits = recall_dense.search(
            query_vector, top_k=DENSE_TOP_K, filters=filters
        )
    diagnostic["sparse_recall"] = len(sparse_hits)
    diagnostic["dense_recall"] = len(dense_hits)

    if not sparse_hits and not dense_hits:
        latency_ms = int((time.monotonic() - started) * 1000)
        diagnostic["latency_ms"] = latency_ms
        _write_query_log(
            query_id, query_text, hyde_text, filters,
            top_evidence_ids=[], top_score=0.0, level="low",
            insufficient=True, sparse_n=0, dense_n=0,
            strategy=diagnostic["rerank_strategy"], latency_ms=latency_ms,
        )
        return _empty_response(
            query_id, query_text,
            "知识库中未找到与该问题相关的资料。",
            diagnostic,
        )

    # ----- Stage 2: RRF fusion -----
    fused = rrf_module.fuse(sparse_hits, dense_hits, top_n=FUSION_TOP_K)
    diagnostic["fused_count"] = len(fused)

    # ----- Hydrate fused ids with parent + document metadata -----
    rerank_inputs = _hydrate(fused)
    if not rerank_inputs:
        latency_ms = int((time.monotonic() - started) * 1000)
        _write_query_log(
            query_id, query_text, hyde_text, filters,
            top_evidence_ids=[], top_score=0.0, level="low",
            insufficient=True, sparse_n=len(sparse_hits), dense_n=len(dense_hits),
            strategy=diagnostic["rerank_strategy"], latency_ms=latency_ms,
        )
        return _empty_response(
            query_id, query_text,
            "知识库中未找到与该问题相关的资料。",
            diagnostic,
        )

    # ----- Stage 3: rerank -----
    # Rerank the full fused candidate set so the parent-dedup step below has
    # a real choice — truncating to top_k *before* dedup would just throw
    # away the alternative parents we want to surface.
    reranker = rerank_module.get_reranker()
    reranked = reranker.rerank(
        query_text, rerank_inputs, top_k=len(rerank_inputs)
    )

    # The configured strategy may have silently fallen back (e.g. LLM call
    # failed audit / timed out → HeuristicReranker). Each RerankOutput's
    # per-item diagnostic carries the actual strategy that produced its score;
    # promote that to the top-level diagnostic so observability reflects what
    # really ran, not just what was requested.
    if reranked:
        actual_strategy = reranked[0].diagnostic.get("strategy")
        configured = diagnostic.get("rerank_strategy")
        if actual_strategy and actual_strategy != configured:
            diagnostic["rerank_strategy_actual"] = (
                f"{configured}_fallback_{actual_strategy}"
            )

    # ----- Stage 4: parent-level + content-level dedup -----
    # Two flavours of duplicate to suppress:
    #  (a) same parent_chunk, multiple children from sliding-window overlap;
    #  (b) different documents whose parent content is essentially identical
    #      — this happens when the same PDF was uploaded several times during
    #      testing. Both collapse to one card.
    # Per-item floor: drop candidates whose final reranker score falls below
    # INSUFFICIENT_EVIDENCE. The top-level `top_score` gate decides if the
    # query as a whole has any signal; this gate decides which individual
    # cards are worth showing. Without it, LLM rerank's score=0 default for
    # un-scored candidates leaks into top-k and surfaces useless cards.
    rerank_input_by_id = {ri.chunk_id: ri for ri in rerank_inputs}
    seen_parents: set[int] = set()
    seen_content: set[str] = set()
    evidence: list[Evidence] = []
    for r in reranked:
        if r.score < rerank_module.INSUFFICIENT_EVIDENCE:
            continue
        ri = rerank_input_by_id.get(r.chunk_id)
        if ri is None:
            continue
        if ri.parent_id in seen_parents:
            continue
        content_key = _content_dedup_key(ri.parent_content)
        if content_key and content_key in seen_content:
            continue
        seen_parents.add(ri.parent_id)
        if content_key:
            seen_content.add(content_key)
        evidence.append(_build_evidence(r, ri))
        if len(evidence) >= top_k:
            break

    top_score = reranked[0].score if reranked else 0.0
    insufficient = (not evidence) or rerank_module.is_insufficient(top_score)

    # Drop any low-confidence tail when insufficient_evidence is true:
    # the API contract is that we either return useful evidence or signal a miss.
    if insufficient:
        evidence = []

    summary = _build_summary(query_text, evidence)
    boundary = _build_boundary_statement(insufficient)
    flags = {"insufficient_evidence": insufficient}

    latency_ms = int((time.monotonic() - started) * 1000)
    diagnostic["latency_ms"] = latency_ms
    diagnostic["top_score"] = round(top_score, 4)
    diagnostic["returned"] = len(evidence)

    _write_query_log(
        query_id, query_text, hyde_text, filters,
        top_evidence_ids=[e.evidence_id for e in evidence],
        top_score=top_score,
        level=evidence[0].confidence_level if evidence else "low",
        insufficient=insufficient,
        sparse_n=len(sparse_hits),
        dense_n=len(dense_hits),
        strategy=diagnostic["rerank_strategy"],
        latency_ms=latency_ms,
    )

    return QueryResponse(
        query_id=query_id,
        query_text=query_text,
        summary=summary,
        relevant_evidence=evidence,
        evidence_boundary_statement=boundary,
        flags=flags,
        diagnostic=diagnostic,
    )


# ---------- Hydration ----------

def _hydrate(fused: list) -> list:
    """Join fused chunk_ids with parent + document rows, returning RerankInputs.

    One SQL round-trip with IN (...) and a Python-side merge keeps this O(N)
    instead of N+1 queries. Order is preserved to match `fused`.
    """
    if not fused:
        return []

    chunk_ids = [c.chunk_id for c in fused]
    placeholders = ",".join("?" * len(chunk_ids))
    sql = f"""
        SELECT cc.id AS chunk_id,
               cc.content AS child_content,
               pc.id AS parent_id,
               pc.content AS parent_content,
               pc.section_path AS section_path,
               pc.locator AS locator,
               d.id AS document_id,
               d.filename AS filename,
               d.source_type AS source_type,
               d.source_scope AS source_scope,
               d.meta_json AS doc_meta
        FROM child_chunk cc
        JOIN parent_chunk pc ON pc.id = cc.parent_id
        JOIN document d ON d.id = cc.document_id
        WHERE cc.id IN ({placeholders})
          AND cc.archived_at IS NULL
          AND pc.archived_at IS NULL
          AND d.archived_at IS NULL
    """
    with db.connect() as conn:
        rows = conn.execute(sql, chunk_ids).fetchall()

    by_id = {r["chunk_id"]: r for r in rows}

    inputs = []
    for cand in fused:
        row = by_id.get(cand.chunk_id)
        if row is None:
            continue  # archived between recall and hydrate
        parent_content = row["parent_content"] or ""
        inputs.append(rerank_module.RerankInput(
            chunk_id=cand.chunk_id,
            parent_id=row["parent_id"],
            rrf_score=cand.rrf_score,
            sparse_score=cand.sparse_score,
            dense_score=cand.dense_score,
            sources=cand.sources,
            child_content=row["child_content"] or "",
            parent_content=parent_content,
            section_path=row["section_path"] or "",
            locator=row["locator"] or "",
            filename=row["filename"] or "",
            source_scope=row["source_scope"] or "tenant_private",
            is_toc=_looks_like_toc(parent_content),
        ))

    return inputs


_WHITESPACE_RUN = re.compile(r"\s+")


def _content_dedup_key(content: str) -> str:
    """Normalized prefix used to spot near-identical parent content across
    documents. We collapse whitespace and take the first 160 characters so
    duplicate PDF uploads (different document_id, same body) get suppressed.
    """
    if not content:
        return ""
    normalized = _WHITESPACE_RUN.sub(" ", content).strip()
    return normalized[:160]


_TOC_DOT_RUN = re.compile(r"[\.·•…]{3,}")
_TOC_LEADER_LINE = re.compile(
    r"\S[^\n]*?[\.·•…\s]{3,}[0-9IVXLCDM]+\s*$",
    re.MULTILINE,
)


def _looks_like_toc(content: str) -> bool:
    """Detect table-of-contents pages by structural signals.

    Three independent checks; any one is enough:
      1. The Chinese "目录" / "目 录" marker appears in the first 60 chars.
      2. Three or more runs of dotted-leader characters (regular dots, the
         middle-dot ·, the bullet •, or the Unicode ellipsis …).
      3. Three or more lines that end with a roman/arabic page number after
         dotted-or-spacey leader (catches the case where the PDF extractor
         drops the dots but preserves the layout).
    """
    if not content:
        return False

    head = content[:60]
    if "目录" in head or "目 录" in head:
        return True
    lower_head = head.lower()
    if "contents" in lower_head or "table of contents" in lower_head:
        return True

    if len(_TOC_DOT_RUN.findall(content)) >= 3:
        return True

    if len(_TOC_LEADER_LINE.findall(content)) >= 3:
        return True

    return False


# ---------- Evidence + response shaping ----------

_SCOPE_LABELS = {
    "tenant_private": "私域沉淀",
    "system_builtin": "系统内置",
    "runtime_curated": "运行时整理",
}


def _build_evidence(rerank_out, rerank_in) -> Evidence:
    summary = (rerank_in.child_content or "").strip()
    if len(summary) > CHUNK_SUMMARY_CHARS:
        summary = summary[:CHUNK_SUMMARY_CHARS].rstrip() + "..."

    citation = {
        "source_label": rerank_in.filename,
        "source_scope": rerank_in.source_scope,
        "source_scope_label": _SCOPE_LABELS.get(
            rerank_in.source_scope, rerank_in.source_scope
        ),
        "section_path": rerank_in.section_path or None,
        "locator": rerank_in.locator or None,
    }
    return Evidence(
        evidence_id=rerank_in.chunk_id,
        confidence_score=round(rerank_out.score, 4),
        confidence_level=rerank_out.confidence_level,
        chunk_summary=summary,
        chunk_text=rerank_in.parent_content,
        citation=citation,
        meta={
            "sources": sorted(rerank_in.sources),
            "rrf_score": round(rerank_in.rrf_score, 4),
            "diagnostic": rerank_out.diagnostic,
        },
    )


def _build_summary(query: str, evidence: list[Evidence]) -> str:
    if not evidence:
        return "未找到匹配的知识库资料。"
    top = evidence[0]
    return (
        f"知识库中找到 {len(evidence)} 条与「{query}」相关的资料，"
        f"最相关来源：{top.citation['source_label']}"
        + (f"（{top.citation['section_path']}）" if top.citation.get("section_path") else "")
        + "。"
    )


def _build_boundary_statement(insufficient: bool) -> str:
    if insufficient:
        return "当前知识库中没有足够证据回答该问题。建议补充资料后重试，或参考通用经验作答。"
    return "以下回答完全基于知识库已有的检索证据；如需更多上下文请展开来源。"


def _empty_response(
    query_id: str,
    query_text: str,
    summary: str,
    diagnostic: dict,
) -> QueryResponse:
    return QueryResponse(
        query_id=query_id,
        query_text=query_text,
        summary=summary,
        relevant_evidence=[],
        evidence_boundary_statement=_build_boundary_statement(insufficient=True),
        flags={"insufficient_evidence": True},
        diagnostic=diagnostic,
    )


# ---------- query_log persistence ----------

def _write_query_log(
    query_id: str,
    query_text: str,
    expanded_text: str | None,
    filters: dict | None,
    *,
    top_evidence_ids: list[int],
    top_score: float,
    level: str,
    insufficient: bool,
    sparse_n: int,
    dense_n: int,
    strategy: str,
    latency_ms: int,
) -> None:
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO query_log (
                    query_id, query_text, expanded_text, filters_json,
                    top_evidence_ids, top_score, confidence_level,
                    insufficient_evidence, sparse_recall_count, dense_recall_count,
                    rerank_strategy, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    query_id,
                    query_text,
                    expanded_text,
                    json.dumps(filters or {}, ensure_ascii=False),
                    json.dumps(top_evidence_ids, ensure_ascii=False),
                    float(top_score),
                    level,
                    1 if insufficient else 0,
                    sparse_n,
                    dense_n,
                    strategy,
                    latency_ms,
                    _now_iso(),
                ),
            )
    except Exception as exc:
        # Logging must never break the user's query path.
        logger.warning("query_log insert failed: %s", exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
