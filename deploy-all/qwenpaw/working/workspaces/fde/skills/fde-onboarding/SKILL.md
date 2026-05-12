---
name: fde-onboarding
category: ops-delivery
tags: [fde, delivery, secondary-development, skill-generation, network-management, ops-automation]
triggers: [新增数字员工, 交付一个技能, 帮我做个数字员工, 二开一个技能, FDE, 客户需求落地, 生成技能, 交付方案, 把需求落进系统]
description: FDE 交付助手的元技能 —— 把客户/运营方的需求与系统现状翻译成可上线的"数字员工"业务技能。访谈澄清 → 交付方案 → 按 skill_scaffold 生成技能 → 自检（域审查 dry-run + 示例运行 + 待确认项）→ 把产物暂存到 fde 工作区 staged/，交人工在 Portal『交付工作台』确认安装。仅面向网络管理 / 运维域；不直接写业务智能体工作区。
---

# FDE Onboarding（数字员工交付）

把"原本要带客户需求去现场、给方案、再让研发落地"的链路压成一个回路：**访谈 → 方案 → 生成 → 自检 → 交人确认安装**。详细职责见工作区根目录的 `AGENTS.md`。

## 何时使用

- 用户说"我想要个数字员工能……""帮我交付/二开一个技能""把这个需求落进系统"
- 用户带来了客户需求 + 现有系统情况（接口、工单系统、CMDB 等），希望据此产出可上线的技能

## 何时不要使用

- 用户只是问一般编程问题、要技术教程，或与网管/运维无关的需求 —— 这类直接拒绝（领域审查也会拦）
- 用户只是想用某个已有技能做查询 —— 引导他直接对相应业务智能体说话，不需要 FDE 介入

## 工作流（一步步来，别甩问卷）

1. **访谈**：拿到「业务目标/痛点、要对接哪些系统及对接方式（贴 API 文档/报文样例/curl）、期望职责与输入输出形态、目标业务智能体、SLA/边界、可复用的已有技能」。整理成「交付需求单」（结构化要点 + markdown 摘要），发给对方确认。
2. **交付方案**：把需求单映射到平台构件 —— 要新建哪几个 skill（`name`/`category`/`triggers`/职责/目标工作区）、要不要 `integrations/` 适配器或 MCP、要不要 cron、复用哪些已有 skill、关键不确定点（进"待确认项"，**不要编造接口字段**）。发给对方确认。
3. **生成**：对每个待建 skill，调
   ```bash
   python scripts/fde_tools.py scaffold --name <skill-name> --target-workspace <ws> --brief-file /tmp/brief.json --json
   ```
   它会从骨架（`references/skeleton/`，镜像 `src/qwenpaw/extensions/templates/skill_scaffold/`）生成到 fde 工作区的 `staged/<skill-name>/` 并顺手自检一次。然后**按访谈拿到的接口信息**用 `edit_file` 把 `staged/<skill-name>/runtime/tool_adapters.py` 的 `mock-or-real` 占位换成真实调用、补 `runtime/playbooks/business_flow.py`、改 `SKILL.md` 的触发/描述、把 `.env.example` 写成真实的 key。
4. **自检**：每改动一次跑
   ```bash
   python scripts/fde_tools.py selfcheck --skill-dir staged/<skill-name> --json
   python scripts/fde_tools.py probe     --skill-dir staged/<skill-name> --json   # 沙箱跑一遍 diagnose
   ```
   `ready_for_review` 必须为 true 才交付（域审查未通过/有语法错/缺 SKILL.md 都会阻塞）。凭证只进 `.env.example` + 待确认项，**绝不写进 SKILL.md/脚本**。
5. **交付**：把"交付方案 + 每个 staged skill 的预览 + 自检结果 + 待确认项"组织清楚给对方，并提示：到 Portal **「交付工作台」** 面板逐个查看代码、（可选）沙箱试跑、然后点「确认安装到 \<目标工作区\>」。真正写入业务工作区由那个人工动作触发（走现有 `POST /api/skills`，含安全扫描），**你不替他按这个键**。

## 工具速查（`scripts/fde_tools.py`，用 app 自带 python 调，不要 uv）

| 子命令 | 作用 |
| --- | --- |
| `scaffold --name N --target-workspace W [--brief-file F]` | 从骨架生成 staged 技能 + 自检 |
| `selfcheck --skill-dir D` | 安全扫描 dry-run + 领域审查 + 语法 + 待确认项 |
| `probe --skill-dir D [--context-file F]` | 沙箱里跑一遍生成技能的 `diagnose` |
| `list-staged` / `show-staged --name N` | 列出 / 查看 staged 技能（文件树+内容） |
| `discard --name N` | 删掉一个 staged 技能 |

## 硬约束

- 只写 fde 工作区（尤其 `staged/`）。**不要** `create_skill` 到别的工作区，**不要**直接改其它工作区目录。
- 生成的 skill 必须过 `skill_scanner` + `domain_guard`（网管域）。自检过不了 = 不交付。
- 凭证（token/密码/AK SK）不进生成的 `SKILL.md`/脚本/`skill.json`。
- 拿不准的接口字段，**问对方或让对方贴样例**，不编造。
- 上游 `src/qwenpaw/`（`extensions/` 除外）不动 —— 你的产出是"部署侧定制资产"，落在 workspace 层。
