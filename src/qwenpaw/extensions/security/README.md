# 安全加固扩展（extensions/security）

本扩展为系统提供两项安全加固能力，**不入侵 qwenpaw 核心代码**：核心仅在
`app/_app.py` 启动时调用一次 `install_security_hardening()`（2 行），以及在
`config/config.py` 中登记 `OutputGuardConfig` 配置模型。

| 能力 | 模块 | 说明 |
|---|---|---|
| 出口脱敏 | `output_guard/` | 所有渠道出站消息发送前打码凭证/密钥及业务词库命中内容 |
| 高危操作边界 | `high_risk_boundary.py` + config.json | CRITICAL/HIGH 工具调用自动拒绝，MEDIUM 走 `/approval` 人工审批 |

---

## 一、出口脱敏（output_guard）

### 工作机制

启动时对 `BaseChannel` 及所有已注册渠道类（含 `custom_channels/`）**自身定义**
的出站方法做幂等包装：

- `send` / `send_content_parts` —— 常规回复、工具输出、错误提示、主动/定时消息；
- `on_streaming_delta` / `on_streaming_end` —— 流式渠道（钉钉/飞书/Telegram/企微）
  的 `accumulated_text` 全量刷新文本；delta 阶段附加"尾部防护"，对未输出完整的
  高置信凭证前缀（`sk-`、`AKIA`、`LTAI`、`ghp_`、`eyJ`、`-----BEGIN`、`password=`）
  提前打码。

打码**幂等**（多层包装重复脱敏无害）、**fail-open**（脱敏器异常只记 ERROR 日志，
原文照发，不让回复失败）。日志只记录命中的 pattern id，绝不记录敏感值本身。

### 内置 pattern

| id | 覆盖 | 打码示例 |
|---|---|---|
| `pem_private_key` | PEM 私钥块 | `[REDACTED PRIVATE KEY]` |
| `anthropic_key` | `sk-ant-...` | `sk-ant-ab****...**xx` |
| `openai_dashscope_key` | `sk-...`（OpenAI/百炼） | `sk-tes****...**xx` |
| `aliyun_ak_id` | 阿里云 AccessKey ID（LTAI...） | 留前 6 后 2 |
| `aws_ak_id` | AWS AccessKey（AKIA...） | 留前 6 后 2 |
| `github_token` | `ghp_/gho_/...` | 留前 6 后 2 |
| `jwt` | 三段式 JWT | `eyJ***.[REDACTED-JWT]` |
| `db_uri_password` | `mysql://u:密码@host` 等连接串 | 密码全掩 |
| `bearer_token` | `Bearer xxx` | 留前 4 后 2 |
| `kv_secret_assignment` | `password=/token:/api_key=` 等赋值 | 值留前 4 后 2 |
| `cn_mobile` | 中国手机号 | `138****5678` |

误杀时可通过 `disabled_patterns` 按 id 关停（`kv_secret_assignment` 较泛化，
是最常见的关停对象）。

### 业务词库（lexicon.yaml）

默认词库随模块发布（`output_guard/lexicon.yaml`），推荐通过 `lexicon_path`
指到工作目录下供运维直接编辑。**按 mtime 热加载，改完即生效，无需重启**。
格式（字面词 + 正则，详见文件内注释）：

```yaml
words:
  - "内部项目代号示例"          # 整词打码为 ****
  - text: "客户XX集团"
    mask: "客户***"             # 自定义替换文本
regexes:
  - pattern: "PRJ-\\d{4,}"
    style: partial              # partial | full | fixed
    keep_prefix: 4
  - pattern: "(?i)contract\\s+no\\.?\\s*\\S+"
    style: fixed
    replacement: "[合同编号已脱敏]"
```

### 配置

`config.json` -> `security.output_guard`（环境变量优先级更高）：

```json
{
  "security": {
    "output_guard": {
      "enabled": true,
      "mode": "mask",
      "lexicon_path": "",
      "disabled_patterns": [],
      "mask_streaming": true
    }
  }
}
```

| 环境变量 | 取值 |
|---|---|
| `QWENPAW_OUTPUT_GUARD_ENABLED` | `true` / `false` |
| `QWENPAW_OUTPUT_GUARD_MODE` | `mask` / `off` |
| `QWENPAW_OUTPUT_GUARD_LEXICON_PATH` | 词库文件路径 |
| `QWENPAW_OUTPUT_GUARD_DISABLED_PATTERNS` | 逗号分隔的 pattern id |

---

## 二、高危操作边界

### 策略

依托 qwenpaw 原生 tool_guard（规则引擎 + `/approval` 审批流），纯配置实现：

- **CRITICAL / HIGH 命中 → 自动拒绝**：tool_guard 的自动拒绝是 *rule-ID 制*
  （没有"按严重度拒绝"机制），因此 `security.tool_guard.auto_denied_rules`
  须枚举全部 CRITICAL/HIGH 规则 ID；
- **MEDIUM 命中 → 人工审批**：各 agent 的 `agent.json` 设
  `approval_level: "SMART"`（INFO/LOW 放行，MEDIUM+ 进 `/approval`）；
- **守护所有工具**：`guarded_tools: ["*"]`，未来接入的 MCP/DB 工具自动纳入。

**有意豁免**（HIGH 但属网管运维常规动作，走审批而非拒绝）：
`TOOL_CMD_SERVICE_RESTART`、`TOOL_CMD_PROCESS_KILL`。豁免清单同步维护在
`high_risk_boundary.APPROVAL_INSTEAD_OF_DENY`。

### 新增 custom_rules（针对对话触发的 DB/权限风险）

| 规则 ID | 严重度 | 处置 | 覆盖 |
|---|---|---|---|
| `SEC_SQL_DESTRUCTIVE_DDL` | CRITICAL | 拒绝 | `DROP TABLE/DATABASE/...`、`TRUNCATE` |
| `SEC_SQL_DML_NO_WHERE` | HIGH | 拒绝 | 无 WHERE 的 `DELETE FROM` / `UPDATE ... SET` |
| `SEC_SQL_DML_WRITE` | MEDIUM | 审批 | 带 WHERE 的 DELETE/UPDATE、`ALTER TABLE` |
| `SEC_WIN_REGISTRY_WRITE` | HIGH | 拒绝 | `reg add/delete/import`、`Set-ItemProperty HKLM/HKCU` |
| `SEC_WIN_ACL_CHANGE` | HIGH | 拒绝 | `icacls/takeown/Set-Acl/net user /add`、`chmod/chown` |

完整配置样例见 `deploy-all/qwenpaw/data/qwenpaw/config.json` 的
`security.tool_guard` 段，线上环境可整段套用。

### 启动一致性校验

`check_auto_deny_coverage()` 在应用启动时核对"CRITICAL/HIGH 规则集 vs
auto_denied_rules"，缺漏（升级 qwenpaw 引入新规则后常见）会记 WARNING：

```
security: N CRITICAL/HIGH tool-guard rule(s) are NOT in
security.tool_guard.auto_denied_rules and would fall back to approval-only: ...
```

看到该告警时，把列出的规则 ID 补进 `auto_denied_rules`（或加入豁免清单）。

---

## 测试

```bash
python -m pytest tests/unit/extensions/security/ -v
```

手工冒烟（Console 渠道）：

1. 让 agent 原样输出 `sk-test1234567890abcdefghijklmn` → 回复已打码；
2. 词库加词后再问 → 不重启即生效；
3. 让 agent 执行 `DROP TABLE` / `rm -rf` → 直接拒绝；
4. `DELETE FROM t WHERE id=1` → 出现审批卡片，`/approval approve` 后执行。
