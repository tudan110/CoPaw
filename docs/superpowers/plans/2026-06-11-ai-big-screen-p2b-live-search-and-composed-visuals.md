# AI 大屏 P2b · 实时检索兜底 + 即时创作视觉引擎

**Goal:** 解锁两个"写死":(A) 数据不设限——专用能力之外的公开实时信息由 `web-live-data` 能力真实检索(天气/汇率/通用网页),不再静默丢弃或一律 capability-gap;(B) 表达不设限——新增 `composed` 组件类型 + `visualSpec.blueprint` 声明式原语语法,LLM 用受控积木(value/chart/list/badge/progress/sparkline)即时创作版式,而非只在 18 个成品里挑。

**两条铁律不变:** no-fake-data(检索来的也必须是真数据、可标来源,查不到=诚实 failed/empty);no-arbitrary-code(blueprint 是数据,渲染器解释,不 eval)。

## A. web-live-data 能力(后端)

- `capabilities/web_live.py`:提供方路由 `_detect_kind(query)` → `weather`(wttr.in `?format=j1`,直接收中文地名)/ `fx`(open.er-api.com)/ `web`(cn.bing.com/search HTML 正则解析 title+snippet+host,防御式)。httpx、UA、短超时、文本消毒(去标签/截断)、来源写入 `source`/`trend`。失败抛异常→注册表裁决 failed。
- `descriptors.py`:注册 `web-live-data` 元数据(描述写明:公开实时信息用我;内部未接入数据仍用 capability-gap)+ FETCHERS 项。
- `intent.py`:L1 prompt 增加路由指引。fast-path 不收编(uncovered 子句已回退 LLM,由 LLM 构造 query)。
- 测试:kind 路由、三个 provider 的 canned-response 解析(mock httpx)、注入/超长 query 消毒、registry 集合更新(7→8)、golden:"系统日志+南京天气"→ logs live + web-live-data live。

## B. composed/blueprint 视觉引擎

**语法(受控积木,全白名单):**
```
visualSpec.blueprint = {
  layout: rows|columns|grid|overlay|radial, gap?: s|m|l, cells: [
    { span?: 1..4, element: {
        kind: value|chart|list|badge|label|progress|sparkline|group,
        // value: bind{value,unit,label,prefix}, style plain|flip|glow, size m|l|xl
        // chart: chart line|area|bar|donut|gauge|radar|heatmap, bind{x,y,name,value}
        // list:  style stream|rank|plain, bind{title,message,time,tone,value}, limit≤20
        // badge: bind{text}|text(静态消毒文本), tone
        // progress: style bar|ring|liquid, bind{value,max}
        // sparkline: bind{x,y}
        // group: 嵌套一层 cells(depth≤2)
    }}
  ] (≤12)
}
```
- 后端:`sanitizer.py` 增加 `_sanitize_blueprint`(枚举白名单、bind 走 safe_visual_token、limit/span/depth/cells 钳制、静态 text 消毒);`intent.ALLOWED_COMPONENT_TYPES += composed`;各能力 `supportedVisuals += composed`;L1 prompt 教语法 + 强示例,鼓励把 1-2 个核心组件做成 composed 创作。
- 前端:`types.ts` blueprint 类型;`visualSpec.ts` 白名单镜像;`widgets/ComposedWidget.tsx` 解释器(flex/grid 布局,复用 EChart option builders、FlipNumber、LiquidBall、binding.ts、rules.ts);registry 注册 `composed`;CSS;node 测试(纯逻辑:blueprint 规范化/绑定解析);`pnpm build` 门禁。

## 验收(2026-06-11 已全部通过)
- [x] 单测全绿:后端 133 pytest + 前端 48 node --test;pre-commit 干净。
- [x] 端到端(真后端):"查询15分钟系统日志,南京天气" → 日志 live(359,773 条,历史窗口标注)+ 天气 live(32°C,来源 wttr.in)。
- [x] 创作端到端:"炫酷态势创作大屏" → composed[columns: group/chart/list] 挂 200 条真实告警 + 天气/工单/Top5/CMDB 水球全部 live,零降级。
- [x] 失败诚实:提供方异常→注册表裁决 failed;空检索→empty;blueprint 无效→忽略并提示,不破屏。

提交:`c34a33c3`(A 后端)`27a00197`(B 后端)`38311a73`(B 前端)。
