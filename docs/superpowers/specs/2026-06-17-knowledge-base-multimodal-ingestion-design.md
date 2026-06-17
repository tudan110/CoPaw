# 知识库演进 · 多模态入库与检索管线设计

> Spec · 2026-06-17 · 分支 `dev`（知识库技能源码唯一源头在 `deploy-all/qwenpaw/working/workspaces/knowledge/skills/knowledge-base/`）
> 作者：与操作员共同敲定，Opus 4.8
> 状态：**待评审**（设计稿，未实现；评审通过后按 §9 分期落地）

## 1. 背景与目标

当前知识库（`knowledge-base` 技能）能上传 Word / PDF / 图片 / 表格等并做检索，但存在结构性短板：**抽取阶段把一切压扁成纯文本**，导致信息丢失。典型表现：

- Word 内嵌图片的内容**完全丢弃**——`_extract_docx`（`core/ingestion.py:590`）只读 `word/document.xml` 的 `<w:t>` 文本，从不碰 `word/media/`。
- 同一张图，**直接上传**会走 OCR（`_extract_image`，`core/ingestion.py:827`，`pytesseract` + `chi_sim+eng`）进库；**嵌在 Word 里**则被忽略。这是个割裂的体验。
- 复杂 PDF（扫描页、多栏、表格、图文混排）只走纯文本抽取，版面与表格结构丢失。
- 大文件入库会 OOM——`parse_uploaded_file`（`server.py:88-107`）用 stdlib `email` 解析器，一个文件在内存里同时存在 3~4 份拷贝；`MAX_UPLOAD_BYTES` 默认 200MB（`server.py:38`）与 2G 内存的部署 pod 不匹配。
- **前提性问题**：部署机上 dense embedding 实际是关的（`_is_embedding_enabled`，`server.py:781`，依赖 `DASHSCOPE_API_KEY`），意味着 prod 当前很可能是纯 BM25 关键词检索，语义召回未生效。

**目标**：让知识库演进为一条**可扩展、可度量、离线可用**的多模态入库与检索管线——完整读取 Word（含内嵌图）、正确解析复杂 PDF 与混合材料，并被准确检索。

**非目标**：不追求对任意材料 100% 正确（手写体、复杂嵌套表、图表数值精读等仍是已知边界，见 §10），而是用「管线 + 评测闭环」持续逼近。

## 2. 现状盘点

| 模块 | 现状 | 评价 |
| --- | --- | --- |
| 抽取 `extract()` `ingestion.py:131` | 按扩展名分发到 `_extract_pdf/docx/pptx/xlsx/xls/csv/image/email/text`，各自吐 `str` | **核心短板**：输出纯文本，图片/表格结构/版面丢失 |
| 切片 | parent/child 两级（`parent_count`/`child_count`） | 架子可用，但按 token 切、非结构感知 |
| 嵌入 `providers/embedding.py` | DashScope `text-embedding-v4`，1024 维，依赖 `DASHSCOPE_API_KEY`，可关 | 可用，但 **prod 实际关闭** |
| 检索 `core/retrieval.py` | 3 段式：hybrid 召回（BM25 `recall_sparse` + 向量 `recall_dense`/sqlite-vec）→ RRF 融合（`fusion.py`）→ LLM 重排（`rerank.py`）+ HyDE + 多意图 query 变体 | **已较强**，增量优化即可 |
| 存储 | sqlite + sqlite-vec（`core/db.py`） | 够用 |
| 上传 `server.py:72` | stdlib `email` multipart 解析，全量入内存 | **内存放大 / OOM 风险** |
| LLM `providers/llm.py` | 文本 LLM（重排 / HyDE / 合成） | 复用，承担管线里所有「文本智能」 |

**结论**：检索侧已不弱，真正的杠杆在**抽取前端**与**两个前提**（prod embedding、内存/OOM）。

## 3. 核心架构决策

| # | 决策 | 取舍 |
| --- | --- | --- |
| D1 | 引入**归一化中间表示（IR）**：解析器输出结构化 block 列表，而非 `str`，把「解析」与「切片/嵌入」解耦 | 新增格式只写一个「X→IR」解析器，不动下游；信息不再在抽取阶段被压扁 |
| D2 | **两层分类路由**：L1 容器类型（真实嗅探非扩展名）+ L2 内容类型（每页/每区域：数字文本/扫描/表格/图） | 「不同地方不同处理」，复杂 PDF 才能逐区域分流 |
| D3 | **OCR 与 VLM 分离**：图里的「字」靠 OCR（无需任何 LLM）；图的「语义」靠 VLM（可选档） | 必做的 90% 零 VLM 依赖；文本 LLM 看不到像素，不强求 |
| D4 | **拆分重解析 worker 与查询服务进程** | 解析侧吃内存/依赖独立部署，查询 pod 保持精简；顺手根治 OOM |
| D5 | **评测闭环先行**：gold 问题→期望证据集，每次改解析/切片/检索跑回归 | 「完美正确」可度量、防回退 |
| D6 | **离线优先、外部 API 可降级**：OCR/VLM/嵌入权重烧镜像，外部服务一律可选 | 对齐部署纪律（依赖烧镜像、离线） |

