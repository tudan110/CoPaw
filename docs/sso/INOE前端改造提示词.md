# 任务:INOE 登录页支持跳回外部 portal 地址

> 本文档给 `inoe-ui`(`/Users/tudan/Works/inoe/off-domain/inoe-ui-monorepo/packages/inoe-ui`)的开发/AI agent 使用,可直接作为任务提示词粘贴。仅涉及 INOE 前端,不涉及后端、不涉及 portal 侧代码(portal 侧已完成)。

## 背景

QwenPaw portal 现在支持"未登录时跳转到 INOE 登录页,登录成功后自动跳回 portal"。portal 跳转到登录页时,会带上完整的目标地址:

```
http://<INOE-host>:30081/login?redirect=http%3A%2F%2F<portal-host>%3A30083%2Fsso%2Fcallback%3Fredirect%3D...
```

`redirect` 参数值是**已 `encodeURIComponent` 编码**的完整外部 URL(portal 的页面地址,不是站内路径)。

现状:INOE 已经能读到 `redirect` 参数,但只会把它当**站内路径**处理(`router.push`/`next({path})`),不会识别出这是一个外部 URL 并做整页跳转。需要补上这一段逻辑。

**入口1(右上角 AI 图标)不在本次任务范围内,不需要改。**

## 需要改的两处代码

### 1. `src/router/permission.js`(约第 31-36 行)

场景:用户**已登录**,却直接访问带 `redirect` 参数的 `/login?redirect=...`(比如 portal 判断未登录跳过来后,用户其实还留着 INOE 的登录态)。

现有代码:

```javascript
if (to.path === '/login') {
  if (to.query.menuShow) {
    next({ path: `${to.query.redirect || '/'}?menuShow=${to.query.menuShow}` })
  } else {
    next({ path: to.query.redirect || '/' })  // 只会当站内路径处理
  }
}
```

需要改成:如果 `redirect` 是外部 URL 且通过白名单校验,用 `window.location.href` 整页跳转;否则保持原有站内 `next()` 逻辑不变。

### 2. `src/views/login.vue`(约第 194-227 行)

场景:用户在 INOE **登录表单**里输入账号密码提交,登录成功后的跳转分支。

现有代码(简化):

```javascript
.then((info) => {
  if (info == 'success') {
    const service = this.$store.state.user && this.$store.state.user.service
    if (service) {
      window.location.href = service
    } else {
      this.$router.push({ path: this.redirect || '/' }).catch(() => {})
    }
  }
})
```

`service` 是后端登录接口返回的字段,不是我们要用的东西。需要新增一个分支:登录成功后,优先检查 `this.$route.query.redirect`(或组件里已有的 `this.redirect`,需确认这个值当前是否已经是从 `route.query.redirect` 取的)是否是外部 URL 且通过白名单,是的话 `window.location.href = redirect` 整页跳转,优先级高于 `service` 分支(或至少不冲突,两者不会同时出现)。

## 实现建议

写一个共用的校验函数(建议放 `src/utils/`,两处 import):

```javascript
export function resolveExternalRedirect(raw) {
  if (!raw) return null
  let url
  try {
    url = new URL(raw, window.location.origin)
  } catch (e) {
    return null // 非法 URL,不跳
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return null // 防 javascript: 等协议注入
  }
  // portal 与 INOE 前端目前都是同 host、不同 NodePort 部署,
  // 用 hostname 是否与当前页面一致来判断"是否可信目标",
  // 不需要维护一份 IP/域名白名单清单。若以后出现跨 host 部署,
  // 再改成读一个显式配置的白名单数组。
  if (url.hostname !== window.location.hostname) {
    return null
  }
  return url.toString()
}
```

两处调用点都改成:

```javascript
const target = resolveExternalRedirect(to.query.redirect) // 或 this.$route.query.redirect
if (target) {
  window.location.href = target
} else {
  // 原有的站内 next()/router.push 逻辑不变
}
```

## 安全要求(必须做,不能省)

- **必须做 host 校验**,不能拿到 `redirect` 就直接跳——否则是开放重定向(open redirect)漏洞:攻击者可以构造 `http://<INOE-host>:30081/login?redirect=http://钓鱼站` 发给用户,用户在真实 INOE 页面登录后被导向钓鱼站。
- 校验必须用 `new URL()` 解析后比较 `hostname`,**不能用字符串 `startsWith`/正则前缀匹配**(否则 `http://<INOE-host>.evil.com` 或 `//evil.com` 这类会绕过)。
- `try/catch` 兜住非法 URL(比如 `javascript:alert(1)`、格式错误的字符串),解析失败一律当作"不跳"处理。

## 不需要改的地方(供确认范围用)

- `src/utils/auth.js` 的 `setToken`/cookie 逻辑不用动,token 在跳转前已经设置好了(`src/store/modules/user.js` 里 `setToken()` 先于任何跳转执行)。
- `src/layout/components/Navbar.vue` 的 `systemAI` 跳转(入口1)不用动,那是纯配置驱动、已经跑通,不在本次任务范围。
- 后端 `loginConfig` 接口 / `sys.systemAI` 配置项不用动。

## 测试方法

1. **未登录直接跳登录页场景**:浏览器清掉 INOE 的登录 cookie,访问
   `http://<INOE-host>:30081/login?redirect=http%3A%2F%2F<portal-host>%3A30083%2Fsso%2Fcallback`,
   输入账号密码登录,验证登录成功后**整页跳转**到 portal 的 `/sso/callback`,而不是 INOE 首页。
2. **已登录直接访问登录页场景**:保持登录态,直接访问同样带 `redirect` 参数的 `/login?redirect=...` URL,验证会被 `permission.js` 的守卫直接整页跳到 portal,不会先闪一下登录表单。
3. **开放重定向防护测试**:把 `redirect` 换成一个不同 host 的地址,比如 `http://evil.example.com`,验证**不会**跳过去(应该按原逻辑走站内默认路径),确认白名单生效。

## 联调交接点

- portal 侧已经把 `?redirect=` 拼好并发过来了(`portal/src/auth/ssoConfig.ts` 的 `getSsoLoginRedirectUrl`),INOE 侧**不需要**再定义参数名,直接消费现成的 `redirect` query 参数即可。
- 完整背景和整体架构见同目录 [`部署对接说明.md`](./部署对接说明.md)。
