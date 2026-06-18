# 门户「操作模式」设计:自然语言代操作(page-operator)

状态:v1 已落地(端到端骨架,首条操作「新建流程分类」打通)
日期:2026-06-17
关联:与 `page-navigator`(对话跳转门户页面)同构;是它从"带路(只读)"到
"代操作(写)"的延伸。

## 1. 背景与目标

`page-navigator` 让用户用自然语言跳转到某个门户页面(只读、低风险,且
`getRouters` 白送了"页面目录")。本设计把能力推进到**代操作**:用户说
"帮我新建一个流程分类",系统识别到这是工单中心→流程管理→流程分类页面上的
"新增"能力,**跳过去 → 打开新增弹窗 → 把参数预填好 → 高亮「确定」按钮**,
最终由**用户本人**核对后点击提交(走页面真实校验与真实接口)。

写操作是有副作用、不可逆的,且没有现成的"操作目录"——这是与导航的本质区别。

## 2. 关键决策

### 2.1 执行模型:C 方案(混合)

| 模型 | 做法 | 取舍 |
| --- | --- | --- |
| A 接口级 | 对话里收齐参数直接调新增接口 | 快但绕过前端校验,要逐个知道接口契约 |
| B UI 级全自动 | 模拟点击/填表/提交,真的驱动组件 | 复用页面逻辑但脆、每页定制、难规模化 |
| **C 混合(选用)** | 跳转+预填+**人工确认提交** | 复用真实表单/校验/提交逻辑;写操作保留人确认;虚拟光标正好做演示层 |

C 复用页面**真实的** `handleAdd` / 表单 / `submitForm` / 接口——即"调用新增
按钮相同的后端逻辑",而不是另写一套。预填用**设 model(响应式)**而非模拟键盘,
稳;虚拟光标只是叠加的**演示层**,讲清"AI 在操作哪",不承担数据写入。

成熟度阶梯:L1 跳转+开弹窗 → L2 预填+高亮指引(当前默认止于此)→ L3 用户
显式确认后代点提交(默认关闭)→ L4 全程自动化(暂不做)。

### 2.2 这套若依范式是"省力杠杆"

inoe-ui(`inoe-ui-monorepo/packages/inoe-ui`)是若依范式,~60 个 CRUD 页高度
一致(都是 `handleAdd()` 开弹窗 → `el-form` 绑 `form.xxx` → `submitForm()`
校验后调 `addXxx()`)。这一致性带来三个杠杆:

1. **操作目录可半自动生成**(扫描器扫 `views/**/index.vue` + `api/**`)。实测
   扫 162 个页面抽到 **34 个**标准新增操作候选。
2. **一个通用执行器**就能驱动所有页面(方法名/数据对象统一)。
3. **零侵入接入**:路由经 `store/modules/permission.js` 的 `loadView()` 动态
   加载每个页面;在 `loadView` 里注入一个 operable mixin,**一个页面都不用改**,
   全站 CRUD 页一次性可被驱动。

### 2.3 独立模式,不走通用 gateway

操作是写、复杂、风险高,且本质是前端驱动页面。故做成**独立 `operator` 智能体**
(`/api/agents/operator`),只装 `page-operator` 技能 + 收紧的系统提示,只做
"匹配 + 抽参 + 出指令",不经过 gateway 的通用推理,也不与其共用限流上下文
(避开协同/限流坑)。前端"操作模式"开关把消息发给 operator,而非 gateway。

代理可达性:dev(`vue.config.js`)与 prod(`deploy/nginx.conf`)都按前缀代理
`/api/agents/` → qwenpaw:8088,故 `/api/agents/operator` 零改造即可达。

## 3. 架构

```
用户(操作模式开关 ON)
  └─ chatDialog.vue  ──POST /api/agents/operator/console/chat (SSE)──▶  operator agent
                                                                          │ 只装 page-operator
                                                                          ▼
                                                       find_op.py(识别操作+看缺哪些参数)
                                                       emit_action.py(参数齐→出 qwenpaw:action 指令)
  ◀──────────────── SSE 文本(含 ```qwenpaw:action``` 指令块)───────────────┘
  └─ action.js 解析 → OperatorRunner 执行:
       router.push(route) → operableBus 取页面实例 → vm.handleAdd() 开弹窗
       → 逐字段 vm.$set(form, prop, val) 预填(虚拟光标演示)→ 高亮「确定」→ 停手
  └─ 用户核对 → 点「确定」→ 页面真实 submitForm() → 真实接口
```

