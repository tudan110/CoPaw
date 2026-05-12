---
name: {{skill-name}}
category: {{business-category}}
tags: [{{tags}}]
triggers: [{{triggers}}]
description: {{description}}
---

# {{skill-title}}

{{summary}}

由 FDE 交付助手按 `skill_scaffold` 生成的技能骨架。**上线前**请：

1. 把 `runtime/tool_adapters.py` 里的 `mock-or-real` 占位换成真实接口调用（直接 HTTP，或复用 `src/qwenpaw/extensions/integrations/*`），鉴权从 `.env` 读。
2. 按业务场景补 `runtime/playbooks/business_flow.py`（查询/统计类只需 `diagnose`；带"分析→建议动作→执行→恢复验证"闭环的再补 `execute`）。
3. 需要返回动作按钮 / 图表时，遵循 `src/qwenpaw/extensions/templates/protocols/{portal_action,echarts}.template.md`。

## 何时使用

- 用户消息里已经带有结构化上下文（"业务上下文(JSON)"）
- 用户目标是 {{when-to-use}}

## 何时不要使用

- 用户只是做一般编程问题、技术教程、与本业务无关的任务

## 输入协议

1. 用户消息中包含 `【业务上下文(JSON)】`
2. Skill 从消息中提取 JSON，写入临时文件
3. 调用桥接脚本：

```bash
python scripts/chat_skill_bridge.py diagnose --context-file /tmp/business_context.json
```

如用户明确确认动作：

```bash
python scripts/chat_skill_bridge.py execute --context-file /tmp/business_context.json
```

## 架构

`QwenPaw 聊天 → {{skill-name}} → scripts/chat_skill_bridge.py → runtime/router.py → runtime/playbooks/business_flow.py → runtime/tool_adapters.py → markdown / portal-action / echarts`

## 配置

复制 `.env.example` 为 `.env`，填入真实的 base_url / token。`.env` 不进版本库，真实 secret 走 `secrets/` 级联。
