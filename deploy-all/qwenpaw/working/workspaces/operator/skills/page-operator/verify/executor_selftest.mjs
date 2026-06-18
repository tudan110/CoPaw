// 操作模式前端执行器自测(无框架、无网络):最小假 DOM + 桩光标,真实跑
// runner.run(),验证 C 方案的关键行为:跳转 → 开新增弹窗 → 预填 model →
// 不自动提交。前端模块由 run.py 拷进 ./_fe/(并补 .js 扩展名)后运行。
import { extractAction } from './_fe/action.js'
import { registerPage } from './_fe/operator/operableBus.js'
import runner from './_fe/operator/runner.js'

class FakeEl {
  constructor({ text = '', q = {}, style = {}, offsetParent = {} } = {}) {
    this.textContent = text
    this._q = q
    this.style = Object.assign({ display: '' }, style)
    this.offsetParent = offsetParent
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
      '.el-form-item__content input, .el-form-item__content textarea': [input]
    }
  })
const items = [item('分类名称', inputName), item('分类编码', inputCode), item('备注', inputRemark)]
const submitBtn = new FakeEl({ text: '确 定' })
const dialog = new FakeEl({
  q: {
    '.el-form-item': items,
    '.dialog-footer .el-button--primary, .el-dialog__footer .el-button--primary': [submitBtn]
  }
})
const wrapper = new FakeEl({ q: { '.el-dialog': [dialog] } })

globalThis.document = {
  querySelectorAll: (sel) => (sel === '.el-dialog__wrapper' ? [wrapper] : []),
  querySelector: () => null,
  createElement: () => new FakeEl({}),
  getElementById: () => null,
  body: { appendChild() {} },
  head: { appendChild() {} }
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
  const res = await runner.run(payload, { router })
  assert(res && res.ok === true, 'runner 返回 ok')
  assert(pushed.length === 1 && pushed[0] === '/workflow/category', 'router.push 到目标路由')
  assert(vm.open === true, 'handleAdd 被调用(新增弹窗打开)')
  assert(vm.form.categoryName === '财务类', 'categoryName 被预填')
  assert(vm.form.code === 'FIN', 'code 被预填')
  assert(vm.form.remark === undefined, 'remark 未给值则不预填')
  assert(vm._submitted !== true, 'submitForm 不被自动调用(提交交用户)')
  assert(res.dialogFound === true, '执行器定位到弹窗')

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

  console.log(failed === 0 ? '\nFRONTEND-EXECUTOR-SELFTEST: PASS' : `\nFRONTEND-EXECUTOR-SELFTEST: FAIL (${failed})`)
  process.exitCode = failed === 0 ? 0 : 1
})().catch((e) => {
  console.error('SELFTEST ERROR', (e && e.stack) || e)
  process.exitCode = 1
})
