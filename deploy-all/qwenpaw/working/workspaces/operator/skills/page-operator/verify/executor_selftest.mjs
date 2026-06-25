// 操作模式前端执行器自测(无框架、无网络):最小假 DOM + 桩光标,真实跑
// runner.run(),验证 C 方案的关键行为:跳转 → 开新增弹窗 → 预填 model →
// 不自动提交。前端模块由 run.py 拷进 ./_fe/(并补 .js 扩展名)后运行。
import { extractAction, extractOperate, extractOperateAny, normalizeOperate, canonicalizeOperate } from './_fe/action.js'
import { registerPage } from './_fe/operator/operableBus.js'
import runner from './_fe/operator/runner.js'
import { describePage, describeForm } from './_fe/operator/pageSchema.js'
import { pageLeaves, resolvePath as resolveLeafPath } from './_fe/operator/pageMap.js'

class FakeEl {
  constructor({ text = '', q = {}, style = {}, offsetParent = {}, className = '' } = {}) {
    this.textContent = text
    this._q = q
    this.style = Object.assign({ display: '' }, style)
    this.offsetParent = offsetParent
    this.className = className
    this.classList = { add() {}, remove() {} }
  }
  querySelector(sel) {
    const a = this._q[sel]
    return a && a.length ? a[0] : null
  }
  querySelectorAll(sel) {
    return this._q[sel] || []
  }
  getBoundingClientRect() {
    return { left: 0, top: 0, width: 10, height: 10 }
  }
}

const inputName = new FakeEl({})
const inputCode = new FakeEl({})
const inputRemark = new FakeEl({})
const item = (label, input) =>
  new FakeEl({
    q: {
      '.el-form-item__label': [new FakeEl({ text: label })],
      input: [input], // controlType 靠它判类型(=input)
      '.el-form-item__content input, .el-form-item__content textarea': [input]
    }
  })
const items = [item('分类名称', inputName), item('分类编码', inputCode), item('备注', inputRemark)]
const submitBtn = new FakeEl({ text: '确 定' })
const dialog = new FakeEl({
  q: {
    '.el-form-item': items,
    button: [submitBtn],
    '.dialog-footer .el-button--primary, .el-dialog__footer .el-button--primary': [submitBtn]
  }
})
const wrapper = new FakeEl({ q: { '.el-dialog': [dialog] } })

// 模拟 Element 把 el-select 下拉 append 到 body:由 ddlRef 指向当前可见下拉
let ddlRef = null
// 当前是否有"打开的弹窗"。默认无(当前页操作场景);需要弹窗作用域的用例显式置 true,
// 模拟 Element 弹窗可见。这样 getActiveDialog 只在确有弹窗时才返回它(真实环境一致)。
let dialogShown = false
globalThis.document = {
  querySelectorAll: (sel) => {
    if (sel === '.el-dialog__wrapper') return dialogShown ? [wrapper] : []
    if (sel === '.el-select-dropdown') return ddlRef ? [ddlRef] : []
    return []
  },
  querySelector: () => null,
  createElement: () => new FakeEl({}),
  getElementById: () => null,
  body: { appendChild() {} },
  head: { appendChild() {} }
}
// typeIntoInput 会 new Event(...) 派发事件,node 无 DOM,给个最小桩
globalThis.Event = class {
  constructor(type) {
    this.type = type
  }
}

const addBtn = new FakeEl({ text: '新增', q: { '.el-icon-plus': [] } })
const vm = {
  $options: { name: 'Category' },
  open: false,
  form: { categoryId: undefined, categoryName: undefined, code: undefined, remark: undefined },
  $el: new FakeEl({ q: { button: [addBtn] } }),
  handleAdd() {
    this.open = true
  },
  submitForm() {
    this._submitted = true
  },
  $set(obj, k, v) {
    obj[k] = v
  }
}

const noop = () => {}
const anoop = async () => {}
runner.cursor = {
  show: noop,
  hide: noop,
  hideLater: noop,
  say: noop,
  moveTo: anoop,
  moveToEl: anoop,
  clickEl: anoop,
  highlight: noop,
  clearHighlight: noop
}

const pushed = []
const router = {
  currentRoute: { path: '/elsewhere' },
  // 模拟 SPA 路由表:按页面 name 反解真实路径
  resolve: ({ name }) => ({
    route: {
      name,
      path: name === 'Category' ? '/workflow/category' : name === 'WorkProcess' ? '/workflow/work' : '/'
    }
  }),
  push: async (p) => pushed.push(p)
}
const payload = {
  op: 'workflow.category.add',
  action: 'create',
  route: '/workflow/category',
  page: 'Category',
  open: 'handleAdd',
  model: 'form',
  submit: 'submitForm',
  title: '新建流程分类',
  fields: [
    { prop: 'categoryName', label: '分类名称', type: 'input', required: true },
    { prop: 'code', label: '分类编码', type: 'input', required: true },
    { prop: 'remark', label: '备注', type: 'textarea', required: false }
  ],
  params: { categoryName: '财务类', code: 'FIN' },
  risk: 'create'
}

