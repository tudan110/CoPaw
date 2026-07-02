# OAuth2 单点登录对接文档（IdP 授权服务端）

> 适用对象：与 inoe-system 对接单点登录的外部系统后端。
> 角色：inoe-system 作为 **OAuth2 授权服务端（IdP）**，外部系统作为客户端（Client）。
> 模式：OAuth2 授权码模式（authorization_code），纯后端（server-to-server）对接，用户按**手机号**匹配。
> 鉴权：请求采用 **HMAC-SHA256 签名 + 时间窗 + nonce 抗重放**，`client_secret` 不在请求中传输。

---

## 1. 对接前置

由 inoe-system 侧分配并下发给外部系统：

| 项 | 说明 | 示例 |
|----|------|------|
| `client_id` | 客户端标识 | `extsysA` |
| `client_secret` | 签名密钥，**仅用于本地计算签名，绝不在请求中传输** | `xxxxxx` |
| `redirect_uri` | 回调地址，需提前登记，精确匹配 | `https://extsysA.example.com/sso/callback` |
| 网关地址 | 接口基址 | `https://<gateway-host>:<port>` |

**接口基址（Base URL）**

- 直连网关：`https://<gateway-host>:<port>/auth/oauth2`
- 经前端 nginx：`https://<host>/prod-api/auth/oauth2`

下文端点路径均相对于接口基址。

---

## 2. 交互流程

```
外部系统后端                              inoe-system (IdP)
    │  ① POST /authorize                       验签(HMAC+时间窗+nonce) + 校验 redirect_uri
    │     (手机号 + 签名)                        校验手机号对应用户存在
    ├────────────────────────────────────►     签发一次性 code（存 Redis，默认 5 分钟）
    │  ◄── { code, redirectUrl } ──────────
    │
    │  ② POST /token                            验签 + 一次性消费 code
    │     (code + 签名)                          按手机号 loginBySmsCode 并签发本系统 JWT
    ├────────────────────────────────────►
    │  ◄── { access_token, ... } ──────────
    │
    │  ③ GET /userinfo                          校验 access_token（JWT + 登录态）
    │     (Authorization: Bearer access_token)
    ├────────────────────────────────────►
    │  ◄── { userId, username, phonenumber, ... }
```

> `code` 一次性消费、默认 5 分钟过期；`access_token` 即本系统 JWT，随用户登出失效。

---

## 3. 签名算法（authorize / token 必须）

每个请求需附带三个字段：`timestamp`、`nonce`、`sign`。

1. **timestamp**：当前毫秒时间戳（字符串），须在服务端时间窗内（默认 ±60 秒）。
2. **nonce**：随机串（建议 UUID 去横线），同一 client 下一次性使用，重复即判为重放。
3. **sign**：对**所有非空签名参数**按 **key 字典序升序**拼成 `key=value&key=value`，再用
   `HMAC-SHA256(clientSecret)` 取**小写 hex**。

**参与签名的字段（仅取非空者）**

- `/authorize`：`clientId`、`redirectUri`、`phonenumber`、`scope`、`state`、`timestamp`、`nonce`
- `/token`：`clientId`、`code`、`redirectUri`、`timestamp`、`nonce`
  （`grantType`、`responseType` 为常量，不参与签名）

**示例（authorize）**

排序拼接后的签名串：

```
clientId=extsysA&nonce=2f...e9&phonenumber=15888888888&redirectUri=https://extsysA.example.com/sso/callback&scope=basic&state=xyz123&timestamp=1782800000000
```

`sign = HMAC_SHA256_hex(clientSecret, 上述串)`

**参考实现（Java，仅依赖 JDK）**

仓库内 `inoe-system-auth/src/test/java/.../oauth2/Oauth2SignDemo.java` 提供可直接运行的签名/请求体生成器，可整体拷贝使用。核心：

