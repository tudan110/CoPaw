# CNOS Inoe Agent 部署说明

一体化部署配置，包含 digital-workforce-portal 和 qwenpaw 两个子应用。

> **已有 PVC 的 Agent/Skill 更新**：不要使用旧 `/app/.working.backup` 或全目录 rsync/delete 操作。当前 Helm qwenpaw chart 通过 `managed-seed-sync` initContainer 从 `/app/share/qwenpaw-seed` 自动更新 `working/workspaces` 中受管的 Agent 静态文件和 Skills，并保护 jobs、secret、知识库 data、运行状态和用户自装 Skill。同步脚本位于镜像内 `/usr/local/bin/sync_managed_seed.py`。

## 目录结构

```
deploy-all/
├── docker/                     # docker run 方式部署说明
├── helm/
│   └── cnos-inoe-agent/
│       ├── Chart.yaml          # 父 Chart 配置，声明依赖
│       ├── values.yaml         # 统一配置文件
│       └── charts/             # 子 Chart 目录（软链接）
│           ├── digital-workforce-portal -> ../../../portal/helm/digital-workforce-portal
│           └── qwenpaw -> ../../../qwenpaw/helm/qwenpaw
├── portal/                     # Portal 前端部署配置
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── nginx.conf
│   ├── build-arm.sh
│   └── helm/digital-workforce-portal/
└── qwenpaw/                    # QwenPaw 应用部署配置
    ├── Dockerfile
    ├── entrypoint.sh
    ├── build-arm.sh
    ├── data/
    ├── config/
    └── helm/qwenpaw/
```

## 应用说明

| 应用 | 端口 | NodePort | 说明 |
|------|------|----------|------|
| digital-workforce-portal | 80 | 30083 | Portal 纯前端 |
| qwenpaw | 8088 | 30088 | QwenPaw 主后端 |

### 服务依赖关系

前端 `digital-workforce-portal` 通过 nginx 反向代理访问后端 `qwenpaw` API：

- 前端请求 `/copaw-api/*` → nginx 代理 → `qwenpaw:8088/*`
- 前端请求 `/portal-api/*` → nginx 代理 → `qwenpaw:8088/api/portal/*`

说明：
- `/portal-api/*` 由 QwenPaw 主进程通过自定义路由扩展提供
- 具体代码位于 `src/qwenpaw/extensions/api/portal_backend.py`
- 外部系统接入逻辑位于 `src/qwenpaw/extensions/integrations/`

## 快速部署

```bash
# 生成包含两个已展开子 Chart 的完整交付包
./deploy-all/helm/package-cnos-inoe-agent.sh

# 首次安装或后续升级（默认使用 qwenpaw:latest 和 portal:0.1.0）
helm upgrade --install cnos-inoe-agent \
  ./deploy-all/helm/cnos-inoe-agent-1.0.0.tgz \
  -n cnos-iomp --create-namespace --wait --timeout 10m

# 卸载（PVC 按 Chart 的 keep 策略保留）
helm uninstall cnos-inoe-agent -n cnos-iomp
```

交付包内已包含展开后的 qwenpaw 和 portal 子 Chart，离线服务器不需要访问本机仓库路径或解析软链接。

## 离线一键部署 / 升级（k3s / k8s）

把以下文件放在离线服务器同一目录后执行 `deploy-offline.sh`
（位于 `deploy-all/helm/`）：

- `qwenpaw-amd64.tar`、`digital-workforce-portal-amd64.tar`（`docker save` 产物）
- chart 包 `cnos-inoe-agent-<版本>.tgz`（`helm package` 产物）
- `deploy-offline.sh`

```bash
chmod +x deploy-offline.sh
NAMESPACE=cnos-iomp ./deploy-offline.sh            # 导入镜像 + helm upgrade（自动触发 Pod 更新）
NAMESPACE=cnos-iomp EXTRA_VALUES=my-values.yaml ./deploy-offline.sh
./deploy-offline.sh --skip-import                  # 镜像已导入，只执行 helm upgrade
```

脚本要点：

1. **k3s 用 containerd，不是 docker**：导入镜像必须用
   `k3s ctr images import <tar>`（脚本自动探测 k3s ctr / ctr / docker）。
   对 k3s 执行 `docker load` 看似成功，实际集群根本看不到该镜像。
