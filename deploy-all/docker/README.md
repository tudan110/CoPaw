# QwenPaw `docker run` 启动说明

本文档说明如何**不通过 Helm Chart**，直接使用 `docker run` 启动 QwenPaw 与 Portal。

适用场景：

- 服务器上没有 Kubernetes / k3s
- 需要快速验证镜像
- 希望手工控制端口、挂载目录和容器重启策略

---

## 0. 离线一键部署（推荐）

> ⚠️ 本目录脚本只适用于 **docker run 直跑**。生产环境用 k3s/k8s + Helm
> 部署时，请改用 `deploy-all/helm/deploy-offline.sh`（k3s 的 containerd
> 无法通过 `docker load` 导入镜像）。

把 `deploy-offline.sh`（本目录）与两个镜像 tar 放在离线服务器的同一目录，执行：

```bash
chmod +x deploy-offline.sh
./deploy-offline.sh                # docker load 两个镜像 + 重建两个容器
./deploy-offline.sh --skip-load    # 镜像已 load 过，只重建容器
```

脚本做的事 = 本文档第 2–7 节的全部手工步骤：load 镜像、建持久化目录与
`qwenpaw-net` 网络、按下文参数重建 `qwenpaw` 与 `portal` 容器、等待就绪并
打印访问地址。端口 / 数据目录 / 镜像名等均可用环境变量覆盖（见脚本头部
配置区），例如：

```bash
DATA_ROOT=/srv/qwenpaw QWENPAW_HOST_PORT=18088 ./deploy-offline.sh
```

> 注意：`docker load` 只导入镜像，**不会**自动更新正在运行的容器 ——
> 脚本因此总是 stop + rm + run 重建。挂载卷中的旧技能代码同样不会被
> 镜像覆盖，升级技能请按 `deploy-all/SYNC_GUIDE.md` 同步卷内文件。

---

## 1. 部署目标

`deploy-all` 这一套一体化部署包含两个容器：

1. **qwenpaw**：后端主服务，默认监听容器内 `8088`
2. **portal**：前端门户，默认监听容器内 `80`

二者关系与 Helm 版一致：

- Portal 请求 `/copaw-api/*` → 转发到 `qwenpaw:8088/*`
- Portal 请求 `/portal-api/*` → 转发到 `qwenpaw:8088/api/portal/*`

所以在 `docker run` 方式下，**Portal 必须能够通过容器名 `qwenpaw` 访问后端**。

---

## 2. 前置准备

### 2.1 准备镜像

如果本机还没有镜像，可在项目根目录构建：

```bash
# 构建 QwenPaw 后端镜像
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .

# 构建 Portal 前端镜像
docker build -f deploy-all/portal/Dockerfile -t digital-workforce-portal:0.1.0 .
```

如果镜像已经由 CI、私有仓库或 `docker load` 提供，可直接跳过这一步。

### 2.2 准备 data 目录

QwenPaw 镜像依赖 `deploy-all/qwenpaw/data` 中的数据。打包前请先按现有流程准备：

1. 执行仓库根目录的 `./sync-qwenpaw-working.sh`
2. 按 `deploy-all/SYNC_GUIDE.md` 同步本地目录到：
   - `deploy-all/qwenpaw/data/qwenpaw/`
   - `deploy-all/qwenpaw/data/qwenpaw.secret/`

相关文档：

- `deploy-all/QWENPAW_IMAGE_BUILD.md`
- `deploy-all/SYNC_GUIDE.md`

---

## 3. 推荐目录规划

建议在目标服务器上准备独立的持久化目录，例如：

```bash
mkdir -p /data/qwenpaw/working
mkdir -p /data/qwenpaw/working.secret
```

说明：

- `/data/qwenpaw/working` 对应容器内 `/app/working`
- `/data/qwenpaw/working.secret` 对应容器内 `/app/working.secret`
- 如果挂载目录是空的，QwenPaw 容器首次启动时会自动用镜像内置备份初始化内容

---

## 4. 创建 Docker 网络

先创建一个独立网络，让 Portal 能通过 `qwenpaw` 这个名字访问后端：

```bash
docker network create qwenpaw-net
```

如果网络已存在，可忽略报错或先执行：

```bash
docker network rm qwenpaw-net
docker network create qwenpaw-net
```

---

## 5. 启动 qwenpaw 后端

```bash
docker run -d \
  --name qwenpaw \
  --restart unless-stopped \
  --network qwenpaw-net \
  -p 30088:8088 \
  -e TZ=Asia/Shanghai \
  -e QWENPAW_PORT=8088 \
  -e QWENPAW_DISABLED_CHANNELS=imessage \
  -v /data/qwenpaw/working:/app/working \
  -v /data/qwenpaw/working.secret:/app/working.secret \
  qwenpaw:latest
```