```java
String canonical = params.entrySet().stream()          // params 为 TreeMap，已按 key 排序
    .filter(e -> e.getValue() != null && !e.getValue().isEmpty())
    .map(e -> e.getKey() + "=" + e.getValue())
    .collect(Collectors.joining("&"));
Mac mac = Mac.getInstance("HmacSHA256");
mac.init(new SecretKeySpec(clientSecret.getBytes(UTF_8), "HmacSHA256"));
String sign = Hex.encodeHexString(mac.doFinal(canonical.getBytes(UTF_8))); // 小写 hex
```

---

## 4. 端点定义

> 所有请求体为 JSON（`Content-Type: application/json`）。
> **成功**返回原始报文（HTTP 200）；**失败**返回标准错误体（见第 5 节）。

### 4.1 授权端点 —— 签发授权码

`POST /authorize`

| 字段 | 必填 | 说明 |
|------|------|------|
| `clientId` | 是 | 客户端标识 |
| `redirectUri` | 是 | 回调地址，须在登记白名单内 |
| `phonenumber` | 是 | 被授权用户的手机号（身份标识） |
| `timestamp` | 是 | 毫秒时间戳 |
| `nonce` | 是 | 一次性随机串 |
| `sign` | 是 | HMAC-SHA256 签名 |
| `responseType` | 否 | 固定 `code` |
| `scope` | 否 | 授权范围，如 `basic` |
| `state` | 否 | 客户端透传值，原样回带 |

请求示例：

```json
{
  "responseType": "code",
  "clientId": "extsysA",
  "redirectUri": "https://extsysA.example.com/sso/callback",
  "scope": "basic",
  "state": "xyz123",
  "phonenumber": "15888888888",
  "timestamp": "1782800000000",
  "nonce": "2f8c1e7a8b5d4e2f9012ab34cd56ef78",
  "sign": "9a1b2c3d..."
}
```

成功响应（200）：

```json
{
  "code": "3f9c1e7a8b5d4e2f9012ab34cd56ef78",
  "redirectUrl": "https://extsysA.example.com/sso/callback?code=3f9c1e7a8b5d4e2f9012ab34cd56ef78&state=xyz123"
}
```

### 4.2 令牌端点 —— code 换 access_token

`POST /token`

| 字段 | 必填 | 说明 |
|------|------|------|
| `code` | 是 | 上一步获取的授权码 |
| `clientId` | 是 | 客户端标识 |
| `timestamp` | 是 | 毫秒时间戳 |
| `nonce` | 是 | 一次性随机串 |
| `sign` | 是 | HMAC-SHA256 签名 |
| `grantType` | 否 | 固定 `authorization_code` |
| `redirectUri` | 否 | 若上传，须与签发 code 时一致；上传则需参与签名 |

请求示例：

```json
{
  "grantType": "authorization_code",
  "code": "3f9c1e7a8b5d4e2f9012ab34cd56ef78",
  "clientId": "extsysA",
  "redirectUri": "https://extsysA.example.com/sso/callback",
  "timestamp": "1782800000000",
  "nonce": "7d3a9f2e1c4b8a6f0e5d2c1b9a8f7e6d",
  "sign": "5e6f7a8b..."
}
```

