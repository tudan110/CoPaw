"""Query expansion: domain synonyms + HyDE.

Synonym groups are domain-specific (telecom + ops). Add a new group when you
notice queries failing because of vocabulary mismatch — a new entry is much
cheaper than retraining anything.

HyDE (Hypothetical Document Embeddings) generates a plausible answer text and
embeds *that* instead of the literal query. Useful for short / ambiguous
questions where the query embedding is too coarse.
"""

from __future__ import annotations

import logging

from providers import llm


logger = logging.getLogger(__name__)


# Each set is one equivalence class. If any member appears in the query, all
# other members get registered as variant queries.
SYNONYM_GROUPS: list[set[str]] = [
    {"中国电信", "电信", "CT"},
    {"大模型", "大模型能力", "模型能力", "人工智能", "AI", "ai"},
    {"智能体", "agent", "Agent"},
    {"知识库", "知识专员"},
    {"运维", "智观"},
    {"故障", "异常", "事件"},
    {"工单", "派单", "单据"},
    {"告警", "报警", "alert"},
]


HYDE_SYSTEM_PROMPT = (
    "你是运维知识库的检索助手。给定一个问题，输出一段约 80-150 字的假设答案。"
    "假设答案需要包含问题可能涉及的关键技术名词、典型场景、处置步骤。"
    "直接输出答案文本，不要加任何解释或前后缀。"
)


def expand_with_synonyms(query: str) -> list[str]:
    """Return the original query plus rewrites where any matched term is
    swapped for each synonym in its group. Order: original first, then variants
    in declaration order — caller may treat the head as primary."""
    if not query or not query.strip():
        return []

    variants = [query]
    seen = {query}

    for group in SYNONYM_GROUPS:
        members = sorted(group, key=len, reverse=True)  # longest match first
        for present in members:
            if present in query:
                for alt in members:
                    if alt == present:
                        continue
                    rewritten = query.replace(present, alt)
                    if rewritten not in seen:
                        seen.add(rewritten)
                        variants.append(rewritten)
                break  # only one substitution per group per query

    return variants


def generate_hyde(
    query: str,
    *,
    timeout_s: float = 8.0,
    request_id: str = "hyde",
) -> str | None:
    """Synthesize a hypothetical answer for the query. Returns None on failure
    so callers can fall back to literal-query embedding."""
    if not query or not query.strip():
        return None
    if not llm.is_available("deepseek"):
        return None

    try:
        result = llm.call_llm(
            "deepseek",
            messages=[
                {"role": "system", "content": HYDE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            timeout_s=timeout_s,
            request_id=request_id,
        )
    except llm.LLMError as exc:
        logger.warning("hyde generation failed: %s", exc)
        return None

    answer = (result.get("answer") or "").strip()
    return answer or None
