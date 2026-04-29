# Portal 流式 Markdown 渲染修复说明

## 1. 问题现象

Portal 聊天区在 **模型流式输出阶段** 会出现 Markdown 渲染异常：

- 代码块、列表、表格、链接在生成中经常错乱
- 生成完成后，整段内容又恢复正常
- 同一段回复，**流式阶段不正常，完成态正常**

这类问题后续非常容易被新的 AI 改动重新引入，因为表面看起来像是“后端没发对”“前端没拼好”，但真实原因并不在这两个直觉点上。

---

## 2. 真实根因

根因不是后端没发流，也不是最终消息内容错误，而是：

1. 后端流事件本身是正常的，文本增量是按 delta 持续发送的
2. `@agentscope-ai/chat` 默认 response card 会在流式阶段对**当前未完成的文本**持续做 Markdown 解析
3. Markdown 在“半截语法”状态下本来就不稳定，例如：
   - 未闭合的 ````` 代码块
   - 只输出了一半的表格
   - 列表缩进还没补全
   - 链接 `[]()` 只生成到一半
4. 所以流式阶段看到的是“对不完整 Markdown 的实时解析结果”，而不是最终内容本身有问题

**结论：这是渲染策略问题，不是内容正确性问题。**

---

## 3. 当前采用的修复策略

Portal 现在采用的是一个**保守且稳定**的策略：

- **生成中**：不对文本做正常 Markdown 解析，改为 `Markdown raw` 直接显示原始文本
- **生成完成后**：继续回退到 upstream 默认 `AgentScopeRuntimeResponseCard`，保留完整 Markdown、工具卡、reasoning、媒体展示等默认能力

这意味着我们明确接受一个取舍：

- 流式阶段优先 **稳定显示**
- 完成阶段优先 **完整格式化**

这个取舍是刻意设计的，不是临时绕过。

---

## 4. 修复落点

本次只改 **portal**，不改 console。

### 关键文件

1. `portal/src/components/PortalRemoteRuntimeChat.tsx`
   - 通过 `options.cards.AgentScopeRuntimeResponseCard` 覆盖默认 response card

2. `portal/src/components/PortalStreamingResponseCard.tsx`
   - 生成中接管渲染
   - 完成后回退到默认 `DefaultResponseCard`

---

## 5. 关键实现原则

### 原则 A：只在生成态接管

判断条件：

- `created`
- `in_progress`

优先看 `response.status`，但**不要只看 `response.status`**。

在当前 `@agentscope-ai/chat` 版本与 portal 实际链路里，流式阶段可能出现：

- `response.status` 已经不是生成态
- 但 `output` 里的 `message.status` 或 `content.status` 仍然处于 `created / in_progress`

如果只盯 `response.status`，portal 会过早回退到默认 Markdown 卡片，结果又重新对半截 Markdown 做实时解析。

因此生成态判断必须按下面优先级兜底：

1. `response.status` 是 `created / in_progress`
2. 或 `output[].status` 里仍有 `created / in_progress`
3. 或 `output[].content[].status` 里仍有 `created / in_progress`

只有当 response / message / content 三层都不再处于生成态时，才回到默认卡片。

### 原则 B：不要改后端协议来“修渲染”

这次问题不是协议错，因此不要为了修前端显示去改：

- SSE 事件格式
- delta 结构
- message/content schema
- response builder 的后端拼装逻辑

否则很容易把一个前端渲染问题扩散成前后端兼容问题。

### 原则 C：工具卡 / reasoning / media 继续复用 upstream 逻辑

生成态接管时，只对最容易出问题的文本部分做保守渲染：

- `text` -> `@agentscope-ai/chat` 的 `Markdown raw`，外层再套 `pre-wrap` 容器保留换行
- `refusal` -> `@agentscope-ai/chat` 的 `Markdown raw`，外层再套 `pre-wrap` 容器保留换行
- `data` -> `<pre>`
- `image/audio/video/file` -> 继续走现有媒体卡片
- `tool/reasoning/error/actions` -> 尽量复用 upstream 组件

补充说明：`@agentscope-ai/chat` 新版本里的 `Markdown raw` 底层只是普通 `div`，
默认不会额外保留换行和空白；如果直接裸用它显示流式中的表格 / 列表 / 代码块，
视觉上仍然会“挤坏”。因此 portal 生成态仍然可以继续使用 `Markdown raw`，
但必须在外层补一层 `white-space: pre-wrap` 的容器来保留原文换行。

### 原则 D：完成态必须回退到默认卡片

不要自己长期维护一整套完整 response card。

否则后面很容易出现：

- tool card 行为不一致
- reasoning 样式分叉
- error/actions 丢失
- 升级 `@agentscope-ai/chat` 后 portal 与 upstream 能力脱节

### 原则 E：业务卡片不要在流式阶段提前结构化

除了聊天 response card 之外，portal 还有一些业务卡片会根据回复内容做二次识别和结构化渲染，例如：

- 巡检卡片（`# PORTAL INSPECTION CARD MODE`）
- 其他基于 marker / 标题 / 固定章节名判断的业务卡片

