# AI 大屏 M1 · 生产地基(稳态 + 活数据)

**Goal:** 把大屏从"演示强的内部 Beta"推到"可上生产的最小集"。四件硬事:
(1) SQLite 持久化(screens/versions/tasks),修复 2-worker 下内存任务表的 404/丢任务潜伏 bug;
(2) **数据自动刷新**——后端 refresh 接口只重跑 L2(组件级 fetch-once),前端按能力 refreshPolicy 周期拉新,发布出去的大屏是"活的";
(3) 跨请求能力缓存(尊重元数据 cachePolicy.ttlSeconds)+ web-live 提供方限流;
(4) 取数失败文案友好化(CLI 风格报错不上屏)。

**不变式:** wire contract 不破(AiBigScreenApp 形状、draft-tasks 轮询协议、CRUD 路由);no-fake-data;失败诚实。

## 任务

- [ ] T1 `ai_big_screen/store.py`:SQLite(WAL)三表 screens/screen_versions/draft_tasks,路径经 `runtime_data_paths.py`;API 与 `ai_big_screen_registry` 等价(save/get/list/delete)+ 任务 CRUD;首次启动自动从 registry.json 迁移;跨进程(2 worker)可见。TDD。
- [ ] T2 service 切换:CRUD 与 draft-task 走 store(任务状态由 worker 进程写库、任意 worker 可读);保留 registry.json 只读迁移源。现有 API 契约测试全绿。
- [ ] T3 刷新链路(后端):`POST /ai-big-screens/{id}/refresh`——读屏→按组件 queryParams 重跑 L2(共享 CapabilityCache)→只更新 components[].data 与 updatedAt(不动版式/不调 LLM)→落库并返回 screen。单测:数据更新、版式不变、失败组件裁 failed 不阻断。
- [ ] T4 跨请求能力缓存:registry 级 TTL 缓存(键=capabilityId+params,TTL=元数据 cachePolicy.ttlSeconds,默认 30s,web-live 120s);refresh 与 draft 共用;线程/异步安全。
- [ ] T5 刷新链路(前端):大屏查看页与工坊预览按 min(组件 refreshInterval) 周期调 refresh(下限 30s,页面隐藏暂停);失败静默保留旧数据 + 角标提示最近刷新时间。
- [ ] T6 失败文案友好化:adjudication 层把含 CLI 痕迹(--flag/.env/Traceback)的 message 收敛为「数据源暂不可用(<来源>)」,原文进日志;单测钉死。
- [ ] T7 验收:重启不丢任务;并发 2 worker 轮询稳定;发布屏挂 2 个刷新周期数字变化;pre-commit + 全套测试绿。

## 验证
`pytest tests/unit/extensions/ai_big_screen/ tests/unit/extensions/api/test_ai_big_screen_api.py`;前端 `npm run test:big-screen` + build;真机:生成→发布→开外链→观察自动刷新与 failed 徽章。
