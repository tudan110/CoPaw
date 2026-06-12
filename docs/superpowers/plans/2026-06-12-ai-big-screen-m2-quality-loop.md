# AI 大屏 M2 · 智能质量闭环

**Goal:** 让"智能"可度量、可回归、可自我改进。M1 解决了"活与稳",M2 解决"好不好、有多好、坏了能不能立刻知道"。分支 `m2-quality-loop`(worktree),基于 M1 HEAD `ef30ddb7`。

## 任务

- [x] T1 **生成遥测** `ai_big_screen/telemetry.py`:每次 draft/refresh/patch 记录事件(stage 耗时、LLM 尝试次数/degraded、各能力 sourceStatus、组件类型分布、总耗时),SQLite 表 `generation_metrics`(复用 store 连接)+ `GET /ai-big-screens/metrics` 汇总端点(近 N 次成功率/降级率/能力失败率/平均耗时)。pipeline/patch 接入,失败不阻断主流程。TDD。(`7f8ad91d`)
- [x] T2 **评测集 harness** `ai_big_screen/evals.py` + `tests/unit/extensions/ai_big_screen/test_evals.py`(mock 冒烟)+ `tests/evals/test_big_screen_llm_evals.py`(`-m p1`,真 LLM 夜间):golden prompt 集(意图→期望能力集合/组件数下限/类型多样性/诚实状态),确定性评分器产出 {case, pass, reasons},汇总通过率。真 LLM 模式双重门控:`QWENPAW_RUN_LLM_EVALS=1` **且** 配置了默认模型,否则 skip(普通 `pytest` 全程离线确定)。(`c889e306`)
- [x] T3 **视觉评审-修订闭环 v1(spec 级)**:`ai_big_screen/critique.py` — 生成后把组件结构概要(类型/标题/布局/配色,不含数据行)交 LLM 评审(CritiquePlan schema:score 0-100、issues、operations⊆视觉类白名单:setComponentTitle/Type/Layout/Palette + setThemePalette),应用一轮受限修订,`aiConversationContext.critique={score,issuesCount,issues,applied}`。仅 LLM 路径且 plan 未降级时启用,fast-path 跳过;失败/超时静默跳过不阻断;`AI_BIG_SCREEN_CRITIQUE=off` 关闭。(`eb8b98c5`)
- [x] T4 **patch 预览 diff**:`apply_patch(dry_run=True)` 在深拷贝上执行(含 queryParams 变更的真实重取数)并产出结构化 diff(componentId/field/before/after;增删组件为 field="component");API patch 请求增加 `preview` 字段,预览不落库不写版本,真实 patch wire 形状不变。前端接入留 M3。(`de865103`)
- [x] T5 验收:大屏全套单测绿(`tests/unit/extensions/ai_big_screen/` + `test_ai_big_screen_api.py`,196+ 用例)+ pre-commit 全过;p1 真 LLM 评测跑通并记录基线(见下)。

## 基线(2026-06-12,真 LLM:custom provider `ctyun`)

```
passRate = 1.0 (5/5)
workorders-today      pass (fast-path,确定性)
alarms-distribution   pass (LLM 路由 real-alarms)
logs-and-weather      pass (system-logs + web-live-data,天气子句未丢)
stock-fallback        pass (未错误路由到任何目录能力)
executive-cockpit     pass (多能力 + 类型多样性达标)
总耗时 20m48s(慢网关;含取数与 critique 超时等待)
```

观察与修正:ctyun 网关上 critique 45s×2 次全部超时(均优雅跳过,生成未阻断,行为符合设计)。据此把 critique 默认调成 **单次尝试 + 60s 上限**——评审是用户关键路径上的加分项,最坏新增延迟必须有界。

已知无关失败:`test_portal_backend.py`(3)/`test_alarm_analyst_service.py`(1)/`test_fde_workbench.py`(1)在 dev 主仓同样失败(预存在,与 M2 无关)。

## 约束
- dev 分支不动;wire contract 不破(新增字段全部可选)。
- critic 绝不修改 queryParams/数据语义——视觉类 op 白名单硬限制。
- 遥测/评审任何失败都不影响生成主链路。

## 运维入口
- 质量看板数据:`GET /ai-big-screens/metrics?limit=100`(成功率/降级率/能力失败率/平均耗时/kind 分布)。
- 夜间评测:`QWENPAW_RUN_LLM_EVALS=1 pytest tests/evals/test_big_screen_llm_evals.py -m p1`(需默认模型;该测试会显式退出测试套件的 provider 隔离)。
- 评审开关:`AI_BIG_SCREEN_CRITIQUE=off`。