这类卡片**只能在非流式完成态渲染**。原因是：

1. 流式阶段拿到的是半截业务 Markdown
2. marker、章节、表格、拓扑区块可能刚输出到一半
3. 一旦提前进入结构化卡片组件，就会把半截表格、半截章节错误地解释成“已完成数据”

表现上就会出现：

- 标题已经被提取成卡片标题
- 但表格正文还没完整，显示成一整行管道文本
- 拓扑/指标/结论区域反复跳变

因此巡检卡片这类业务卡片的正确策略是：

- **流式阶段**：继续走普通 `MessageMarkdown` / 原文稳定展示
- **完成阶段**：再切换到 `InspectionAnalystCardPanel` 这类结构化卡片

---

## 6. 为什么后续 AI 很容易又改坏

后续 AI 常见误判有这些：

### 误判 1：以为是 SSE / delta 有问题

然后去改后端流事件，结果把原本正常的 runtime 协议搞复杂。

### 误判 2：以为应该“继续优化 Markdown 实时渲染”

比如尝试：

- 继续用默认 Markdown 组件硬解析
- 在流式阶段加更多 parser hack
- 手工补齐代码块或表格闭合

这类方案都很脆弱，因为你无法可靠判断模型下一 token 会不会补齐语法。

### 误判 3：直接全量 fork upstream response card

这样短期能跑，但后续成本很高：

- 升库时容易失配
- 新能力不会自动继承
- 一个小问题演变成长期维护分叉

### 误判 4：顺手去改 console

**这次 fix 的边界是 portal。**

如果未来用户只要求 portal，不要把 console 一起改进去。

---

## 7. 后续开发时必须遵守的边界

### 可以改

- `PortalRemoteRuntimeChat.tsx` 中的 card override 接法
- `PortalStreamingResponseCard.tsx` 中生成态的展示细节
- 生成态 raw 文本样式
- 媒体内容和 data 内容的展示方式

### 尽量不要改

- 后端 `/console/chat` 流协议
- `portalRuntimeSessionApi.ts` 的消息转换契约
- 默认 response 的完成态行为

### 升级依赖时重点关注

Portal 当前依赖 `@agentscope-ai/chat`，并且 `PortalStreamingResponseCard.tsx` 使用了它的**内部导出路径**，例如：

- `@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Card`
- `.../Builder`
- `.../Tool`
- `.../Reasoning`
- `.../Error`
- `.../Actions`

这类路径不是稳定公开 API。**只要升级 `@agentscope-ai/chat`，这里就要重点回归。**

---

## 8. 回归检查清单

以后只要有人改下面任一项，都要检查这份问题是否回归：

- `portal/src/components/PortalRemoteRuntimeChat.tsx`
- `portal/src/components/PortalStreamingResponseCard.tsx`
- `portal/src/lib/portalRuntimeSessionApi.ts`
- portal 的 `@agentscope-ai/chat` 版本
- portal 的消息卡片覆盖逻辑

建议至少验证以下场景：

1. 流式代码块：模型逐字输出三引号代码块时，页面不应出现严重错位
2. 流式表格：半截表格不应把整个消息区渲染崩
3. 流式列表：未闭合列表期间至少应稳定可读
4. 完成态回放：回复完成后，Markdown 应恢复正常格式化
5. 工具卡与 reasoning：生成中和完成后都不能丢
6. 图片/文件/音频/视频：媒体 URL 替换逻辑仍然正常

---

## 9. 推荐处理原则

如果以后又有人反馈“流式 Markdown 又坏了”，优先按下面顺序排查：

1. 先确认是不是 **portal**
2. 再确认是不是只在 **生成中异常、完成后正常**
3. 如果是，就优先检查 `PortalStreamingResponseCard.tsx`
4. 检查是否有人把生成态又切回默认 Markdown 解析
5. 检查 `@agentscope-ai/chat` 升级后内部导入路径或行为是否变了

不要一上来就改后端协议。

---

## 10. 当前结论

这次问题的本质是：

> **不完整 Markdown 的实时解析天然不稳定，因此流式阶段应该优先保证稳定显示，完成后再恢复完整格式化。**

Portal 当前实现就是围绕这个原则建立的。后续如果继续开发，除非有非常明确的理由，否则不要推翻这条策略。
