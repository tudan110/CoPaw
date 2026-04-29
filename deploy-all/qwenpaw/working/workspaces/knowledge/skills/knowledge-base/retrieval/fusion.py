"""Reciprocal Rank Fusion — merge sparse + dense rankings without tuning."""

from __future__ import annotations

from dataclasses import dataclass


RRF_K = 60  # canonical default; tunable but rarely needs changing


@dataclass
class FusedCandidate:
    chunk_id: int
    rrf_score: float
    sources: set[str]                     # {"sparse"}, {"dense"}, or both
    sparse_score: float | None = None
    dense_score: float | None = None
    sparse_rank: int | None = None
    dense_rank: int | None = None


def fuse(
    sparse: list[tuple[int, float, int]],
    dense: list[tuple[int, float, int]],
    *,
    k: int = RRF_K,
    top_n: int | None = None,
) -> list[FusedCandidate]:
    """Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank_i(d)).

    Parameters are (chunk_id, normalized_score, rank) tuples from each recall
    stage; ranks are 0-indexed. Output is sorted by rrf_score descending.
    """
    by_id: dict[int, FusedCandidate] = {}

    for chunk_id, score, rank in sparse:
        cand = by_id.get(chunk_id)
        if cand is None:
            cand = FusedCandidate(chunk_id=chunk_id, rrf_score=0.0, sources=set())
            by_id[chunk_id] = cand
        cand.rrf_score += 1.0 / (k + rank + 1)
        cand.sources.add("sparse")
        cand.sparse_score = score
        cand.sparse_rank = rank

    for chunk_id, score, rank in dense:
        cand = by_id.get(chunk_id)
        if cand is None:
            cand = FusedCandidate(chunk_id=chunk_id, rrf_score=0.0, sources=set())
            by_id[chunk_id] = cand
        cand.rrf_score += 1.0 / (k + rank + 1)
        cand.sources.add("dense")
        cand.dense_score = score
        cand.dense_rank = rank

    fused = sorted(by_id.values(), key=lambda c: c.rrf_score, reverse=True)
    return fused[:top_n] if top_n else fused
