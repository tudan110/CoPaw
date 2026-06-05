# QwenPaw 部署说明

QwenPaw 应用的容器化部署配置，包含前后端一体化镜像，支持 Docker 和 Kubernetes (k3s) 部署。

## 目录结构

```
deploy-all/qwenpaw/
├── Dockerfile                  # 多阶段构建配置
├── entrypoint.sh               # 容器入口脚本
├── build-arm.sh                # ARM64 版本构建脚本
├── config/
│   └── supervisord.conf.template  # Supervisor 配置模板
└── helm/
    └── qwenpaw/
        ├── Chart.yaml
        ├── values.yaml
        └── templates/
            ├── _helpers.tpl
            ├── deployment.yaml
            ├── service.yaml
            └── pvc.yaml
```

## 应用说明

QwenPaw 是一个前后端一体化应用：
- **前端**: console（React 应用）
- **后端**: Python 应用（qwenpaw）
- **端口**: 8088
- **特性**: 内置 Chromium 浏览器，支持自动化任务
- **Portal 扩展路由**: 容器启动时会自动写入 `custom_channels/portal_api.py`，确保 `/api/portal/*` 可供 Portal 前端访问
- **后端启动器**: 容器默认使用 `qwenpaw.extensions.runtime.worker_app`，支持通过环境变量配置多 worker

## Docker 构建

在项目根目录执行：

```bash
docker build -f deploy-all/qwenpaw/Dockerfile -t qwenpaw:latest .
```

### ARM64 版本构建

用于 ARM 架构设备（如树莓派、AWS Graviton 等）：

```bash
cd deploy-all/qwenpaw
./build-arm.sh
```

导出镜像用于传输：

```bash
docker save -o qwenpaw-arm64.tar qwenpaw:latest
```

在目标设备上加载：

```bash
docker load -i qwenpaw-arm64.tar
```

## Helm 部署 (k3s)

```bash
# 打包
helm package ./deploy-all/qwenpaw/helm/qwenpaw

# 安装
helm install qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw

# 升级
helm upgrade qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw

# 卸载
helm uninstall qwenpaw
```

## 配置说明

### 镜像配置 (values.yaml)

```yaml
image:
  repository: qwenpaw
  tag: latest
  pullPolicy: IfNotPresent
```

### 后端 worker 配置

```yaml
env:
  QWENPAW_APP_WORKERS: "2"
  QWENPAW_APP_BACKLOG: "2048"
  QWENPAW_APP_TIMEOUT_KEEP_ALIVE: "5"
```

### 服务配置

```yaml
service:
  type: NodePort
  port: 8088
  targetPort: 8088
  nodePort: 30088
```

访问地址：`http://<node-ip>:30088`

### 持久化存储

```yaml
persistence:
  enabled: true
  size: 10Gi
  workingDir:
    mountPath: /app/working
  secretDir:
    mountPath: /app/working.secret
```

### 环境变量

```yaml
env:
  QWENPAW_PORT: "8088"
  QWENPAW_DISABLED_CHANNELS: "imessage"
```

### 自定义配置

创建自定义 values 文件：

```bash
helm install qwenpaw ./deploy-all/qwenpaw/helm/qwenpaw -f my-values.yaml
```