## 4. 模型与算力前提（操作员已确认）

- 部署环境**可切换网络**，**有 GPU 时优先用 GPU**。
- 当前**只有文本 LLM**（如 GLM 5.1 / DeepSeek v4 pro），**没有 VLM**。
- **关键事实**：纯文本 LLM 看不到图片像素，无法做图表语义描述——这是能力边界不是质量问题。因此：

| 需求 | 依赖 | 现状可行性 |
| --- | --- | --- |
| 图里的**字**（扫描件/截图/表格图/盖章件） | OCR（纯 CV，不用 LLM） | ✅ 大头，立即可做 |
| 图的**语义**（折线图结论、架构图拓扑） | **VLM** | ❌ 文本 LLM 做不了，列为**可选档** |
| 重排 / HyDE / 表格文本清洗 / 答案合成 | 文本 LLM | ✅ GLM/DeepSeek 正好胜任 |

- VLM 档要做时，**不要用聊天 LLM 的文本版**，单独挂开源 VLM（推荐 **Qwen2.5-VL 7B**，权重开放、单卡 GPU 可离线），与聊天 LLM 解耦。

## 5. 详细设计

### 5.1 归一化中间表示（IR）

每个解析器产出 `list[Block]`：

```python
@dataclass
class Block:
    type: str            # heading|paragraph|list|table|image|formula|code
    text: str            # 文本 / 表格的 Markdown / 图片的 OCR+caption
    level: int | None    # 标题层级
    page: int | None     # 来源页
    bbox: tuple | None   # 版面坐标（PDF）
    heading_path: list[str]   # 所在标题路径，如 ["第3章","3.2 告警策略"]
    origin: str | None   # 溯源，如 "word/media/image5.png"
    meta: dict           # 扩展（表格行列数、图片尺寸、OCR 置信度…）
```

`extract()` 改为返回 `ExtractedDocument(blocks=[...])`；现有 `content: str` 由 `blocks` 渲染成 Markdown 兜底，保证下游平滑过渡（P0 阶段行为不变）。

### 5.2 两层分类与路由

**L1 容器类型**（强化 `ingestion.py:163` 现有 magic-byte 嗅探）：office-zip / pdf / image / email / 表格 / 纯文本 / 压缩包 → 对应解析器。

**L2 内容类型**（每页/每区域分类，PDF 尤其需要）：
- 数字原生文本 → 直接取（保多栏阅读顺序、标题层级）
- 扫描页 / 无文本层 → OCR
- 表格区域 → 表格结构化
- 图片 / 图表 → OCR + 可选 VLM caption
- 公式 → 可选 LaTeX 识别

### 5.3 各模态解析器（→ IR）

- **docx / pptx（含内嵌图）**：解 zip，正文走现有 XML 解析；同时遍历 `word/media/*`（pptx 为 `ppt/media/*`）+ 解析 `*.rels` 关系，**按图片在正文被引用的位置插入 `image` block**，走 §5.4 图片管线。直接解决「完整 Word」。
- **PDF**：版面解析（选型见 §8），按 L2 逐页分流；扫描页 OCR，表格结构化，图文按版面还原顺序。
- **image**：复用现有 OCR，升级引擎（§8）。
- **表格（xlsx/xls/csv 及文档内嵌表）**：转 Markdown/HTML 保行列，整表作为一个 `table` block。
- **混合材料**：IR 天然统一，无需特判。

### 5.4 富化层

- **OCR**：RapidOCR（离线 onnx，中文优于 tesseract），统一服务于「直接上传的图」与「文档内嵌图」。输出带置信度，低于阈值标 warning。
- **VLM caption（可选档，D3/§4）**：装了/能调才富化图表语义，否则跳过加 warning——**绝不因一张图 OCR/caption 失败让整篇入库失败**。
- **表格结构化**：保结构 + 生成一句表摘要（标题+列名）单独成块，提升「表里 X 是多少」类检索命中。
- **降级原则**：富化全部 best-effort，缺依赖即跳过并记 warning。

### 5.5 切片与嵌入