成功响应（200）：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9....",
  "token_type": "Bearer",
  "expires_in": 720,
  "scope": "basic"
}
```

| 字段 | 说明 |
|------|------|
| `access_token` | 本系统访问令牌（JWT） |
| `token_type` | 固定 `Bearer` |
| `expires_in` | 有效期，**单位为分钟**（默认 720 = 12 小时，沿用本系统约定，非 OAuth2 标准的秒，请注意换算） |
| `scope` | 授权范围 |

### 4.3 用户信息端点 —— 查询用户

`GET /userinfo`，请求头 `Authorization: Bearer <access_token>`

成功响应（200）：

```json
{
  "userId": "1",
  "username": "zhangsan",
  "nickName": "张三",
  "phonenumber": "15888888888",
  "deptId": "100",
  "email": "zhangsan@example.com"
}
```

---

## 5. 错误响应

失败统一返回 OAuth2 标准错误体（RFC 6749 §5.2），并使用对应 HTTP 状态码；`401` 附带 `WWW-Authenticate` 头。

```json
{ "error": "invalid_grant", "error_description": "code 无效或已过期" }
```

| 场景 | `error` | HTTP | 端点 |
|------|---------|------|------|
| 缺 `client_id`/`phonenumber`/`code`/`timestamp`/`nonce`/`sign`，`redirect_uri` 不在白名单，时间戳超窗 | `invalid_request` | 400 | authorize / token |
| `client_id` 未注册、**签名校验失败** | `invalid_client` | 401 | authorize / token |
| `code` 无效/过期、与 client 或 redirect_uri 不匹配、**nonce 重放** | `invalid_grant` | 400 | token / authorize |
| `grant_type` 非 `authorization_code` | `unsupported_grant_type` | 400 | token |
| 手机号无对应用户、用户停用/冻结 | `access_denied` | 400 | authorize / token |
| `access_token` 无效/过期 | `invalid_token` | 401 | userinfo |
| 服务内部异常 | `server_error` | 500 | 全部 |

---

## 6. 安全说明

1. `client_secret` 仅用于本地计算签名，**绝不出现在任何请求/前端**。
2. 签名机制保证：抓包到的请求**不含明文密钥**，且因时间窗（±60s）+ nonce 一次性，**无法重放**。
3. `code` 一次性消费，换取 `access_token` 后立即失效；默认 5 分钟过期。
4. `redirect_uri` 精确匹配登记白名单，防开放重定向；换 token 时校验与签发 code 时一致。
5. 建议在网关对 `/authorize`、`/token` 增加**源 IP 白名单**；有条件启用 **mTLS**。
6. 全链路必须使用 HTTPS。
7. 信任模型说明：本对接为"可信后端"模型——持有 `client_secret` 的外部系统被信任去断言用户身份（按手机号），故 `client_secret` 必须严格保密。

---

## 7. 联调与自测

仓库内提供：

- 测试样例：`inoe-system-auth/src/test/resources/oauth2-idp-test.http`
  （IntelliJ IDEA 2023.3+ 可一键运行，预请求脚本自动算签名；串联 authorize→token→userinfo，含失败用例）
- 签名生成器 / 参考实现：`inoe-system-auth/src/test/java/.../oauth2/Oauth2SignDemo.java`
  （main 运行，打印含 `timestamp/nonce/sign` 的完整请求体，可粘贴进 .http 或 curl）

curl 速查（`sign` 需先用 Oauth2SignDemo 生成）：

```bash
# ① 取 code
curl -X POST "https://<host>/auth/oauth2/authorize" -H "Content-Type: application/json" \
  -d '{"clientId":"extsysA","redirectUri":"https://extsysA.example.com/sso/callback","phonenumber":"15888888888","scope":"basic","state":"xyz123","timestamp":"<ms>","nonce":"<nonce>","sign":"<sign>"}'

# ② code 换 token
curl -X POST "https://<host>/auth/oauth2/token" -H "Content-Type: application/json" \
  -d '{"grantType":"authorization_code","code":"<上一步code>","clientId":"extsysA","redirectUri":"https://extsysA.example.com/sso/callback","timestamp":"<ms>","nonce":"<nonce>","sign":"<sign>"}'

# ③ 查用户
curl "https://<host>/auth/oauth2/userinfo" -H "Authorization: Bearer <access_token>"
```

---

## 8. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-06-29 | v1.0 | 初版：OAuth2 授权码模式后端对接 |
| 2026-06-29 | v1.1 | 鉴权升级为 HMAC-SHA256 签名 + 时间窗 + nonce 抗重放，client_secret 不再传输 |
