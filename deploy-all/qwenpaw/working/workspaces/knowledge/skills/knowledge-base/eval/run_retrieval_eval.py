"""End-to-end retrieval eval against a throwaway temp knowledge base.

Ingests the synthetic gold documents into a temp DB, runs the gold questions
through `retrieval.query` (HyDE disabled so no LLM is needed), and reports
recall@k / evidence-hit. Runs offline: when no embedding key is configured it
degrades to BM25-only — the table-cell questions still prove that docx table
content reaches retrieval.

    python eval/run_retrieval_eval.py            # default top_k=5

Set DASHSCOPE_API_KEY first for the full hybrid (dense+sparse) signal.
Exit code is non-zero if recall falls below the threshold, so this can gate CI.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_EVAL_DIR)
for _p in (_SKILL_ROOT, _EVAL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TOP_K = int(os.environ.get("KB_EVAL_TOP_K", "5"))
PASS_THRESHOLD = float(os.environ.get("KB_EVAL_THRESHOLD", "0.8"))


def _load_questions() -> list[dict]:
    path = os.path.join(_EVAL_DIR, "gold_questions.jsonl")
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> int:
    # Point the skill at an isolated temp data dir BEFORE importing db/ingestion.
    tmp_dir = tempfile.mkdtemp(prefix="kb-eval-")
    os.environ["KNOWLEDGE_BASE_DATA_DIR"] = tmp_dir
    # HyDE off by default for an LLM-free run; honor an explicit override.
    os.environ.setdefault("KNOWLEDGE_BASE_HYDE_ENABLED", "false")

    from core import db, ingestion  # noqa: E402
    from core import retrieval  # noqa: E402
    import gold_docs  # noqa: E402

    db.init_db()
    embed_on = ingestion.embedding.is_available()
    print(f"data dir : {tmp_dir}")
    print(f"embedding: {'on (hybrid)' if embed_on else 'off (BM25-only)'}")
    print(f"top_k    : {TOP_K}\n")

    print("Ingesting gold documents:")
    for filename, content in gold_docs.gold_documents():
        result = ingestion.ingest_file(filename, content, source_type="eval")
        print(f"  {filename}: {result.parent_count} parents / "
              f"{result.child_count} children")

    questions = _load_questions()
    hits = 0
    print("\nRunning queries:")
    for item in questions:
        q = item["q"]
        expected = item.get("expect_any", [])
        try:
            resp = retrieval.query(q, top_k=TOP_K, enable_hyde=False)
            blob = "\n".join(e.chunk_text for e in resp.relevant_evidence)
        except Exception as exc:  # noqa: BLE001 - report, don't abort the run
            print(f"  MISS  {q}  (query error: {exc})")
            continue
        ok = any(token in blob for token in expected)
        hits += 1 if ok else 0
        print(f"  {'HIT ' if ok else 'MISS'}  {q}  -> expect any {expected}")

    total = len(questions)
    recall = hits / total if total else 0.0
    print(f"\nrecall@{TOP_K} = {hits}/{total} = {recall:.2f} "
          f"(threshold {PASS_THRESHOLD:.2f})")
    if recall < PASS_THRESHOLD:
        print("RESULT: BELOW THRESHOLD")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
