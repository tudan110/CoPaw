# 技能（SKILL.md）写作规范

> 目的：减少智能体**选错工具 / 反复换工具 / 用 shell 硬凑**。清晰、边界明确、
> 可被路由命中的技能描述，是压测里"无效调用"的根治手段之一（L2）。
> 配套校验器：`scripts/check_skill_quality.py`（CI 可用，见文末）。

## 1. Frontmatter 必填 / 建议字段

| 字段 | 要求 | 说明 |
|---|---|---|
| `name` | **必填**，且**必须等于目录名** | 不一致会导致注册/引用错乱（ERROR） |
| `description` | **必填**，≥ 40 字符 | 说清**何时用**，并声明**边界**（见 §2） |
| `triggers` | **强烈建议**（列表） | 明确触发短语，让路由/选择确定化；缺失＝易选错（WARN） |
| `category` | 建议 | 领域分组（如 `asset`/`alarm`/`query`） |
| `tags` | 建议 | 关键词，辅助检索 |

## 2. description 必须含"边界声明"

大多数"选错工具"源于相邻技能领域重叠。description 或正文要**显式划清边界**，
指明相邻场景该用哪个技能。例：

> 查询 INOE 资源状态与性能数据。适用于设备状态统计、资源性能 Top…。
> **告警列表/统计继续使用 `real-alarm`；CMDB 模型/关系/count 使用 `zgops-cmdb`。**

判定线索（校验器识别其一即算有边界声明）：`继续使用` / `而非` / `不用于` /
`请使用` / `改用`，或正文点名了另一个技能。

## 3. 脚本类技能必须有"自然语言映射"

若技能带 `scripts/`（靠 `execute_shell_command` 跑脚本），SKILL.md 必须给出
**自然语言 → 具体命令**的映射，覆盖常见问法，避免模型猜命令、猜参数、瞎试。
至少包含一节 `## 自然语言映射` 或等价的 ```bash 用法示例。例：

```
## 自然语言映射
- "主机磁盘使用率排行 / 超阈值主机" → top-metric --resource_type host --order_code diskRate [--min_rate 80]
```

## 4. 查询类技能的运行时约定（详见 L2b）

- **结构化返回**：稳定字段，便于模型解析、避免二次加工。
- **支持过滤/阈值参数**：如 `--min_rate`，一次到位，杜绝"取回→自筛→空→重试"。
- **空结果给明确信号**：返回如 `{"code":200,"data":[],"empty":true,"reason":"..."}`
  或明确文案「未查询到」，**不要返回空串**——空串会诱发模型重试。

## 5. 多副本一致性

同一技能若存在于多个 workspace（如 `query`/`gateway`/`resource` 各一份），
各副本的 SKILL.md 与脚本**必须保持一致**，改动要同步所有副本（校验器会报 divergence）。

## 校验

```bash
.venv/bin/python scripts/check_skill_quality.py            # 全量
.venv/bin/python scripts/check_skill_quality.py --workspace resource
.venv/bin/python scripts/check_skill_quality.py --json     # 机器可读(供 L3 分诊)
```
有 ERROR 时退出码非 0，可接入 CI。WARN/INFO 仅提示。
