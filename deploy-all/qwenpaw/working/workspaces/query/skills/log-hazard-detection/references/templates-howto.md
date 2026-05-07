# Drain3 模板挖掘速记

## Drain3 是什么

Drain3 是 LogPAI 在 [Drain](https://pinjiahe.github.io/papers/ICWS17.pdf) 论文基础上做的在线日志模板挖掘库。核心思想：

1. 把每条日志按空格 + 自定义 delimiter 切 token
2. 在一棵深度受限的解析树里按"长度 → 前缀 → 相似度"路由到一个叶子节点（一个 cluster）
3. 同一 cluster 里所有日志的相同位置 token 保留，不同的 token 替换为通配符 `<*>`，得到稳定模板
4. 数字、IP、UUID 等容易爆的"参数"先被 masking 屏蔽（`<:NUM:>`、`<:IP:>`），让模板更稳定

**优点**：在线（O(1) 单条吸收）、模板稳定、占内存小。
**缺点**：不识别语义；对完全无格式的自由文本（比如混合多语言堆栈）效果一般。

## 本技能的关键参数

`_drain_helper.py::_build_config()` 用的默认配置：

| 配置 | 值 | 含义 |
|------|---|----|
| `drain_sim_th` | 0.4 | 相似度阈值。越低越激进合并；越高模板越细 |
| `drain_depth` | 4 | 解析树深度。3~6 是常见取值 |
| `drain_max_children` | 100 | 每节点最多子节点数 |
| `drain_max_clusters` | 2000 | 全局簇数上限（兜底） |
| `drain_extra_delimiters` | `["_"]` | 把 `_` 也当分词点（默认只按空格） |
| `mask_prefix` / `mask_suffix` | `<:` / `:>` | 占位符前后缀；默认是 `<` / `>` |
| `masking_instructions` | 见下 | masking 顺序：IP → UUID → PATH → HEX → NUM → STR |

## Masking 列表（顺序敏感）

按声明顺序匹配（先匹配的就吃掉了字符），所以：

```python
[
    (r"(\d+\.){3}\d+", "IP"),                    # 必须先于 NUM
    (r"\b[0-9a-fA-F]{8}-...{12}\b", "UUID"),     # 先于 NUM / HEX
    (r"(?:[A-Za-z]:)?[/\\][\w./\\-]{2,}", "PATH"),
    (r"\b0x[0-9a-fA-F]+\b", "HEX"),              # 必须先于 NUM
    (r"\b\d+\b", "NUM"),                         # 兜底
    (r'"(?:[^"\\]|\\.)*"', "STR"),               # 引号字符串
]
```

如果你的日志里有特殊参数想统一屏蔽（比如 trace_id、request_id、k8s pod 名），可以在 `_drain_helper.py::_MASKING_PATTERNS` 加一行，**放在 NUM 之前**。

## 抽样策略

`fit_hits` 不知道总命中数，调用方负责。本技能的 CLI 都做：

1. 默认 `--sample-size 2000`
2. ES 端 `sort=@timestamp desc` 拉最新 2000 条（`tail` 模式）
3. 当 `total > sample_size * 4` 时，自动改成 `function_score{random_score}` 抽样并标记 `auto_sampled=true`，避免最近 2000 条都属于同一种模板（比如某个服务突发刷屏）的偏差
4. 单行喂给 drain3 之前截到 `--max-line-len`（默认 4000 字节）

## 调参经验

| 现象 | 怎么调 |
|------|------|
| 模板太多（200+ 都不像同义） | 降 `drain_sim_th` 到 0.3；提高 `drain_depth` 到 5 |
| 不同语义被合并到一个模板 | 提高 `drain_sim_th` 到 0.5~0.6 |
| 数字串没被合并（比如 token 串） | 加一条 masking 在 NUM 前 |
| `<*>` 太多，模板像 `* * <*> from <*>` | 加 `drain_extra_delimiters`，或检查日志是不是过短 |
| 某个高频模板永远在 #1，淹没其他 | 用 `--query` 过滤掉它再跑 |

## 内存与超时

- drain3 in-memory，不持久化（`persistence_handler=None`），每次脚本启动都从零 fit
- 实测 5000 条/15min × 4KB/行，drain3 fit 大约 < 3s
- 如果窗口拉到 6h × 命中 10 万+，OOM 风险高；建议：
  - 拉到分钟粒度多次跑
  - 增大 `N9E_LOG_TIMEOUT` 到 90s
  - 降低 `--sample-size` 到 1500

## 升级 `_n9e_client.py`

⚠️ 本技能的 `scripts/_n9e_client.py` 是 nightingale-log 的**物理拷贝**。当 nightingale-log 的客户端修了 bug 或加了新接口：

```bash
cp deploy-all/qwenpaw/working/workspaces/query/skills/nightingale-log/scripts/_n9e_client.py \
   deploy-all/qwenpaw/working/workspaces/query/skills/log-hazard-detection/scripts/_n9e_client.py
cp deploy-all/qwenpaw/working/workspaces/query/skills/nightingale-log/scripts/_n9e_client.py \
   deploy-all/qwenpaw/working/workspaces/query/skills/log-security-scan/scripts/_n9e_client.py
```

然后保留每份副本顶部的 `# COPY OF nightingale-log/scripts/_n9e_client.py — sync manually when upstream changes.` 注释。

不用 symlink 是为了让每个 skill 自包含、能独立分发到 portal/helm 部署里。
