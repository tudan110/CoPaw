# 跳转指令契约(后端 agent ↔ 前端小助手)

后端 agent 是无浏览器的服务进程,只能回文本;真正的页面跳转必须由调用
本 agent 的前端(运维门户 SPA 里的小助手组件)执行。两边只需约定**一段
结构化指令块**。

## 指令格式

agent 在回复末尾追加一个 fenced code block,语言标识为 `qwenpaw:navigate`,
内容是一行 JSON:

````
```qwenpaw:navigate
{"path": "/ops/xj/results", "title": "结果报表", "breadcrumb": "运维中心 / 自动巡检 / 结果报表"}
```
````

字段:

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `path` | 是 | 完整路由,直接喂给 `router.push`。已按 Vue Router 父子拼接规则生成,与 SPA 注册的路由逐字一致。 |
| `title` | 否 | 叶子页面标题,用于按钮文案/确认。 |
| `breadcrumb` | 否 | 面包屑(`运维中心 / 自动巡检 / 结果报表`),用于确认提示。 |

`path` 不含 origin —— 小助手与目标页面同源、同一个 SPA,只需相对路由。

## 前端解析(Vue 示例)

在小助手消息渲染处,拿到 agent 回复全文 `text` 后:

```js
const m = text.match(/```qwenpaw:navigate\s*([\s\S]*?)```/);
if (m) {
  let payload = null;
  try { payload = JSON.parse(m[1].trim()); } catch (e) {}
  const display = text.replace(m[0], "").trim();   // 展示用,去掉指令块
  // 渲染 display;并二选一:
  if (payload && payload.path) {
    this.$router.push(payload.path);                 // ① 自动跳转
    // ② 或渲染按钮,让用户点了再跳:
    //   <el-button @click="$router.push(payload.path)">
    //     前往{{ payload.title }}
    //   </el-button>
  }
}
```

要点:

- **务必把指令块从展示文本里剥掉**(`text.replace(m[0], "")`),否则用户会
  看到一段裸 JSON。
- 自动跳转体验最顺;若担心误跳,可改成"前往页面"按钮,由用户点击触发。
- 解析失败(JSON 不合法)时静默忽略,只展示文本,不要抛错。
- 前端没更新这段逻辑时,指令块只会被渲染成一个普通代码块,不会出错 ——
  可平滑灰度。

## 为什么是 fenced block 而不是自定义标签

- 易正则提取,JSON 可随时扩展字段(如未来加 `query`、`target`)。
- markdown 渲染器对未知语言的 fenced block 只当代码块显示,降级安全。
