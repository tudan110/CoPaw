# AI 大屏 M1 · 生产地基(稳态 + 活数据)

**Goal:** 把大屏从"演示强的内部 Beta"推到"可上生产的最小集"。四件硬事:
(1) SQLite 持久化(screens/versions/tasks),修复 2-worker 下内存任务表的 404/丢任务潜伏 bug;
(2) **数据自动刷新**——后端 refresh 接口只重跑 L2(组件级 fetch-once),前端按能力 refreshPolicy 周期拉新,发布出去的大屏是"活的";
(3) 跨请求能力缓存(尊重元数据 cachePolicy.ttlSeconds)+ web-live 提供方限流;
(4) 取数失败文案友好化(CLI 风格报错不上屏)。

**不变式:** wire contract 不破(AiBigScreenApp 形状、draft-tasks 轮询协议、CRUD 路由);no-fake-data;失败诚实。

## 任务(2026-06-11 全部完成)

- [x] T1 SQLite store 三表 + 迁移 + TDD(`437a5aeb`)
- [x] T2 service 切 store,修 2-worker 任务 404 潜伏 bug(`fb752735`)
- [x] T3 `POST /{id}/refresh` 只重跑 L2,版式/版本不动,失败不阻断(`53f57a22`)
- [x] T4 跨请求 TTL 缓存(尊重 cachePolicy;refresh 语义绕过读、回填写)(`16671c9f`)
- [x] T5 查看页自动刷新(min refreshInterval,钳 30s-10min,隐藏暂停,角标时间)+ 工坊「刷新数据」(`53da3694`)
- [x] T6 CLI 痕迹失败文案收敛,业务文案保留,原文进日志(`08d85d7d`)
- [x] T7 真机验收:跨 worker 任务一轮即中;保存→连刷两次 200、20 行真实工单、updatedAt 前进、版本数不变;后端 168 测试 + 前端 48 测试全绿。

## 验证
`pytest tests/unit/extensions/ai_big_screen/ tests/unit/extensions/api/test_ai_big_screen_api.py`;前端 `npm run test:big-screen` + build;真机:生成→发布→开外链→观察自动刷新与 failed 徽章。
