# 动作指令契约(后端 operator agent ↔ 前端执行器)

后端 operator agent 是无浏览器的服务进程,只能回文本;真正的"代操作"必须由
前端(门户 SPA 里的智观AI助手)执行。两边约定**一段结构化指令块**
`qwenpaw:action`,与 `qwenpaw:navigate` 同族(都用 fenced code block,前端正则
切片、JSON 可扩展、未知语言降级为普通代码块,平滑灰度)。

## 指令格式

agent 在回复里追加一个 fenced code block,语言标识为 `qwenpaw:action`,内容是
一行 JSON:

````
```qwenpaw:action
{"op":"workflow.category.add","action":"create","route":"/workflow/category","page":"Category","open":"handleAdd","model":"form","submit":"submitForm","title":"新建流程分类","breadcrumb":"工单中心 / 流程管理 / 流程分类","fields":[{"prop":"categoryName","label":"分类名称","type":"input","required":true},{"prop":"code","label":"分类编码","type":"input","required":true},{"prop":"remark","label":"备注","type":"textarea","required":false}],"params":{"categoryName":"财务类","code":"FIN"},"risk":"create"}
```
````

字段:

| 字段 | 必有 | 说明 |
| --- | --- | --- |
| `op` | 是 | 操作 id(目录主键),用于日志/幂等。 |
| `action` | 是 | 动作类型:`create` / `update` / `delete`。 |
| `route` | 是 | 目标页面路由,直接喂给 `router.push`。 |
| `page` | 是 | 目标页面组件 `name`(如 `Category`),执行器据此从注册表取到当前页实例。 |
| `open` | 是 | 打开新增弹窗的方法名(若依统一 `handleAdd`)。 |
| `model` | 是 | 表单数据对象名(若依统一 `form`)。 |
| `submit` | 是 | 提交方法名(若依统一 `submitForm`),仅用于高亮/确认,**不由执行器自动调用**(除非用户在 L3 显式确认)。 |
| `fields` | 是 | 字段 schema(`prop`/`label`/`type`/`required`),用于虚拟光标定位输入框与文案。 |
| `params` | 是 | 要预填的值(只含目录声明过的字段)。 |
| `title` / `breadcrumb` | 否 | 卡片/确认文案。 |
| `risk` | 否 | 风险级别,决定触发类(kind=trigger)是否自动点击:`export` 等**只读/安全**操作 → 执行器虚拟光标**自动点击**按钮完成(用户已开操作模式+下指令=已确认);`create`/`update`/`delete` **写操作** → 只预填/高亮,**由用户确认点击**(不自动,防 AI 预填错值/误删)。 |

`route` 不含 origin —— 助手与目标页面同源、同一个 SPA,只需相对路由。

## 前端执行器流程(L1 → L3)

执行器拿到 `payload` 后按下列步骤驱动页面,**写操作的最后一步永远交给用户**:

1. **跳转(L1)**:`router.push(payload.route)`(已在该路由则跳过)。虚拟光标
   移向页面。
2. **取页面实例**:从 operable 注册表按 `payload.page`(组件 `name`)拿到当前
   挂载的页面 vm。轮询等待(页面懒加载/路由切换有延迟)。
3. **打开弹窗(L1)**:调用 `vm[payload.open]()`(即 `handleAdd()`),复用页面
   自己的"新增按钮"逻辑。等待 `vm.open === true` 且弹窗 DOM 出现。虚拟光标在
   「新增」按钮上做一次"点击"动画。
4. **预填(L2)**:对 `payload.params` 里每个字段,`vm.$set(vm[payload.model],
   prop, value)` 写入(走 Vue 响应式 + 页面真实校验);虚拟光标移到对应输入框
   做"打字"动画。预填是设 model,不是模拟键盘,稳。
5. **高亮提交、停手(L2)**:虚拟光标移到弹窗里的「确定」按钮,高亮 + 提示
   "我已填好,请您核对后点击提交"。**到此停手**,等用户自己点。用户点的就是
   页面真正的 `submitForm()` → 真实校验 → 真实接口。
6. **(可选 L3)自动提交**:仅当产品开启 L3 且用户在对话里**显式确认**后,执行器
   才调用 `vm[payload.submit]()` 代点提交。默认不开。

任何一步失败(页面未注册、方法不存在、弹窗没出来)都应**降级**:已经跳转/打开的
就停在那一步,提示用户手动继续,绝不静默吞错或强行提交。

## 页面如何变得"可操作"(零侵入注册)

门户所有业务页都经 `store/modules/permission.js` 的 `loadView()` 动态加载。在
`loadView` 里给每个视图组件混入一个 `operable` mixin:组件 `mounted` 时把自身
实例按组件 `name` 注册进一个全局注册表,`beforeDestroy` 时注销。这样**一个页面
都不用改**,全站 CRUD 页一次性具备"可被执行器驱动"的能力。执行器只跟注册表 +
`route/open/model/fields/submit` 打交道,不依赖各页 DOM 结构,稳。

## 为什么是 C 方案(混合)而不是纯模拟点击

- 复用页面**真实的** `handleAdd` / 表单 / 校验 / `submitForm` / 接口——"调用新增
  按钮相同的后端逻辑",而不是另写一套接口、绕过前端校验。
- 预填用设 model(响应式),不靠脆弱的模拟键盘事件;虚拟光标只是叠加的**演示
  层**,讲清"AI 在操作哪",不承担真正的数据写入。
- 写操作天然需要"人确认一次",C 把这一闸做进流程:预填好 → 用户核对 → 用户提交。

## 独立模式,不走通用 gateway

operator 是独立 agent(`/api/agents/operator`),只装 page-operator 技能、用收紧的
系统提示,只做"匹配 + 抽参 + 出指令",不经过 gateway 那套通用推理,也不与其共用
限流上下文。前端"操作模式"开关把消息发给 operator,而非 gateway。