后端(QwenPaw,`deploy-all/qwenpaw/working/`):

- `config.json`:`agents.profiles` / `agent_order` 新增 `operator`。
- `workspaces/operator/`:`agent.json`(收紧提示、console 渠道、可用模型)、
  `skill.json`(只启用 page-operator)、`AGENTS.md`/`SOUL.md`/`PROFILE.md`。
- `workspaces/operator/skills/page-operator/`:
  - `runtime/`:`catalog.py`(目录加载)、`matcher.py`(意图匹配,纯逻辑)、
    `directive.py`(必填校验 + 指令生成)、`menu_client.py`(可选:getRouters 按
    component 反查真实 route)。
  - `catalog/operations.json`:操作目录(种子 = `workflow.category.add`)。
  - `scripts/`:`find_op.py`、`emit_action.py`、`scan_catalog.py`(扫描器)。
  - `references/action-contract.md`:`qwenpaw:action` 契约 + 执行器流程。

前端(inoe-ui-monorepo / `packages/inoe-ui`,分支 `tyzg_dev_mk`):

- `layout/components/chatDialog/action.js`:`extractAction`(镜像 `navigate.js`)。
- `layout/components/chatDialog/operator/`:`operableBus.js`(页面注册表)、
  `operableMixin.js`(注册/注销)、`cursor.js`(虚拟光标)、`runner.js`(执行器)。
- `store/modules/permission.js`:`loadView` 包一层注入 operableMixin。
- `api/chatDialog/qwenpaw.js`:各接口参数化 `agentId`(缺省 gateway)。
- `layout/components/chatDialog/chatDialog.vue`:加「操作」开关(与知识库互斥)、
  操作模式消息发往 operator、回复里 `extractAction` → `runAction`。
- `components/MarkdownMessage.vue`:解析 `qwenpaw:action` → 操作卡片(@action)。

## 4. qwenpaw:action 指令契约

fenced code block,语言标识 `qwenpaw:action`,单行 JSON。字段:`op`/`action`/
`route`/`page`/`open`/`model`/`submit`/`fields`/`params`/`title`/`breadcrumb`/
`risk`。完整语义与前端执行器流程见
`workspaces/operator/skills/page-operator/references/action-contract.md`。

## 5. 操作目录与扫描器

- 目录条目:`id` / `intent`(同义词)/ `name` / `menu` / `component` / `page` /
  `route`(兜底)/ `open` / `model` / `submit` / `fields[]` / `api` / `risk` /
  `permission`。
- `route` 仅作兜底:**前端执行器优先用 SPA 自己的路由表按 `page`(组件 name)
  反解真实路径**(菜单权威、随各用户权限),目录无需硬编码每页路由(路由真值只在
  后端菜单里)。运行期 `emit_action.py --resolve-route` 也可在后端按 component 反查。
- 当前已登记 6 条已验证操作:流程分类 / 岗位 / 公告 / 参数配置 / 字典类型 / 租户。
- 扩充方式:`scan_catalog.py --src <inoe-ui>/packages/inoe-ui/src` 半自动抽候选
  → **人工 review**(校 Chinese 名/意图、补 route/permission、核必填)→ 并入
  `operations.json`。扫描器是辅助工具,不是事实源。

## 6. 安全(写操作的命门)

- **显式开关**:操作模式与聊天/知识库并列的独立开关,进了才允许"代操作"。
- **最后一步永远是用户点提交**:预填好 → 用户核对 → 用户点「确定」→ 页面真实
  校验 + 真实接口。agent 填错用户当场能拦。
- **只透传目录声明的字段**:`build_payload` 丢弃未声明/越权字段。
- **风险分级**:`risk=create` 普通确认;`delete`/批量走强确认(后续)。
- agent 永不声称"已提交/已新建";措辞统一为"已为您预填,请确认提交"。
- 不泄露接口 token / Authorization。