let failed = 0
function assert(cond, msg) {
  if (cond) console.log('  ok -', msg)
  else {
    failed++
    console.error('  FAIL -', msg)
  }
}

;(async () => {
  const block = '```qwenpaw:action\n' + JSON.stringify(payload) + '\n```'
  const ex = extractAction('好的,我来帮您。\n' + block)
  assert(ex && ex.payload && ex.payload.op === 'workflow.category.add', 'extractAction 解析出 op')

  registerPage(vm)
  dialogShown = true // 新增流程会打开弹窗,模拟弹窗可见
  const res = await runner.run(payload, { router })
  assert(res && res.ok === true, 'runner 返回 ok')
  assert(pushed.length === 1 && pushed[0] === '/workflow/category', 'router.push 到目标路由')
  assert(vm.open === true, 'handleAdd 被调用(新增弹窗打开)')
  assert(vm.form.categoryName === '财务类', 'categoryName 被预填')
  assert(vm.form.code === 'FIN', 'code 被预填')
  assert(vm.form.remark === undefined, 'remark 未给值则不预填')
  assert(vm._submitted !== true, 'submitForm 不被自动调用(提交交用户)')
  assert(res.dialogFound === true, '执行器定位到弹窗')
  dialogShown = false // 复位:后续当前页操作场景没有弹窗

  // ---- 触发类(导出,只读 risk=export)场景:自动点击「导出」按钮完成 ----
  const exportBtn = new FakeEl({ text: '导出' })
  const wpVm = {
    $options: { name: 'WorkProcess' },
    $el: new FakeEl({ q: { button: [exportBtn] } }),
    handleExport() {
      this._exported = true
    }
  }
  exportBtn.click = () => wpVm.handleExport() // 模拟按钮 @click="handleExport"
  registerPage(wpVm)
  const exportPayload = {
    op: 'workflow.process.export',
    kind: 'trigger',
    action: 'export',
    route: '',
    page: 'WorkProcess',
    trigger: 'handleExport',
    button: '导出',
    title: '导出工单列表',
    fields: [],
    params: {},
    risk: 'export'
  }
  // 触发指令 route 为空,extractAction 也应能解析(防 route-required 回归)
  const exportBlock = '```qwenpaw:action\n' + JSON.stringify(exportPayload) + '\n```'
  const ex2 = extractAction('好的。\n' + exportBlock)
  assert(ex2 && ex2.payload && ex2.payload.op === 'workflow.process.export', '导出: extractAction 解析空 route 指令')

  const res2 = await runner.run(exportPayload, { router })
  assert(res2 && res2.ok === true && res2.kind === 'trigger', '导出: runner 返回 ok(trigger)')
  assert(res2.clicked === true, '导出(只读): 自动点击按钮')
  assert(wpVm._exported === true, '导出(只读): handleExport 已触发(自动完成)')

  // ---- 选择类(select)场景:聊天 chips 拿页面真实选项 → 光标点中那项 ----
  let selectedLabel = null
  const mkOpt = (label) => {
    const el = new FakeEl({ text: label })
    el.click = () => {
      selectedLabel = label
      ddl.style.display = 'none' // 选中后下拉关闭
    }
    return el
  }
  const ddl = new FakeEl({ q: { '.el-select-dropdown__item': [mkOpt('通知'), mkOpt('公告')] } })
  ddl.style = { display: 'none' }
  ddl.offsetParent = {}
  const selEl = new FakeEl({})
  selEl.click = () => {
    // Element 点 el-select 即 toggle 开/关
    ddl.style.display = ddl.style.display === 'none' ? '' : 'none'
    ddlRef = ddl
  }
  const selItem = new FakeEl({
    q: { '.el-form-item__label': [new FakeEl({ text: '公告类型' })], '.el-select': [selEl] }
  })
  const selDialog = new FakeEl({ q: { '.el-form-item': [selItem] } })
  let askedOptions = null
  const requestChoice = (f, opts) => {
    askedOptions = opts
    return Promise.resolve('公告') // 用户在聊天里点了「公告」
  }
  await runner._fillSelectByChips(
    null,
    selDialog,
    { prop: 'noticeType', label: '公告类型', type: 'select' },
    { requestChoice }
  )
  assert(
    askedOptions && askedOptions.join(',') === '通知,公告',
    'select: chips 拿到页面下拉真实选项'
  )
  assert(selectedLabel === '公告', 'select: 光标点中了所选项「公告」')

  // ---- 单选(radio)场景:聊天 chips → 点中页面 radio ----
  let radioClicked = null
  const mkRadio = (label) => {
    const lab = new FakeEl({ text: label })
    const r = new FakeEl({ q: { '.el-radio__label, .el-radio-button__inner': [lab] } })
    r.click = () => {
      radioClicked = label
    }
    return r
  }
  const rGroup = new FakeEl({ q: { '.el-radio, .el-radio-button': [mkRadio('正常'), mkRadio('停用')] } })
  const rItem = new FakeEl({
    q: { '.el-form-item__label': [new FakeEl({ text: '状态' })], '.el-radio-group': [rGroup] }
  })
  const rDialog = new FakeEl({ q: { '.el-form-item': [rItem] } })
  let radioAsked = null
  await runner._fillRadioByChips(
    null,
    rDialog,
    { prop: 'status', label: '状态', type: 'radio' },
    {
      requestChoice: (f, opts) => {
        radioAsked = opts
        return Promise.resolve('停用')
      }
    }
  )
  assert(radioAsked && radioAsked.join(',') === '正常,停用', 'radio: chips 拿到页面单选项')
  assert(radioClicked === '停用', 'radio: 光标点中了所选项「停用」')

  // ---- 文本输入卡场景:requestInput 填值 → 写进 model ----
  const inpVm = { form: {}, $set(o, k, v) { o[k] = v } }
  const tInput = new FakeEl({})
  const tItem = new FakeEl({
    q: {
      '.el-form-item__label': [new FakeEl({ text: '备注' })],
      '.el-form-item__content input, .el-form-item__content textarea': [tInput]
    }
  })
  const tDialog = new FakeEl({ q: { '.el-form-item': [tItem] } })
  await runner._fillTextByCard(
    inpVm,
    tDialog,
    { prop: 'remark', label: '备注', type: 'textarea' },
    { requestInput: () => Promise.resolve('测试备注内容') },
    'form',
    'textarea',
    ''
  )
  assert(inpVm.form.remark === '测试备注内容', 'input: 输入卡填的值写进了 model')

  // ---- 页面自省(L5 地基):describePage 抽搜索字段 + 工具栏按钮、排除行内按钮 ----
  const sf = (label, ctrlKey) =>
    new FakeEl({
      q: {
        '.el-form-item__label': [new FakeEl({ text: label })],
        [ctrlKey]: [new FakeEl({})]
      }
    })
  const butItem = new FakeEl({
    q: { button: [new FakeEl({ text: '搜索' }), new FakeEl({ text: '重置' })] }
  })
  const queryForm = new FakeEl({
    q: {
      '.el-form-item': [
        sf('流程标识', 'input'),
        sf('流程名称', 'input'),
        sf('流程分类', '.el-select'),
        butItem
      ]
    }
  })
  const rowBtn = new FakeEl({ text: '查看' })
  rowBtn.closest = (sel) => (sel === '.el-table' ? {} : null) // 行内按钮应被排除
  const wpProcVm = {
    $options: { name: 'WorkProcess' },
    $el: new FakeEl({
      q: {
        '.queryForm': [queryForm],
        button: [new FakeEl({ text: '搜索' }), new FakeEl({ text: '重置' }), new FakeEl({ text: '导出' }), rowBtn]
      }
    })
  }
  const schema = describePage(wpProcVm)
  assert(
    schema.search.map((s) => s.label + ':' + s.type).join(',') ===
      '流程标识:input,流程名称:input,流程分类:select',
    '自省: 抽到搜索字段(含控件类型)'
  )
  const actText = schema.actions.map((a) => a.text)
  assert(
    actText.indexOf('搜索') !== -1 && actText.indexOf('导出') !== -1,
    '自省: 抽到工具栏按钮(搜索/导出)'
  )
  assert(actText.indexOf('查看') === -1, '自省: 排除了表格行内按钮')

  // ---- L5 就地操作:runOperate 填搜索框 + 自动点搜索(只读直跑)----
  let queried = false
  const qInput = new FakeEl({})
  qInput.dispatchEvent = () => {}
  const qItem = new FakeEl({
    q: {
      '.el-form-item__label': [new FakeEl({ text: '流程名称' })],
      '.el-form-item__content input, .el-form-item__content textarea': [qInput]
    }
  })
  const searchBtn = new FakeEl({ text: '搜索' })
  searchBtn.click = () => {
    queried = true
  }
  const wpOpVm = {
    $options: { name: 'WpOperate' },
    $el: new FakeEl({ q: { '.el-form-item': [qItem], button: [searchBtn] } })
  }
  registerPage(wpOpVm)
  const res5 = await runner.runOperate(
    {
      mode: 'current',
      page: 'WpOperate',
      fill: [{ label: '流程名称', value: '系统派单' }],
      click: '搜索',
      risk: 'query',
      title: '按流程名称搜索'
    },
    {}
  )
  assert(res5 && res5.ok === true && res5.mode === 'operate', 'operate: runner 返回 ok(operate)')
  assert(qInput.value === '系统派单', 'operate: 搜索框被填入「系统派单」')
  assert(queried === true, 'operate: 只读自动点了「搜索」')

  // ---- L5-7 表格行内操作:describePage 抽行内按钮 + runOperate 点对应行的下载 ----
  let downloaded = null
  const mkRow = (dayText) => {
    const dlBtn = new FakeEl({ text: '下载' })
    dlBtn.click = () => {
      downloaded = dayText
    }
    return new FakeEl({ text: dayText, q: { button: [dlBtn], 'button, a': [dlBtn] } })
  }
  const tableEl = new FakeEl({
    q: {
      '.el-table__row': [mkRow('第1天'), mkRow('第3天')],
      '.el-table__row, tbody tr': [mkRow('第1天'), mkRow('第3天')]
    }
  })
  const reportVm = {
    $options: { name: 'Report' },
    $el: new FakeEl({ q: { '.el-table': [tableEl] } })
  }
  registerPage(reportVm)
  const reportSchema = describePage(reportVm)
  assert((reportSchema.rowActions || []).indexOf('下载') !== -1, '自省: 抽到表格行内按钮(下载)')
  const res6 = await runner.runOperate(
    { mode: 'current', page: 'Report', row: { match: '第3天', click: '下载' }, risk: 'query', title: '下载第3天' },
    {}
  )
  assert(res6 && res6.ok === true && res6.mode === 'row', 'row: runner 返回 ok(row)')
  assert(downloaded === '第3天', 'row: 点中了「第3天」那行的下载(不是别行)')

  // ---- row 按钮模糊匹配:agent 猜"详情",实际按钮是"查看" → 应点中"查看"(同义)----
  let viewed = null
  const mkVRow = (label) => {
    const vb = new FakeEl({ text: '查看' })
    vb.click = () => {
      viewed = label
    }
    const hb = new FakeEl({ text: '办理' })
    return new FakeEl({ text: label, q: { button: [hb, vb], 'button, a': [hb, vb] } })
  }
  const vTable = new FakeEl({ q: { '.el-table__row': [mkVRow('r1'), mkVRow('r2'), mkVRow('r3')] } })
  const vVm = { $options: { name: 'Todo' }, $el: new FakeEl({ q: { '.el-table': [vTable] } }) }
  registerPage(vVm)
  const resV = await runner.runOperate(
    { mode: 'current', page: 'Todo', row: { index: 3, click: '详情' }, risk: 'query' },
    {}
  )
  assert(resV && resV.ok === true && resV.mode === 'row', 'row模糊: runner 返回 ok')
  assert(viewed === 'r3', 'row模糊: 猜"详情"→点中第3行真实按钮"查看"(同义匹配)')

  // ---- L5-5 当前页"新建":自省弹窗字段 + 就地填(model 名未知,走 DOM 打字)----
  const dTitle = new FakeEl({})
  dTitle.dispatchEvent = () => {}
  const dRemark = new FakeEl({})
  dRemark.dispatchEvent = () => {}
  const dItem = (label, inp) =>
    new FakeEl({
      q: {
        '.el-form-item__label': [new FakeEl({ text: label })],
        input: [inp],
        '.el-form-item__content input, .el-form-item__content textarea': [inp]
      }
    })
  const newDialog = new FakeEl({
    q: { '.el-form-item': [dItem('工单标题', dTitle), dItem('备注', dRemark)] }
  })
  const dlgFields = await runner._fillDialogFields({ form: {} }, newDialog, {
    requestInput: (f) => Promise.resolve(f.label === '工单标题' ? '紧急工单' : '尽快处理')
  })
  assert(
    dlgFields.map((f) => f.label + ':' + f.type).join(',') === '工单标题:input,备注:input',
    'open: 自省到弹窗字段'
  )
  assert(
    dTitle.value === '紧急工单' && dRemark.value === '尽快处理',
    'open: 弹窗字段在对话里填好并落到页面(DOM)'
  )

  // ---- L5-6 日期范围(填两端)+ 下拉按值自动选 ----
  const rIn1 = new FakeEl({})
  rIn1.dispatchEvent = () => {}
  const rIn2 = new FakeEl({})
  rIn2.dispatchEvent = () => {}
  const dateItem = new FakeEl({
    q: { '.el-form-item__label': [new FakeEl({ text: '时间' })], '.el-range-input': [rIn1, rIn2] }
  })
  let picked6 = null
  const mkOpt6 = (label) => {
    const el = new FakeEl({ text: label })
    el.click = () => {
      picked6 = label
      ddl6.style.display = 'none'
    }
    return el
  }
  const ddl6 = new FakeEl({ q: { '.el-select-dropdown__item': [mkOpt6('请假'), mkOpt6('报销')] } })
  ddl6.style = { display: 'none' }
  ddl6.offsetParent = {}
  const selEl6 = new FakeEl({})
  selEl6.click = () => {
    ddl6.style.display = ddl6.style.display === 'none' ? '' : 'none'
    ddlRef = ddl6
  }
  const catItem = new FakeEl({
    q: { '.el-form-item__label': [new FakeEl({ text: '流程分类' })], '.el-select': [selEl6] }
  })
  const l6Vm = {
    $options: { name: 'L6' },
    $el: new FakeEl({ q: { '.el-form-item': [dateItem, catItem] } })
  }
  registerPage(l6Vm)
  await runner.runOperate(
    {
      mode: 'current',
      page: 'L6',
      fill: [
        { label: '时间', value: '2026-06-23~2026-06-24' },
        { label: '流程分类', value: '请假' }
      ],
      risk: 'query'
    },
    {}
  )
  assert(rIn1.value === '2026-06-23' && rIn2.value === '2026-06-24', 'date: 日期范围两端都填了')
  assert(picked6 === '请假', 'select: 下拉按值自动选中「请假」')

  // ---- 跨页:runOperate 按页面名解析路由 → 跳转 → 再就地操作(点第2行详情)----
  let pushedTo = null
  const navRouter = {
    currentRoute: { path: '/somewhere' },
    push(p) {
      pushedTo = p
      this.currentRoute.path = p
    }
  }
  const resolvePath = (name) => (name === '自动巡检结果报表' ? '/inspect/report' : '')
  let navHit = null
  const detailBtn = new FakeEl({ text: '详情' })
  detailBtn.click = () => (navHit = 'row2')
  const navRow2 = new FakeEl({ text: '第二条', q: { button: [detailBtn], 'button, a': [detailBtn] } })
  const navTable = new FakeEl({
    q: { '.el-table__row': [new FakeEl({ text: '第一条' }), navRow2] }
  })
  const navVm = {
    $options: { name: 'InspectReport' },
    $el: new FakeEl({ q: { '.el-table': [navTable] } })
  }
  registerPage(navVm) // 模拟跳转后已注册(getCurrentPage 取它)
  await runner.runOperate(
    { mode: 'current', navigate: '自动巡检结果报表', row: { index: 2, click: '详情' }, risk: 'query' },
    { router: navRouter, resolvePath }
  )
  assert(pushedTo === '/inspect/report', 'navigate: 按页面名解析路由并跳转过去')
  assert(navHit === 'row2', 'navigate: 跳转后点中了第2行的详情')

  // navigateFor:只跳转 + 等页面就绪,不执行任何操作(供 L6 感知闭环:跳后再重扫)
  let navOnlyPushed = null
  const navOnlyRouter = {
    currentRoute: { path: '/a' },
    push(p) {
      navOnlyPushed = p
      this.currentRoute.path = p
    }
  }
  registerPage({
    $options: { name: 'ReadyPage' },
    $el: new FakeEl({ q: { button: [new FakeEl({ text: 'x' })] } })
  })
  const navOnly = await runner.navigateFor('随便页', {
    router: navOnlyRouter,
    resolvePath: () => '/target'
  })
  assert(
    navOnly && navOnly.ok === true && navOnlyPushed === '/target',
    'navigateFor: 只跳转到目标路由(不执行操作)'
  )

  // ---- 宽松兜底:agent 写成 YAML/steps,extractOperate 也能抠出 navigate+row ----
  const yamlBlock =
    '```qwenpaw:operate\n' +
    'steps:\n' +
    '  - action: navigate\n' +
    '    target: 工单管理\n' +
    '  - action: row\n' +
    '    index: 2\n' +
    '    filter: 待办\n' +
    '    detail: true\n' +
    '```'
  const exYaml = extractOperate('好的。\n' + yamlBlock)
  assert(
    exYaml && exYaml.payload && exYaml.payload.navigate === '待办工单管理',
    'loose: YAML 把 filter(待办)拼进页面名 → 待办工单管理'
  )
  assert(
    exYaml &&
      exYaml.payload.row &&
      exYaml.payload.row.index === 2 &&
      exYaml.payload.row.click === '详情',
    'loose: YAML 抠出 row{index:2, click:详情}'
  )
  assert(exYaml && exYaml.payload.risk === 'query', 'loose: 只读默认 risk=query(可自动执行)')

  // ---- 防 404:navigate 解析不到真实页面时,绝不跳转、中止 ----
  let pushed404 = null
  const res404 = await runner.runOperate(
    { mode: 'current', navigate: '不存在的页面', row: { index: 1, click: '详情' }, risk: 'query' },
    { router: { currentRoute: { path: '/x' }, push: (p) => (pushed404 = p) }, resolvePath: () => '' }
  )
  assert(res404 && res404.ok === false && res404.reason === 'page-not-resolved', 'navigate: 解析不到则中止')
  assert(pushed404 === null, 'navigate: 解析不到时绝不跳转(防 404)')

  // ---- 转译层:canonicalize 把各种走样掰成标准 schema + 校验 ----
  const c1 = canonicalizeOperate({ row: 1, button: '流转记录', risk: 'query' })
  assert(
    c1.ok && c1.payload.row && c1.payload.row.index === 1 && c1.payload.row.click === '流转记录',
    '转译: row数字+button别名 → row{index:1,click:流转记录}'
  )
  const c2 = canonicalizeOperate({ mode: 'current', risk: 'query' })
  assert(c2.ok === false, '转译: 没有任何操作 → 校验不过(ok:false)')
  const c3 = canonicalizeOperate({ row: { index: 2, click: '删除' } })
  assert(c3.ok && c3.payload.risk === 'delete', '转译: 按"删除"文案推断 risk=delete')
  const c4 = normalizeOperate('not json at all 乱写一通')
  assert(c4.ok === false, '转译: 彻底没结构 → ok:false(交二次转译/回问,不乱跑)')
  const nlBlock =
    '```qwenpaw:operate\nsteps:\n  - navigate: 工单管理\n  - operate: |\n      定位列表中第3条记录,点击该行进入详情\n```'
  const exNl = extractOperate('好的。\n' + nlBlock)
  assert(
    exNl && exNl.payload.navigate === '工单管理' && exNl.payload.row && exNl.payload.row.index === 3,
    '转译: navigate+自然语言"第3条详情" → navigate=工单管理, row.index=3'
  )
  // 真实 agent 输出格式①:steps + "fill: 字段 = 值" + click(搜索场景)
  const exFill = extractOperate('x\n```qwenpaw:operate\nsteps:\n  - fill: 流程名称 = 系统派单\n  - click: 搜索\n```')
  assert(
    exFill &&
      exFill.payload.fill &&
      exFill.payload.fill[0].label === '流程名称' &&
      exFill.payload.fill[0].value === '系统派单' &&
      exFill.payload.click === '搜索',
    '转译(真实): "fill: 字段 = 值" → fill[{流程名称,系统派单}] + click 搜索'
  )
  // 真实 agent 输出格式②:action:click + row + button(下载场景)
  const exDl = extractOperate('x\n```qwenpaw:operate\naction: click\nrow: 2\nbutton: 下载\n```')
  assert(
    exDl && exDl.payload.row && exDl.payload.row.index === 2 && exDl.payload.row.click === '下载',
    '转译(真实): action:click+row:2+button:下载 → row{index:2,click:下载}'
  )
  // 真实 agent 输出格式③(联调实采,跨页):navigate + action:查看 + target:第3行
  const exA = extractOperate(
    'x\n```qwenpaw:operate\nnavigate: 自动巡检结果报表\naction: 查看\ntarget: 第3行\n```'
  )
  assert(
    exA &&
      exA.payload.navigate === '自动巡检结果报表' &&
      exA.payload.row &&
      exA.payload.row.index === 3 &&
      exA.payload.row.click === '查看',
    '转译(真实③跨页): navigate+action:查看+target:第3行 → navigate=报表,row{3,查看}'
  )
  // 真实 agent 输出格式④(联调实采,本页):action:click + target:row=3, 查看
  // 关键:target 是"行"而非页面,绝不能误抠成 navigate=row=3
  const exB = extractOperate('x\n```qwenpaw:operate\naction: click\ntarget: row=3, 查看\n```')
  assert(
    exB &&
      !exB.payload.navigate &&
      exB.payload.row &&
      exB.payload.row.index === 3 &&
      exB.payload.row.click === '查看',
    '转译(真实④本页): action:click+target:row=3,查看 → 无navigate,row{3,查看}'
  )
  // 真实⑤(联调实采):agent 写成【无 fence 的 steps 列表】(action/page/ref/value)
  const exSteps = extractOperateAny(
    '当前页是待办工单，需要先跳转再搜索 👇\n\nsteps:\n  - action: navigate\n    page: 日志\n  - action: fill\n    ref: 搜索关键词\n    value: "主机"\n  - action: click\n    ref: 搜索'
  )
  assert(
    exSteps &&
      exSteps.payload.navigate === '日志' &&
      exSteps.payload.fill &&
      exSteps.payload.fill[0].label === '搜索关键词' &&
      exSteps.payload.fill[0].value === '主机' &&
      exSteps.payload.click === '搜索',
    '转译(真实⑤无fence steps): navigate+fill(ref/value)+click 全抠出'
  )
  // 真实⑥(联调实采):fence 内 navigate + actions 列表 + CSS/Playwright selector 寻址
  const exActs = extractOperateAny(
    '先跳转再操作👇\n\n```qwenpaw:operate\nnavigate: 日志中心\nactions:\n  - type: fill\n    selector: input[placeholder*="搜索"] , input[type="search"]\n    value: 主机\n  - type: click\n    selector: button:has-text("搜索")\n```'
  )
  assert(
    exActs &&
      exActs.payload.navigate === '日志中心' &&
      exActs.payload.fill &&
      exActs.payload.fill[0].value === '主机' &&
      exActs.payload.click === '搜索',
    '转译(真实⑥actions+selector): 从 has-text/placeholder 抠出"搜索"文字线索'
  )
  // 真实⑦:无 fence steps,只 navigate+click(漏洞扫描场景)
  const exScan = extractOperateAny(
    'steps:\n  - action: navigate\n    page: 漏洞扫描\n  - action: click\n    ref: 扫描'
  )
  assert(
    exScan && exScan.payload.navigate === '漏洞扫描' && exScan.payload.click === '扫描',
    '转译(真实⑦无fence): navigate+click(扫描)'
  )
  // 真实⑧(联调实采):navigate + steps,步骤用「动作名为 key + 箭头」`- fill: 搜索框 → 主机`
  const exArrow = extractOperateAny(
    '正在为您跳转 👇\n\n```qwenpaw:operate\nnavigate: 日志中心\nsteps:\n  - fill: 搜索框 → 主机\n  - click: 搜索\n```'
  )
  assert(
    exArrow &&
      exArrow.payload.navigate === '日志中心' &&
      exArrow.payload.fill &&
      exArrow.payload.fill[0].value === '主机' &&
      exArrow.payload.click === '搜索',
    '转译(真实⑧ key+箭头): - fill: 搜索框 → 主机 / - click: 搜索 全抠出'
  )
  // 普通对话不应被误解析成操作(extractOperate 严格 fence;Any 仅操作模式用)
  assert(
    extractOperate('好的，日志中心可以在左侧菜单找到，您直接点进去就行。') === null,
    '转译: 普通对话(无 fence)→ extractOperate 不误判'
  )

  // ---- L6 批量导入:upload → DataTransfer 注入 el-upload → 高亮确定(写,不自动点)----
  globalThis.DataTransfer = class {
    constructor() {
      this._f = []
      this.items = { add: (f) => this._f.push(f) }
    }
    get files() {
      return this._f
    }
  }
  const impFileInput = new FakeEl({})
  impFileInput.dispatchEvent = () => {}
  const impConfirm = new FakeEl({ text: '确定' })
  let impConfirmClicked = false
  impConfirm.click = () => {
    impConfirmClicked = true
  }
  const impVm = {
    $options: { name: 'DeviceImport' },
    $el: new FakeEl({
      q: {
        '.el-upload': [new FakeEl({})],
        '.el-upload input[type=file]': [impFileInput],
        button: [impConfirm]
      }
    })
  }
  registerPage(impVm)
  let askedAccept = null
  const resImp = await runner.runOperate(
    { mode: 'current', upload: true, click: '确定', accept: '.xlsx,.xls', risk: 'create', title: '批量导入设备' },
    {
      requestUpload: (opts) => {
        askedAccept = opts.accept
        return Promise.resolve({ name: 'devices.xlsx' })
      }
    }
  )
  assert(resImp && resImp.ok === true && resImp.mode === 'import', 'import: runner 返回 ok(import)')
  assert(
    impFileInput.files && impFileInput.files.length === 1 && impFileInput.files[0].name === 'devices.xlsx',
    'import: 文件被注入页面 el-upload(DataTransfer)'
  )
  assert(askedAccept === '.xlsx,.xls', 'import: 聊天上传卡带了 accept 限定')
  assert(impConfirmClicked === false, 'import: "确定"不自动点(写操作,留用户确认)')

  // ---- 真机"新建/提交"链路逼出的修复(Fix1 作用域 / Fix2 必填 / Fix3 确认卡 / Fix4 确认才执行)----
  dialogShown = true // 模拟弹窗打开(el-dialog append-to-body)
  // Fix1:弹窗开着时,就地 fill 落进【弹窗】输入框(不是页面上)——根治"找不到弹窗元素"
  inputName.value = ''
  await runner.runOperate(
    { mode: 'current', fill: [{ label: '分类名称', value: '测试密钥' }], risk: 'query' },
    {}
  )
  assert(inputName.value === '测试密钥', 'Fix1: 弹窗开着 → fill 落进弹窗输入框(作用域感知)')

  // Fix4:写操作(click 确定)——没确认只高亮、用户点了卡片(confirmed)才真点
  let submitClicked = false
  submitBtn.click = () => {
    submitClicked = true
  }
  await runner.runOperate({ mode: 'current', click: '确定', risk: 'create' }, {})
  assert(submitClicked === false, 'Fix4: 写操作未确认 → 只高亮不点')
  await runner.runOperate({ mode: 'current', click: '确定', risk: 'create', confirmed: true }, {})
  assert(submitClicked === true, 'Fix4: 写操作已确认(点了卡片)→ 真正点击「确定」')

  // Fix3:确认提交卡——requestSubmit 返回 true → 真正点弹窗「确定」;取消则不点
  submitClicked = false
  let askedSubmit = null
  const resCs = await runner._confirmSubmit(
    dialog,
    {
      requestSubmit: (o) => {
        askedSubmit = o
        return Promise.resolve(true)
      }
    },
    { title: '确认提交' },
    'open'
  )
  assert(askedSubmit && askedSubmit.label === '确定', 'Fix3: 提交前弹「确认提交」卡(带按钮名)')
  assert(
    resCs && resCs.submitted === true && submitClicked === true,
    'Fix3: 用户点确认 → 真正点弹窗「确定」提交'
  )
  submitClicked = false
  const resCancel = await runner._confirmSubmit(
    dialog,
    { requestSubmit: () => Promise.resolve(false) },
    {},
    'open'
  )
  assert(
    resCancel.submitted === false && submitClicked === false,
    'Fix3: 用户取消 → 不提交'
  )
  dialogShown = false

  // Fix2:describeForm 标出必填字段(名称*必填、备注选填)
  const reqForm = new FakeEl({
    q: {
      '.el-form-item': [
        new FakeEl({
          className: 'el-form-item is-required',
          q: { '.el-form-item__label': [new FakeEl({ text: '名称' })], input: [new FakeEl({})] }
        }),
        new FakeEl({
          className: 'el-form-item',
          q: { '.el-form-item__label': [new FakeEl({ text: '备注' })], input: [new FakeEl({})] }
        })
      ]
    }
  })
  const reqFields = describeForm(reqForm)
  assert(
    reqFields.length === 2 &&
      reqFields[0].label === '名称' &&
      reqFields[0].required === true &&
      reqFields[1].required === false,
    'Fix2: describeForm 标出必填(名称必填、备注选填)'
  )

  // 兜底(真机关键):agent 经常把"新建"发成 click(而非 open)。前端检测到"点新建→弹窗
  // 打开"就接管:列真实字段总览 + 给「确认提交」卡。**完全不依赖 agent 出 open/submit 指令。**
  let noteText = null
  let askedNew = null
  submitClicked = false
  addBtn.click = () => {
    dialogShown = true // 模拟点"新增"后弹窗打开
  }
  dialogShown = false
  await runner.runOperate(
    { mode: 'current', page: 'Category', click: '新增', risk: 'query' },
    {
      note: (t) => {
        noteText = t
      },
      requestSubmit: (o) => {
        askedNew = o
        return Promise.resolve(true)
      }
    }
  )
  assert(/分类名称/.test(noteText || ''), '兜底: 点"新增"弹出弹窗 → 前端列出真实字段总览(不靠 agent)')
  assert(askedNew && submitClicked === true, '兜底: 点"新增"后给「确认提交」卡,确认即真提交')
  dialogShown = false

  // ---- 全系统页面地图解析(整系统接入 / 防 404 / 修 bug#2)----
  const routers = [
    {
      path: '/workorder',
      component: 'Layout',
      meta: { title: '工单管理' },
      children: [
        { path: 'todo', component: 'workorder/todo', meta: { title: '待办工单' } },
        { path: 'done', component: 'workorder/done', meta: { title: '已办工单' } }
      ]
    },
    {
      path: '/inspect',
      component: 'Layout',
      meta: { title: '自动巡检' },
      children: [{ path: 'report', component: 'inspect/report', meta: { title: '自动巡检结果报表' } }]
    }
  ]
  const leaves = pageLeaves(routers)
  const leafTitles = leaves.map((l) => l.title)
  const leafPaths = leaves.map((l) => l.path)
  assert(
    leafTitles.includes('待办工单') && leafTitles.includes('自动巡检结果报表'),
    'pageMap: 抽到真实叶子页(全系统可跳转清单)'
  )
  assert(
    !leafTitles.includes('工单管理') && !leafTitles.includes('自动巡检'),
    'pageMap: 父级菜单容器被排除(防 404)'
  )
  assert(resolveLeafPath(routers, '待办工单') === '/workorder/todo', 'pageMap: 精确叶子名 → 叶子路径')
  assert(
    resolveLeafPath(routers, '自动巡检结果报表') === '/inspect/report',
    'pageMap: 点名报表页 → 报表叶子路径(修 bug#2:不当成当前页)'
  )
  const parentResolved = resolveLeafPath(routers, '工单管理')
  assert(
    parentResolved === '' || leafPaths.includes(parentResolved),
    'pageMap: 父菜单名永不解析成容器路径(只会是叶子或空,杜绝 404)'
  )
  assert(resolveLeafPath(routers, '查无此页xyz') === '', 'pageMap: 解析不到 → 空串(上层据此中止跳转)')

  console.log(failed === 0 ? '\nFRONTEND-EXECUTOR-SELFTEST: PASS' : `\nFRONTEND-EXECUTOR-SELFTEST: FAIL (${failed})`)
  process.exitCode = failed === 0 ? 0 : 1
})().catch((e) => {
  console.error('SELFTEST ERROR', (e && e.stack) || e)
  process.exitCode = 1
})
