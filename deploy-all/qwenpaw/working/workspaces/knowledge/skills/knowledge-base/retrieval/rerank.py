"""Reranker layer with pluggable strategies.

Today's default is HeuristicReranker (no extra network call). LLMReranker is
opt-in via env var. CrossEncoderReranker is a stub waiting for a hosted
cross-encoder (e.g. DashScope gte-rerank-v2) to be wired in.

Confidence calibration lives here too — it consumes the reranker output and
maps to "high" / "medium" / "low" levels that the API contract exposes.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Protocol

from providers import llm


logger = logging.getLogger(__name__)


# Confidence thresholds (operate on the reranker's final 0..1 score).
CONFIDENCE_HIGH = 0.65
CONFIDENCE_MEDIUM = 0.40
INSUFFICIENT_EVIDENCE = 0.20


@dataclass
class RerankInput:
    """One candidate flowing into the reranker.

    Built by the orchestrator after RRF fusion + DB hydration; bundles every
    signal a reranker might want to look at.
    """
    chunk_id: int
    parent_id: int
    rrf_score: float
    sparse_score: float | None
    dense_score: float | None
    sources: set[str]
    child_content: str
    parent_content: str
    section_path: str
    locator: str
    filename: str
    source_scope: str
    is_toc: bool = False


@dataclass
class RerankOutput:
    chunk_id: int
    score: float                      # final relevance, 0..1
    confidence_level: str             # "high" | "medium" | "low"
    diagnostic: dict                  # signals that contributed (debugging only)


class Reranker(Protocol):
    """Strategy interface — swap implementations without touching the orchestrator."""

    def rerank(
        self,
        query: str,
        candidates: list[RerankInput],
        *,
        top_k: int,
    ) -> list[RerankOutput]: ...


# ---------- Implementations ----------

class NoReranker:
    """Pass-through: trust RRF order, normalize RRF to [0,1] as the score."""

    def rerank(self, query, candidates, *, top_k):
        if not candidates:
            return []
        rrfs = [c.rrf_score for c in candidates]
        lo, hi = min(rrfs), max(rrfs)
        span = hi - lo or 1.0
        out = []
        for c in candidates[:top_k]:
            score = (c.rrf_score - lo) / span
            out.append(RerankOutput(
                chunk_id=c.chunk_id,
                score=score,
                confidence_level=confidence_level(score),
                diagnostic={"strategy": "none", "rrf_norm": round(score, 4)},
            ))
        return out


class HeuristicReranker:
    """Combine RRF, raw recall scores, source agreement, heading match, and
    metadata-keyword overlap. Cheap, no extra network calls. Default strategy.
    """

    # Linear-combination weights (sum to 1.0)
    W_RRF = 0.45
    W_DENSE = 0.15
    W_SPARSE = 0.08
    W_HEADING = 0.20      # query matches the chunk's heading / section_path
    W_KEYWORD = 0.05
    W_AGREEMENT = 0.05
    W_SCOPE = 0.02

    # Multiplicative penalty for chunks classified as table-of-contents.
    # TOCs naturally have very high BM25 scores (every section title appears
    # once) but are useless as direct evidence — they only point to real
    # content. Halving the score pushes them below the actual answer.
    TOC_PENALTY = 0.5

    def rerank(self, query, candidates, *, top_k):
        if not candidates:
            return []

        rrfs = [c.rrf_score for c in candidates]
        lo, hi = min(rrfs), max(rrfs)
        span = hi - lo or 1.0
        query_terms = _meaningful_terms(query)

        scored: list[RerankOutput] = []
        for c in candidates:
            rrf_norm = (c.rrf_score - lo) / span
            dense = c.dense_score or 0.0
            sparse = c.sparse_score or 0.0

            # Cross-modal agreement: when both sparse and dense recall hit, this
            # candidate is likely on-topic for two independent reasons.
            agreement = 1.0 if {"sparse", "dense"} <= c.sources else 0.0

            # Heading match: did the user's query phrase appear in the chunk's
            # section_path (Markdown) or in the leading prose of the content
            # (PDF/plain — headings end up inline)? This is the strongest
            # single signal for "this chunk is *about* the query topic".
            heading = _heading_match_score(query, c.section_path, c.child_content)

            # Looser metadata keyword overlap (filename + section_path).
            metadata_text = f"{c.filename} {c.section_path}".lower()
            keyword = _keyword_overlap(query_terms, metadata_text)

            scope_bonus = 1.0 if c.source_scope == "tenant_private" else 0.5

            raw = (
                self.W_RRF * rrf_norm
                + self.W_DENSE * dense
                + self.W_SPARSE * sparse
                + self.W_HEADING * heading
                + self.W_AGREEMENT * agreement
                + self.W_KEYWORD * keyword
                + self.W_SCOPE * scope_bonus
            )
            score = raw * (self.TOC_PENALTY if c.is_toc else 1.0)
            score = max(0.0, min(1.0, score))

            scored.append(RerankOutput(
                chunk_id=c.chunk_id,
                score=score,
                confidence_level=confidence_level(score),
                diagnostic={
                    "strategy": "heuristic",
                    "rrf_norm": round(rrf_norm, 4),
                    "dense": round(dense, 4),
                    "sparse": round(sparse, 4),
                    "heading": round(heading, 4),
                    "agreement": agreement,
                    "keyword": round(keyword, 4),
                    "scope_bonus": scope_bonus,
                    "toc_penalty": c.is_toc,
                },
            ))

        scored.sort(key=lambda o: o.score, reverse=True)
        return scored[:top_k]


class LLMReranker:
    """Ask an LLM to score each candidate. Costs +1 LLM call per query; output
    is parsed as JSON with regex fallback to handle stray prefixes/suffixes."""

    PROMPT_TEMPLATE = (
        "你是文档相关性评估助手。给定查询和若干候选文档片段，"
        "为每个文档输出与查询的相关性分数 (0.0-1.0)。\n\n"
        "查询: {query}\n\n"
        "候选文档（编号从 0 开始）:\n{docs}\n\n"
        "仅输出 JSON，格式: "
        '{{"scores": [{{"id": 0, "score": 0.85}}, ...]}}\n'
        "不要添加任何解释或前后缀。"
    )

    MAX_PREVIEW_CHARS = int(
        os.environ.get("KNOWLEDGE_BASE_LLM_RERANK_PREVIEW_CHARS", "250")
    )
    TIMEOUT_S = float(
        os.environ.get("KNOWLEDGE_BASE_LLM_RERANK_TIMEOUT", "60.0")
    )

    # Cap how many fused candidates we send to the LLM. The fusion stage hands
    # us up to ~50; passing them all blows the prompt budget and slows the
    # call. The lower-RRF candidates almost never overtake the top after
    # reranking, so trim aggressively.
    #
    # Lower numbers also help with content-audit triggers on providers like
    # Ctyun: "query + many densely-related candidate snippets" can flip
    # aggregate-signal moderation. Smaller batch = smaller surface.
    MAX_INPUT_CANDIDATES = int(
        os.environ.get("KNOWLEDGE_BASE_LLM_RERANK_INPUT_K", "8")
    )

    def rerank(self, query, candidates, *, top_k):
        if not candidates:
            return []
        # Trim to the highest-RRF candidates so we don't pay for the long tail.
        if len(candidates) > self.MAX_INPUT_CANDIDATES:
            candidates = sorted(
                candidates, key=lambda c: c.rrf_score, reverse=True
            )[: self.MAX_INPUT_CANDIDATES]

        # Prefer QwenPaw's active model (already configured in the portal),
        # fall back to DeepSeek if the host process isn't running inside QwenPaw.
        provider = llm.first_available("qwenpaw_active", "deepseek")
        if provider is None:
            logger.warning(
                "LLMReranker: no LLM provider available, falling back to heuristic"
            )
            return HeuristicReranker().rerank(query, candidates, top_k=top_k)

        docs_block = "\n".join(
            f"[{i}] {c.section_path} | {c.child_content[:self.MAX_PREVIEW_CHARS]}"
            for i, c in enumerate(candidates)
        )
        prompt = self.PROMPT_TEMPLATE.format(query=query, docs=docs_block)

        try:
            result = llm.call_llm(
                provider,
                messages=[{"role": "user", "content": prompt}],
                timeout_s=self.TIMEOUT_S,
                request_id="llm-rerank",
            )
        except llm.LLMError as exc:
            logger.warning(
                "LLMReranker call (%s) failed: %s — falling back to heuristic",
                provider, exc,
            )
            return HeuristicReranker().rerank(query, candidates, top_k=top_k)

        scores_by_idx = _parse_llm_scores(result.get("answer", ""), len(candidates))
        if not scores_by_idx:
            logger.warning("LLMReranker: could not parse scores, falling back to heuristic")
            return HeuristicReranker().rerank(query, candidates, top_k=top_k)

        outputs = []
        for i, c in enumerate(candidates):
            score = max(0.0, min(1.0, float(scores_by_idx.get(i, 0.0))))
            outputs.append(RerankOutput(
                chunk_id=c.chunk_id,
                score=score,
                confidence_level=confidence_level(score),
                diagnostic={"strategy": "llm", "raw_score": score},
            ))

        outputs.sort(key=lambda o: o.score, reverse=True)
        return outputs[:top_k]


class CrossEncoderReranker:
    """Future plug-in slot for DashScope gte-rerank-v2 (or equivalent)."""

    def rerank(self, query, candidates, *, top_k):
        raise NotImplementedError(
            "CrossEncoderReranker not connected. Wire DashScope gte-rerank-v2 "
            "in providers/reranker.py and update this class."
        )


# ---------- Factory ----------

def get_reranker() -> Reranker:
    """Pick the configured reranker. Falls back to HeuristicReranker on unknown
    values so a typo never silently disables reranking."""
    mode = os.environ.get("KNOWLEDGE_BASE_RERANKER", "heuristic").lower()
    if mode == "none":
        return NoReranker()
    if mode == "heuristic":
        return HeuristicReranker()
    if mode == "llm":
        return LLMReranker()
    if mode in ("cross_encoder", "cross-encoder"):
        return CrossEncoderReranker()
    logger.warning("unknown KNOWLEDGE_BASE_RERANKER=%r, using heuristic", mode)
    return HeuristicReranker()


# ---------- Confidence calibration ----------

def confidence_level(score: float) -> str:
    if score >= CONFIDENCE_HIGH:
        return "high"
    if score >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


def is_insufficient(top_score: float) -> bool:
    return top_score < INSUFFICIENT_EVIDENCE


# ---------- Helpers ----------

_TERM_RE = re.compile(r"[一-鿿]{2,}|[A-Za-z][A-Za-z0-9]+")

# Single-character / interrogative tokens that aren't useful as topic markers.
# Filtering them stops a query like "目标是什么" from getting credit just because
# every chunk contains the character "是".
_TOPIC_STOPWORDS = frozenset({
    "什么", "怎么", "如何", "哪里", "哪个", "谁", "为什么", "为何",
    "是否", "能否", "可以", "需要", "应该",
    "what", "how", "where", "who", "why", "which", "is", "are", "the", "a", "an",
})


def _meaningful_terms(text: str) -> list[str]:
    """Coarse query terms for keyword-overlap scoring. Matches CJK runs of 2+
    characters and ASCII identifiers; misses single-character CJK by design
    (those are too noisy to reward in metadata matching)."""
    return [t.lower() for t in _TERM_RE.findall(text or "")]


def _keyword_overlap(query_terms: list[str], haystack: str) -> float:
    if not query_terms:
        return 0.0
    hits = sum(1 for t in query_terms if t in haystack)
    return hits / len(query_terms)


def _query_topic_tokens(query: str) -> list[str]:
    """jieba-tokenized query terms, ≥2 chars, with interrogative stopwords
    removed. Falls back to the regex-based extractor when jieba isn't loaded."""
    if not query:
        return []
    try:
        import jieba
        tokens = list(jieba.cut_for_search(query))
    except Exception:
        tokens = _TERM_RE.findall(query)

    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        t = tok.strip().lower()
        if len(t) < 2:
            continue
        if t in _TOPIC_STOPWORDS:
            continue
        if not any(c.isalnum() or "一" <= c <= "鿿" for c in t):
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _heading_match_score(query: str, section_path: str, content: str) -> float:
    """How strongly is the chunk *about* the query topic?

    Two paths:
      - Exact substring of the query in section_path or chunk leading text
        gives full credit (1.0). This catches the easy "the heading literally
        contains the question" case.
      - Otherwise, jieba-segment the query and measure what fraction of those
        terms appear anywhere in section_path + the chunk content. Linear
        ratio — partial coverage gets partial credit.

    The second path is what saves a query like "工业网络安全保护目标是什么？" —
    "保护目标" sits in the chunk body, not in the heading, so substring
    matching alone would miss it.
    """
    if not query:
        return 0.0
    qn = query.lower().strip()
    if not qn:
        return 0.0

    if section_path and qn in section_path.lower():
        return 1.0
    if content and qn in content[:200].lower():
        return 1.0

    q_tokens = _query_topic_tokens(query)
    if not q_tokens:
        return 0.0

    haystack = " ".join(filter(None, [section_path, content])).lower()
    if not haystack:
        return 0.0

    hits = sum(1 for t in q_tokens if t in haystack)
    return hits / len(q_tokens)


_JSON_SCORES_RE = re.compile(
    r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*([0-9.]+)\s*\}'
)


def _parse_llm_scores(text: str, n_candidates: int) -> dict[int, float]:
    """Parse the JSON {"scores": [...]} reply. Falls back to regex extraction
    if the model wrapped the JSON in commentary."""
    text = (text or "").strip()
    if not text:
        return {}

    # Strip code fences if the model wrapped output.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)

    try:
        parsed = json.loads(text)
        scores = parsed.get("scores", [])
        out = {}
        for entry in scores:
            try:
                idx = int(entry["id"])
                if 0 <= idx < n_candidates:
                    out[idx] = float(entry["score"])
            except (KeyError, ValueError, TypeError):
                continue
        if out:
            return out
    except json.JSONDecodeError:
        pass

    # Regex fallback
    out: dict[int, float] = {}
    for m in _JSON_SCORES_RE.finditer(text):
        try:
            idx = int(m.group(1))
            score = float(m.group(2))
            if 0 <= idx < n_candidates:
                out[idx] = score
        except (ValueError, TypeError):
            continue
    return out