- **结构感知切片**：沿 IR 的标题/段落/表格边界切，不在 token 边界硬切；每 chunk 带 `heading_path` 元数据。
- 表格块、图片块**各自成 chunk**，不与正文混切。
- 图片块用其 caption/OCR 文本走现有文本嵌入（稳妥）；算力够再上多模态向量。
- **元数据索引**：类型（表/图/正文）、来源层级、标题路径，支撑检索过滤。

### 5.6 检索增量（已强，小修）

- **元数据过滤**：按类型 / 标题路径 / 来源层级。
- **query routing**：表格类问题优先表块。
- 保留现有 RRF + LLM 重排 + HyDE。
- **前提**：先打通 prod dense embedding（§6.4），否则以上皆空转。

## 6. 工程与部署

### 6.1 拆分 ingestion worker 与查询服务
重解析（OCR/VLM/版面模型，吃内存与依赖）独立部署、给高内存；查询 pod 保持精简 2G。沿用现有异步 job + 线程池（`server.py:65`），把执行体迁到独立 worker 部署。**同时根治 174MB 文档 OOM。**

### 6.2 multipart 流式落盘
重写 `parse_uploaded_file`（`server.py:72`）：不用 stdlib `email` 整块解析，改流式读 body 落临时文件，解析器从文件路径读，**内存与文件大小脱钩**。

### 6.3 离线与依赖
OCR（RapidOCR onnx）、版面/VLM 权重全烧镜像；外部 API 一律可选可降级。对齐部署纪律。

### 6.4 打通 prod embedding（前置）
要么放通到 DashScope 的 egress，要么内网自托管嵌入模型（bge-m3 / Qwen3-Embedding，GPU；走 `local_models` 栈）。**不做这步，语义检索一直瘸。**

## 7. 评测闭环

建 **KB 评测集**：gold「问题 → 期望命中证据 chunk」。每次改解析/切片/检索跑回归，盯 **recall@k / 证据命中率 / 答案正确率**。无此闭环则「完美正确」既验证不了也会悄悄回退。复用大屏既有评测基线经验。

## 8. 选型小抄

| 能力 | 纯离线·CPU 首选 | 有 GPU/外网时更强 |
| --- | --- | --- |
| PDF 版面+图片抽取 | PyMuPDF（快、省内存，**AGPL ⚠️**）/ pdfplumber（MIT，慢） | docling（IBM，Apache-2，版面+表格+OCR 一体） |
| OCR | **RapidOCR**（onnx，中文强） | PaddleOCR |
| 图表理解（可选档） | —（文本 LLM 做不了） | **Qwen2.5-VL 7B**（开源，单卡，离线） |
| 嵌入 | 自托管 bge-m3 / Qwen3-Embedding（GPU） | DashScope text-embedding-v4（现有，需 egress） |

> ⚠️ **许可证**：QwenPaw 开源上 PyPI，**PyMuPDF 为 AGPL**，可能污染分发许可。选型须确认，或改用 MIT 的 pdfplumber。

## 9. 分期路线（映射代码）

| 阶段 | 内容 | 见效 |
| --- | --- | --- |
| **P0 地基** | multipart 流式落盘 + 拆 worker（治 OOM）；打通 prod embedding；各 extractor 重构为输出 IR（行为不变）；搭最小评测集 | 稳定性 + 可度量 |
| **P1 Office 多模态** | docx/pptx 内嵌图抽取 + OCR（换 RapidOCR）；表格结构化 | **「完整 Word」达成，最快见效** |
| **P2 复杂 PDF** | 版面解析 + 扫描页 OCR + 表格/多栏/图文 | 复杂 PDF 入库 |
| **P3 语义富化 + 检索增量** | 图表 VLM caption（可选，需 Qwen2.5-VL）；元数据过滤；query routing；多向量 | 检索精度上台阶 |

每阶段收口都过评测集。

## 10. 已知边界与风险

不承诺 100%，以下场景即便全做完仍会丢分，预留人工兜底：手写体；复杂嵌套/合并单元格表；需「读懂图表数值」的精读；跨页续表；纯装饰图的 OCR 噪声（按像素尺寸过滤小图缓解）。把它们当「已知边界 + 缓解项」而非假装能解。

**风险**：①富化拖慢入库——靠 worker 拆分 + 限张数/限尺寸；②依赖膨胀与离线镜像体积——onnx/VLM 权重显著增大镜像，需评估；③许可证（§8 ⚠️）。

## 11. 三根柱子

整套方案的灵魂：**IR 解耦**（扩展性）、**两层分类路由**（分而治之）、**评测闭环**（让「完美」可验证）。其余能力都往这三根柱子上挂。