### 关键说明

- `--name qwenpaw`
  - **不要随便改名**
  - Portal 的 nginx 配置默认代理到 `http://qwenpaw:8088`
- `-p 30088:8088`
  - 对外暴露后端端口，和 Helm 方案中的 `NodePort 30088` 保持一致
- `-v /data/qwenpaw/working:/app/working`
  - 持久化工作目录
- `-v /data/qwenpaw/working.secret:/app/working.secret`
  - 持久化模型配置、Provider 配置等敏感目录

---

## 6. 启动 Portal 前端

```bash
docker run -d \
  --name portal \
  --restart unless-stopped \
  --network qwenpaw-net \
  -p 30083:80 \
  -e TZ=Asia/Shanghai \
  -e PORTAL_APP_TITLE="数字员工门户" \
  digital-workforce-portal:0.1.0
```

### 关键说明

- `-p 30083:80`
  - 对外暴露前端端口，和 Helm 方案中的 `NodePort 30083` 保持一致
- `PORTAL_APP_TITLE`
  - 可按环境修改，例如：
    - `PORTAL_APP_TITLE="智观 AI"`
    - `PORTAL_APP_TITLE="数字员工门户"`

Portal 容器本身不需要显式传后端地址；只要它和 `qwenpaw` 容器在同一个 Docker 网络中，就会通过 nginx 配置自动转发。

---

## 7. 启动后验证

### 7.1 查看容器状态

```bash
docker ps --filter name=qwenpaw
docker ps --filter name=portal
```

### 7.2 查看日志

```bash
docker logs -f qwenpaw
docker logs -f portal
```

### 7.3 健康检查

```bash
# 检查 Portal
curl http://127.0.0.1:30083/health

# 检查 QwenPaw
curl http://127.0.0.1:30088/
```

### 7.4 访问地址

```bash
Portal:  http://<server-ip>:30083
QwenPaw: http://<server-ip>:30088
```

---

## 8. 常用维护命令

### 停止容器

```bash
docker stop portal qwenpaw
```

### 启动已存在容器

```bash
docker start qwenpaw
docker start portal
```

### 重启容器

```bash
docker restart qwenpaw
docker restart portal
```

### 删除容器

```bash
docker rm -f portal qwenpaw
```

> 删除容器不会删除挂载目录中的持久化数据。

---

## 9. 升级方式

如果镜像更新了，推荐按下面顺序升级：

```bash
docker rm -f portal qwenpaw

# 重新拉取或重新构建镜像
# docker pull <your-registry>/qwenpaw:<tag>
# docker pull <your-registry>/digital-workforce-portal:<tag>

# 然后按本文第 5、6 节重新 docker run
```

只要保留以下挂载目录，工作数据就不会丢失：

- `/data/qwenpaw/working`
- `/data/qwenpaw/working.secret`

---

## 10. 常见问题

### 10.1 Portal 打开后接口报 502 / 504

优先检查：

1. `qwenpaw` 容器是否真的启动成功
2. `portal` 和 `qwenpaw` 是否在同一个 Docker 网络
3. 后端容器名是否就是 `qwenpaw`

可直接执行：

```bash
docker inspect portal --format '{{json .NetworkSettings.Networks}}'
docker inspect qwenpaw --format '{{json .NetworkSettings.Networks}}'
```

### 10.2 QwenPaw 启动后没有数据

通常是以下原因之一：

1. 打包镜像前没有按 `SYNC_GUIDE.md` 同步 `deploy-all/qwenpaw/data`
2. 挂载了空目录，但容器初始化失败
3. 挂载目录路径写错，导致没有真正挂载到 `/app/working` 或 `/app/working.secret`

### 10.3 想改成别的对外端口

只需要改 `-p` 左侧宿主机端口即可，例如：

```bash
-p 38088:8088
-p 38083:80
```

容器内端口仍保持：

- qwenpaw：`8088`
- portal：`80`

---

## 11. 最小可执行示例

```bash
docker network create qwenpaw-net

docker run -d \
  --name qwenpaw \
  --restart unless-stopped \
  --network qwenpaw-net \
  -p 30088:8088 \
  -e TZ=Asia/Shanghai \
  -v /data/qwenpaw/working:/app/working \
  -v /data/qwenpaw/working.secret:/app/working.secret \
  qwenpaw:latest

docker run -d \
  --name portal \
  --restart unless-stopped \
  --network qwenpaw-net \
  -p 30083:80 \
  -e TZ=Asia/Shanghai \
  -e PORTAL_APP_TITLE="数字员工门户" \
  digital-workforce-portal:0.1.0
```

如果你当前是 Helm 部署用户，可以把这份文档理解为：**把原来 Chart 里两个 Deployment + Service 的能力，改成手工 `docker run` 启动两套容器**。