2. **固定 tag 镜像必须先导入，再执行 helm upgrade**：Chart 会使用 Helm release
   revision 更新 Pod template，自动触发新 Pod；不需要再手工执行 `kubectl rollout restart`。
3. **已有 PVC 的受管 Agent/Skill 文件会由新 Pod 的 initContainer 自动同步**：新 Pod 从
   `/app/share/qwenpaw-seed` 更新受管静态文件；不会覆盖 jobs、secret、知识库 data、
   sessions、设置数据库或用户自装 Skill。不要再按 `SYNC_GUIDE.md` 或旧 Shell SOP
   对 PVC 做全目录 rsync/delete。
4. 多节点集群：镜像须在每个可调度节点导入，或使用内网镜像仓库。

### 升级已有环境的 Agent 与 Skill

新镜像中的 `managed-seed-sync` initContainer 会在新 Pod 启动前执行：

```bash
python3 /usr/local/bin/sync_managed_seed.py \
  --apply --yes \
  --seed /app/share/qwenpaw-seed \
  --target /app/working
```

同步器只更新 `workspaces` 中 seed manifest 声明的 Agent 静态字段、workspace prompt 文件和受管 Skill 代码；每个 Skill 在 staging 目录准备完成后原子切换。它不会触碰知识库
`data/`、jobs、secret、settings、sessions、memory、`skill_pool` 或用户自装 Skill。

需要人工检查时，在 Pod 内执行：

```bash
python3 /usr/local/bin/sync_managed_seed.py \
  --seed /app/share/qwenpaw-seed \
  --target /app/working
```

升级后若知识库中已经存在旧版本解析出的乱码记录，仍需在门户「知识库管理」中用
「删除」按钮清除并重新上传。

## 自定义配置

```bash
# 使用自定义 values 文件
helm install cnos-inoe-agent ./deploy-all/helm/cnos-inoe-agent -f my-values.yaml

# 覆盖单个配置
helm install cnos-inoe-agent ./deploy-all/helm/cnos-inoe-agent \
  --set digital-workforce-portal.service.nodePort=32080 \
  --set qwenpaw.service.nodePort=32088


# 实际部署示例 -- 大装置
helm install cnos-inoe-agent ./cnos-inoe-agent-1.0.0.tgz -n cnos-iomp \
  --set-string digital-workforce-portal.env.PORTAL_APP_TITLE="智观 AI" \
  --set-string digital-workforce-portal.env.PORTAL_SSO_ENABLED="true" \
  --set-string qwenpaw.env.INOE_API_BASE_URL="http://192.168.134.96:30080"

# 实际部署示例 -- 北京环境
helm install cnos-inoe-agent ./cnos-inoe-agent-1.0.0.tgz -n cnos-iomp \
  --set-string digital-workforce-portal.env.PORTAL_APP_TITLE="智观 AI" \
  --set-string digital-workforce-portal.env.PORTAL_SSO_ENABLED="true" \
  --set-string qwenpaw.env.INOE_API_BASE_URL="http://10.3.39.246:30080"
```

### 单点登录（SSO）

标准 k3s 部署下 portal 固定在 `:30083`，INOE 前端固定在 `:30081`，二者同主机，
所以开启 SSO 只需要一个开关，无需额外配置登录地址或端口：

```bash
helm install cnos-inoe-agent ./cnos-inoe-agent-1.0.0.tgz -n cnos-iomp \
  --set-string digital-workforce-portal.env.PORTAL_APP_TITLE="智观 AI" \
  --set-string digital-workforce-portal.env.PORTAL_SSO_ENABLED="true"
```

Portal 会自动推导 INOE 登录地址为 `http://<当前访问的 host>:30081/login`。只有
INOE 前端不在标准 `30081` 端口，或者跟 portal 不同主机时，才需要额外覆盖
`PORTAL_SSO_INOE_PORT` / `PORTAL_SSO_LOGIN_URL`（见下方环境变量表）。

如果只是 INOE 前端端口不是默认 `30081`，可以在部署时显式指定端口：

