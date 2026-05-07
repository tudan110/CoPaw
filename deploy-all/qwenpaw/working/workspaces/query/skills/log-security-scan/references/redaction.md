# 脱敏算法 + 已知 false-positive 备忘

## 脱敏的硬约束

**展示给用户的 match 字符串永远不是原文。** 三种模式：

| 模式 | 行为 | 示例（输入 `AKIAIOSFODNN7EXAMPLE`） |
|------|------|-----|
| `full` | 全替换 `***len{N}***`（默认） | `***len20***` |
| `tail` | 保留首尾 N 位（`redact_keep`） | `AK***LE` |
| `hash` | sha256 前 8 位 | `sha256:1d4f0a2b` |

**不要**在 SKILL/CLI 的任何输出里直接展示规则匹配到的原始字符串。

## context 窗口

每个命中带一个上下文片段（默认 `context_chars=24`）：原文中 match 前后各保留 24 字符，超过的用 `…` 截断。**context 内的 match 字符串本身已被脱敏**——`scan_text` 会把上下文里出现的原 match 替换成 redacted 版本。

如果需要更多上下文，调高 `defaults.context_chars`（在 `security_rules.yml` 顶部）；不要在某条规则上单独设置——保持一致性。

## post_filter

正则匹配后还能跑一道过滤，避免某些规则的常见误报：

| post_filter | 含义 |
|-------------|------|
| `luhn` | 必须通过 Luhn 校验（信用卡专用） |
| `no_digits_only` | 不能是纯数字（避免时间戳串、订单号、容器 ID 命中身份证 / 手机号 / token 类规则的弱形式） |

加新 post_filter：在 `_rules_engine.py::_post_filter_passes` 加一个分支即可，规则文件里 `post_filter: <name>`。

## 已知 false-positive

每次实战调试发现 fp 时，记到这里。命中数 > 50 抽 5 条样本，FP 占比 > 80% 的规则要降级或加 post_filter。

| 规则 | 触发场景 | 建议 |
|------|---------|------|
| `pii-mobile-cn` | 容器 ID（21 位 hex）、订单号、容器 cgroup 路径里的数字串 | 默认 medium，不进 critical 排行；如果项目某索引特别容易误中可以单独把它降到 low |
| `pii-bankcard` | 订单号、时间戳串 | 已内置 Luhn 过滤；如果还误判，把 severity 降到 medium |
| `secret-bearer-token` | stack trace 里的 base64 编码 / cookie 字符串 | pattern 已要求 `bearer\|authorization` 上下文锚点；如果误判仍多，把最小长度从 20 调到 30 |
| `injection-sql-union` | 普通文档 / 报错描述里的 “union” / “select” 词 | pattern 已加边界；命中后看 context 再判断；用户报告误报多时可以降级到 medium |

## 自检流程

每次改规则后，跑一次自检防回归：

```bash
for r in $(uv run scripts/n9e_log_secrules.py --mode list --output json | jq -r '.data.rules[].id'); do
  uv run scripts/n9e_log_secrules.py --mode test --rule-id "$r" --output markdown | grep -E '总体|❌'
done
```

## 升级 `_n9e_client.py`

⚠️ 本技能的 `scripts/_n9e_client.py` 是 nightingale-log 的**物理拷贝**。当 nightingale-log 的客户端修了 bug：

```bash
cp deploy-all/qwenpaw/working/workspaces/query/skills/nightingale-log/scripts/_n9e_client.py \
   deploy-all/qwenpaw/working/workspaces/query/skills/log-security-scan/scripts/_n9e_client.py
```

保留顶部的 `# COPY OF nightingale-log/scripts/_n9e_client.py — sync manually when upstream changes.` 注释。
