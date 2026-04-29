---
name: knowledge-base
description: 运维知识库能力。用于知识资料上传入库、手动沉淀、资料管理、关键词/向量混合检索、基于检索证据回答知识问题。用户询问知识库、SOP、历史案例、最佳实践、故障经验、资料检索、文档上传或知识沉淀时使用。
---

# Knowledge Base

这是知识专员的主知识库能力，替代旧 demo `rag-skill`。

## 使用边界

- 默认只服务 `knowledge` 智能体，不作为 gateway 的全局隐式检索中间件。
- 其他智能体需要 SOP、历史案例、最佳实践、故障经验时，应协同 `knowledge`，由 `knowledge` 使用本 skill 检索。
- 不要在普通查询、实时告警、工单列表、CMDB 状态查询前自动检索知识库。

## 数据与配置

- 内嵌到 QwenPaw skill 的知识库引擎，不需要单独部署原项目服务，也不通过反向代理嫁接。
- 数据默认存放在本 skill 的 `data/` 目录；容器部署可设置 `KNOWLEDGE_BASE_DATA_DIR` 或 `QWENPAW_KNOWLEDGE_BASE_DATA_DIR` 到 PVC 路径。
- `DASHSCOPE_API_KEY` 用于 embedding（DashScope `text-embedding-v4`），同一个 key 未来可复用 reranker。
- `DEEPSEEK_API_KEY` 用于 HyDE 查询改写和 RAG 答案合成；缺失时自动降级。
- `KNOWLEDGE_BASE_RERANKER` 可选 `none` / `heuristic`(默认) / `llm` / `cross_encoder`(占位)。
- `KNOWLEDGE_BASE_HYDE_ENABLED` 默认 `true`，设 `false` 关闭。

## 架构（v1, 2026-04 重写）

```
core/db.py             SQLite + sqlite-vec + FTS5 模式
core/chunking.py       token-aware 递归切块 + Markdown 层级
core/ingestion.py      抽取 → 切块 → 嵌入 → 持久化
core/retrieval.py      三阶段检索编排器 + query_log
retrieval/             召回(BM25 / vec0) + RRF 融合 + 重排
providers/             DashScope embedding / DeepSeek LLM 客户端
domain/                同义词字典 + HyDE
api/serializers.py     输出形状对齐 portal 前端契约
server.py              HTTP 路由薄壳（18 个端点）
```

## 启动

```bash
cd skills/knowledge-base
pip install -r requirements.txt
python3 server.py        # 默认 127.0.0.1:8765
```

环境变量覆盖：`KNOWLEDGE_BASE_HOST`、`KNOWLEDGE_BASE_PORT`。

## 常用调试

```bash
# 健康
curl http://127.0.0.1:8765/knowledge-base/health

# 检索
curl -X POST http://127.0.0.1:8765/knowledge-base/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"数据库慢查询怎么处置"}'

# 手动沉淀
curl -X POST http://127.0.0.1:8765/knowledge-base/manual-entry \
  -H 'Content-Type: application/json' \
  -d '{"title":"慢查询处置原则","content":"…","tags":["db"]}'

# 上传文件
curl -X POST http://127.0.0.1:8765/knowledge-base/ingest \
  -F 'file=@/path/to/file.md'

# 资料列表
curl 'http://127.0.0.1:8765/knowledge-base/sources?limit=20'
```

## 回答要求

- 先检索，再回答；不要凭空编造知识库中不存在的结论。
- 回答中说明命中的来源文件、标题或 locator。
- 如果没有命中，明确说明“当前知识库未找到匹配资料”，再给出可选的通用建议或让用户补充资料。