## 7. 自测(全部已跑通)

- **后端纯逻辑单测** `test_page_operator.py`(16 用例:意图匹配 / 必填校验 /
  指令生成 / 越权字段过滤 / 路由反查)。
- **跨仓库契约单测** `test_operation_contract.py`:真实跑 `emit_action.py`,断言其
  指令块能被前端 `action.js` 的 fence 正则解析;并守卫 action.js 仍用同一条正则(防漂移)。
- **目录结构单测** `test_operation_catalog_valid.py`:逐条校验 6 个操作(id 规范且
  唯一、有意图词、page/open/model/submit 齐、可定位、字段结构良好)。
- **匹配实测**:6 条操作的口语化 query 全部正确命中 execute,负样本(查告警)→ not_found。
- **前端执行器自测** `verify/run.py`(无框架、最小假 DOM + 桩光标,真实跑
  `runner.run()`):断言跳转到目标路由、`handleAdd` 开弹窗、`form` 按 params 预填、
  **`submitForm` 不被自动调用**、定位到弹窗。9 项全过。
- **CLI 手测**:`find_op.py` / `emit_action.py` 命中、缺参(退出码 2)、出指令正确。
- **扫描器实测**:162 页 → 34 候选;`workflow.category.add` 抽取与手写种子一致。
- 前端改动文件经项目自带 `vue-eslint-parser` 全部成功解析(无语法错)。

**仍待真机验证(环境受限,非代码问题)**:operator 智能体的活体一轮对话——本机
后端当时被 ctyun TPM 429 限流(fault 智能体重试循环占满单 worker → 502),不宜再
叠加模型调用。operator 已加性注册进 `~/.qwenpaw`(config 备份在
`config.json.bak-operator`),环境健康后即可联调。前端浏览器实操需登录态 + 已部署
operator,留待整体联调。

## 8. 本机部署 / 联调步骤

1. 后端(QwenPaw):把 `deploy-all/qwenpaw/working/` 同步到运行目录并重启,使
   `operator` 智能体注册生效:
   - 同步:`./sync-qwenpaw-working.ps1`(把 working/ 同步到 `~/.qwenpaw`;
     `config.json` 会被覆盖更新,`operator` 的 `agent.json`/`skill.json` 首次 seed)。
   - 重启后端(Windows 单 worker 规避锁竞态:`QWENPAW_APP_WORKERS=1`)。
   - 自检:`GET /api/agents` 应含 `operator`;或对 operator 发一句"新建流程分类"
     看是否回 `qwenpaw:action` 指令。
2. 前端(inoe-ui-monorepo,分支 `tyzg_dev_mk`):`cd packages/inoe-ui && npm run dev`,
   登录后打开右下角「智观AI」,点输入栏「操作」开关 → 输入"帮我新建一个流程分类"
   → 应跳转到流程分类页、弹出新增框、虚拟光标把分类名称/编码填好并高亮「确定」,
   你核对后点「确定」提交。
3. 远端部署:operator 工作区与技能随镜像烧入(离线),`config.json` 注册 operator。

## 9. 限制与下一步

- 当前目录有 6 条已验证操作(流程分类 / 岗位 / 公告 / 参数配置 / 字典类型 / 租户)。
  下一步:跑扫描器把其余候选 review 后逐步并入。
- 目录字段可能没覆盖页面全部必填项(富文本/自定义组件等);未覆盖项由页面提交校验
  兜底、用户补全,不影响安全。
- L3(确认后代点提交)默认关闭;需要时在 runner 接一个对话内"确认"再调
  `vm.submit`。
- 操作模式会话与 gateway 历史分离(operator 自有会话),历史浮层暂只列 gateway。
- 仅支持"新增"类;编辑(需先定位某条记录)、删除(强确认)后续扩展。
- 执行器 DOM 定位(虚拟光标/弹窗/输入框)是 best-effort;定位失败只影响演示,
  数据仍按 model 写入,整体降级而非报错。
```