```bash
helm install cnos-inoe-agent ./cnos-inoe-agent-1.0.0.tgz -n cnos-iomp \
  --set-string digital-workforce-portal.env.PORTAL_APP_TITLE="智观 AI" \
  --set-string digital-workforce-portal.env.PORTAL_SSO_ENABLED="true" \
  --set-string digital-workforce-portal.env.PORTAL_SSO_INOE_PORT="30081"
```

如果同时还需要跳到非同主机或非标准登录页，再额外设置
`PORTAL_SSO_LOGIN_URL="http://<ip>:<port>/login"`。

### 常用环境变量设置

部署时可通过 `--set-string` 覆盖环境变量，格式为 `<子chart名>.env.<变量名>=<值>`：

```bash
helm install cnos-inoe-agent ./cnos-inoe-agent-1.0.0.tgz -n cnos-iomp \
  --set-string digital-workforce-portal.env.PORTAL_APP_TITLE="智观 AI" \
  --set-string digital-workforce-portal.env.PORTAL_SSO_ENABLED="true" \
  --set-string qwenpaw.env.INOE_API_BASE_URL="http://192.168.134.96:30080" \
  --set-string qwenpaw.env.INOE_API_TOKEN="<your_jwt_token>" \
  --set-string qwenpaw.env.INOE_API_TIMEOUT="60" \
  --set-string qwenpaw.env.QWENPAW_APP_WORKERS="2" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_ROUTE_TIMEOUT="5" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_CACHE_TTL="30" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_DEGRADED_COOLDOWN="30" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED="true" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL="300" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT="20" \
  --set-string qwenpaw.env.QWENPAW_PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES="1"
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PORTAL_APP_TITLE` | Portal 页面标题 | - |
| `PORTAL_SSO_ENABLED` | 是否启用 INOE 单点登录（`true`/`false`） | `false` |
| `PORTAL_SSO_INOE_PORT` | INOE 前端 NodePort（同主机部署时用于自动推导登录地址，一般无需设置） | `30081` |
| `PORTAL_SSO_LOGIN_URL` | INOE 登录页完整地址（跟 portal 不同主机，或端口非标准时才需要，格式 `http://<ip>:<port>/login`） | - |
| `INOE_API_BASE_URL` | 智观告警平台接口地址 | `http://192.168.134.96:30080` |
| `INOE_API_TOKEN` | 智观平台 JWT Token | - |
| `INOE_API_TIMEOUT` | 接口请求超时(秒) | `60` |
| `QWENPAW_APP_WORKERS` | QwenPaw 后端 worker 进程数 | `2` |
| `QWENPAW_APP_BACKLOG` | QwenPaw 后端监听 backlog | `2048` |
| `QWENPAW_APP_TIMEOUT_KEEP_ALIVE` | QwenPaw 后端 keep-alive 超时(秒) | `5` |
| `QWENPAW_PORTAL_REAL_ALARM_ROUTE_TIMEOUT` | Portal 告警列表前台等待超时(秒) | `5` |
| `QWENPAW_PORTAL_REAL_ALARM_CACHE_TTL` | 告警列表缓存 TTL(秒) | `30` |
| `QWENPAW_PORTAL_REAL_ALARM_DEGRADED_COOLDOWN` | 告警后端异常降级冷却(秒) | `30` |
| `QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_ENABLED` | 是否启用告警自动接管分析 | `true` |
| `QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_INTERVAL` | 自动接管轮询间隔(秒) | `300` |
| `QWENPAW_PORTAL_REAL_ALARM_AUTO_TAKEOVER_LIMIT` | 单次轮询最大处理告警数 | `20` |
| `QWENPAW_PORTAL_REAL_ALARM_MAX_ACTIVE_ANALYSES` | 同时进行的最大分析任务数 | `1` |

## 相关文档

- [QwenPaw 镜像打包说明](./QWENPAW_IMAGE_BUILD.md)
- [从本地用户目录同步到 deploy-all 指南](./SYNC_GUIDE.md)
- [docker run 启动说明](./docker/README.md)

## 访问地址

部署完成后访问：

- Portal: `http://<node-ip>:30083`
- QwenPaw: `http://<node-ip>:30088`

## 单独部署子应用

如需单独部署某个子应用：

```bash
# 单独部署 portal
helm install digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal

# 单独部署 qwenpaw
helm install qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw
```
