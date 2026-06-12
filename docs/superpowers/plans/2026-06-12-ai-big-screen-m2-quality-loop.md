# AI 大屏 M2 · 智能质量闭环

**Goal:** 让"智能"可度量、可回归、可自我改进。M1 解决了"活与稳",M2 解决"好不好、有多好、坏了能不能立刻知道"。分支 `m2-quality-loop`(worktree),基于 M1 HEAD `ef30ddb7`。

## 任务

- [ ] T1 **生成遥测** `ai_big_screen/telemetry.py`:每次 draft/refresh/patch 记录事件(stage 耗时、LLM 尝试次数/degraded、各能力 sourceStatus、组件类型分布、总耗时),SQLite 表 `generation_metrics`(复用 store 连接)+ `GET /ai-big-screens/metrics` 汇总端点(近 N 次成功率/降级率/能力失败率/平均耗时)。pipeline/patch 接入,失败不阻断主流程。TDD。
- [ ] T2 **评测集 harness** `ai_big_screen/evals.py` + `tests/unit/extensions/ai_big_screen/test_evals.py`(mock 冒烟)+ `tests/evals/test_big_screen_llm_evals.py`(`-m p1`,真 LLM 夜间):golden prompt 集(意图→期望能力集合/组件数下限/类型多样性/含 composed/查询≠分析),确定性评分器产出 {case, pass, reasons},汇总通过率。真 LLM 模式无模型配置时 skip。
- [ ] T3 **视觉评审-修订闭环 v1(spec 级)**:`ai_big_screen/critique.py` — 生成后把组件结构概要(类型/composition/blueprint 摘要,不含数据行)交 LLM 评审(CritiquePlan schema:score 0-100、issues、operations⊆patch 视觉类白名单:setComponentType/Layout/Palette/Title/setThemePalette),应用一轮受限修订,`aiConversationContext.critique={score,issuesCount,applied}`。仅 LLM 路径启用,fast-path 跳过;失败/超时静默跳过不阻断;可经 env `AI_BIG_SCREEN_CRITIQUE=off` 关闭。
- [ ] T4 **patch 预览 diff**:`apply_patch(dry_run=True)` 在深拷贝上执行并产出结构化 diff(componentId/field/before/after);API `POST /{id}/patch` 增加 `preview` 字段,预览不落库不写版本。前端接入留 M3。
- [ ] T5 验收:全套测试绿 + pre-commit;真机(主仓后端不动,worktree 内单测为准)+ p1 评测在配置模型的环境跑一轮记录基线通过率。

## 约束
- dev 分支不动;wire contract 不破(新增字段全部可选)。
- critic 绝不修改 queryParams/数据语义——视觉类 op 白名单硬限制。
- 遥测/评审任何失败都不影响生成主链路。
