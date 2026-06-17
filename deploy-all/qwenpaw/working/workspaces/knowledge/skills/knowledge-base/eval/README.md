# 知识库评测 (eval)

最小评测闭环，用于在改动抽取 / 切片 / 检索后跑回归，防止"完美检索"悄悄退化。
对应设计文档 `docs/superpowers/specs/2026-06-17-knowledge-base-multimodal-ingestion-design.md` §7。

两层，从快到慢：

## 1. 抽取回归（离线，秒级）

```bash
python eval/extraction_cases.py
```

不依赖 DB / 嵌入 / LLM。用合成 docx/pptx/markdown 断言 IR 抽取正确：
标题层级、段落、**表格转 Markdown（此前被完全丢弃）**、内嵌图 OCR 路径优雅降级。
退出码非 0 即失败，可直接做 CI 闸。

## 2. 检索评测（端到端，临时库）

```bash
python eval/run_retrieval_eval.py            # 默认 top_k=5，阈值 0.8
DASHSCOPE_API_KEY=sk-xxx python eval/run_retrieval_eval.py   # 启用 dense 混合检索
```

把 `gold_docs.py` 的合成文档灌进一个**临时数据目录**（不污染生产库），
按 `gold_questions.jsonl` 跑查询，报 recall@k。HyDE 关闭故无需 LLM；
未配嵌入时退化为 BM25-only —— 表格类问题（如"工单总数 2299"）仍能命中，
证明 docx 表格内容确实进入了检索。

环境变量：`KB_EVAL_TOP_K`、`KB_EVAL_THRESHOLD`。退出码非 0 表示低于阈值。

## 文件

- `gold_docs.py` —— 合成 gold 文档（内存构造，不提交二进制）。
- `gold_questions.jsonl` —— 每行 `{q, expect_any, doc}`：问题、期望命中的任一子串、来源文档。
- `extraction_cases.py` —— 抽取层断言。
- `run_retrieval_eval.py` —— 检索层评测。

## 扩展

要覆盖新场景（扫描 PDF、复杂表、跨页续表、图表语义），在 `gold_docs.py`
加构造器、在 `gold_questions.jsonl` 加问题即可。真实文档可放 `eval/gold/`
（建议 .gitignore 大文件，用小样本）。
