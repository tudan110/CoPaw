# CNOS Inoe Agent 部署说明

一体化部署配置，包含 digital-workforce-portal 和 qwenpaw 两个子应用。

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
# 更新依赖（首次部署前需要执行）
helm dependency update ./deploy-all/helm/cnos-inoe-agent

# 安装
helm install cnos-inoe-agent ./deploy-all/helm/cnos-inoe-agent

# 升级
helm upgrade cnos-inoe-agent ./deploy-all/helm/cnos-inoe-agent

# 卸载
helm uninstall cnos-inoe-agent
```

## 自定义配置

```bash
# 使用自定义 values 文件
helm install cnos-inoe-agent ./deploy-all/helm/cnos-inoe-agent -f my-values.yaml

# 覆盖单个配置
helm install cnos-inoe-agent ./deploy-all/helm/cnos-inoe-agent \
  --set digital-workforce-portal.service.nodePort=32080 \
  --set qwenpaw.service.nodePort=32088
```

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
