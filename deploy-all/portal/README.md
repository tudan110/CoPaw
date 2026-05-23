# Digital Workforce Portal 部署说明

Portal 前端项目的容器化部署配置，支持 Docker 和 Kubernetes (k3s) 部署。

## 目录结构

```
deploy-all/portal/
├── Dockerfile              # 多阶段构建配置
├── docker-compose.yml      # Docker Compose 部署配置
├── nginx.conf              # Nginx 配置文件
├── build-arm.sh            # ARM64 版本构建脚本
└── helm/
    └── digital-workforce-portal/
        ├── Chart.yaml
        ├── values.yaml
        └── templates/
            ├── _helpers.tpl
            ├── deployment.yaml
            └── service.yaml
```

## Docker 构建

在项目根目录执行：

```bash
docker build -f deploy-all/portal/Dockerfile -t digital-workforce-portal:0.1.0 .
```

### ARM64 版本构建

用于 ARM 架构设备（如树莓派、AWS Graviton 等）：

```bash
cd deploy-all/portal
./build-arm.sh
```

导出镜像用于传输：

```bash
docker save -o digital-workforce-portal-arm64.tar digital-workforce-portal:0.1.0
```

在目标设备上加载：

```bash
docker load -i digital-workforce-portal-arm64.tar
```

## Docker Compose 部署

```bash
cd deploy-all/portal
docker-compose up -d
```

可通过环境变量覆盖 Portal 展示名称：

```bash
PORTAL_APP_TITLE="数字员工门户" docker compose up -d
```

## Helm 部署 (k3s)

```bash
# 打包
helm package ./digital-workforce-portal

# 安装
helm install digital-workforce-portal ./digital-workforce-portal-1.0.0.tgz
helm install digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal

# 升级
helm upgrade digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal

# 卸载
helm uninstall digital-workforce-portal
```

## 配置说明

### 镜像配置 (values.yaml)

```yaml
image:
  repository: digital-workforce-portal
  tag: 0.1.0
  pullPolicy: IfNotPresent
```

### 服务配置

```yaml
service:
  type: NodePort
  port: 80
  targetPort: 80
  nodePort: 30083
```

访问地址：`http://<node-ip>:30083`

### 自定义配置

创建自定义 values 文件：

```bash
helm install digital-workforce-portal ./deploy-all/portal/helm/digital-workforce-portal -f my-values.yaml
```

可配置项示例：

```yaml
env:
  timezone: Asia/Shanghai
  PORTAL_APP_TITLE: 数字员工门户
```
