# QwenPaw HTML 产物发布服务方案

## 1. 背景

轻应用工坊中的部分场景会由 QwenPaw 在运行时生成可直接访问的 HTML 报表，例如：

- 基于 CMDB 网络设备数据生成 ECharts 图表页面
- 输出可分享、可访问、可归档的分析结果页面
- 在 Portal 中返回一个可直接打开的链接

这类 HTML 产物本质上是 **QwenPaw 运行时生成的文件**，而不是 Portal 构建产物。

在 Helm 部署场景下，QwenPaw 与 Portal 往往运行在不同 Pod 中：

- HTML 默认生成在 QwenPaw Pod 容器内
- Portal 的 nginx 静态目录位于 Portal Pod 容器内
- 两者文件系统天然隔离

因此，不建议把运行时生成的 HTML 直接写入 Portal 容器的 nginx 目录。

## 2. 问题定义

如果继续采用“QwenPaw 生成 HTML，再想办法塞到 Portal nginx 目录”这条路径，会遇到以下问题：

| 问题 | 说明 |
| --- | --- |
| 跨 Pod 文件同步复杂 | QwenPaw 与 Portal 不共享本地文件系统 |
| 部署强耦合 | Portal 的静态发布方式被运行时产物反向绑定 |
| 容器重建风险 | 未持久化的 HTML 可能随 Pod 重建丢失 |
| 发布链路不清晰 | 谁负责存储、谁负责回收、谁负责权限边界不明确 |
| 本地开发与 Helm 行为不一致 | 代码启动和容器化启动容易形成两套逻辑 |

因此，需要把“HTML 生成”和“HTML 发布”拆开。

## 3. 方案结论

推荐新增一个独立的 **HTML 产物发布服务**（以下简称发布服务）：

1. **QwenPaw 负责生成 HTML**
2. **发布服务负责接收、存储、发布并返回访问链接**
3. **Portal 只负责展示链接或跳转入口**

这意味着 Portal 不再承担运行时 HTML 文件托管职责，避免与 nginx 静态目录强绑定。

## 4. 目标与非目标

### 4.1 目标

- 支持 QwenPaw 生成 HTML 后通过接口上传发布
- 返回稳定、可访问的 URL 给 Portal 或最终用户
- 支持 Helm 部署与代码启动两种场景
- 支持版本、元数据、清理策略和权限边界
- 支持后续扩展为通用报表/静态页面发布能力

### 4.2 非目标

- 不要求第一阶段就做成完整内容管理平台
- 不要求 Portal 自己存储和管理这些 HTML 文件
- 不要求 QwenPaw 长期承担静态资源托管职责
- 不要求第一阶段支持任意复杂前端应用发布

## 5. 总体架构

```text
+-------------------+        +------------------------+        +-------------------+
|      Portal       | <----> |   QwenPaw Backend      | -----> | HTML 发布服务      |
| 展示入口/打开链接  |        | 生成 HTML / 调用上传接口 |        | 存储/发布/元数据管理 |
+-------------------+        +------------------------+        +---------+---------+
                                                                         |
                                                                         v
                                                              +-------------------+
                                                              | 对象存储/共享存储   |
                                                              | MinIO / S3 / OSS  |
                                                              +-------------------+
```

职责边界：

| 组件 | 职责 |
| --- | --- |
| QwenPaw | 调用 skill、聚合数据、生成 HTML、发起上传 |
| 发布服务 | 接收 HTML、落盘/入对象存储、生成 URL、管理元数据 |
| Portal | 展示“打开报表”入口，不直接管理 HTML 文件 |
| 存储层 | 提供持久化能力，避免 Pod 重建导致文件丢失 |

## 6. 为什么不直接写到 Portal nginx

直接把 HTML 发布到 Portal nginx 目录，只在“单机、单容器、强控制部署方式”的前提下看起来简单，但在产品化环境中问题明显：

1. QwenPaw 与 Portal 通常不是一个 Pod
2. nginx 目录不适合承载业务级元数据和生命周期管理
3. 后续如果还有其他系统要发布 HTML，会继续堆到 Portal 上
4. Portal 将被迫承担一个“静态资源发布平台”的角色，职责失衡

因此，Portal 最好只消费发布结果，不持有发布逻辑。

## 7. 发布服务形态建议

第一阶段建议做成一个 **轻量级内部服务**，而不是一开始就做成复杂平台。

### 7.1 MVP 形态

- 一个独立服务或独立后端模块
- 暴露上传、查询、删除、续期等 API
- 底层使用 MinIO / S3 / OSS / PVC
- 返回可直接访问的 URL

### 7.2 后续可扩展为平台

当后续出现更多需求时，再逐步扩展为完整平台能力：

- 多业务系统接入
- 审计与审批
- 可见性控制
- 历史版本管理
- 到期清理与回收站
- 访问统计

## 8. 典型业务链路

以“网络设备报表展示助手”为例：

1. 用户在轻应用工坊创建应用
2. 应用运行时由 QwenPaw 调用 `zgops-cmdb`
3. 按要求查询网络设备模型 `54 (networkdevice)`
4. 访问 CMDB 时先匿名访问，失败后再登录
5. QwenPaw 聚合出按地市、设备类型、厂商、型号等维度的数据
6. QwenPaw 生成内嵌 ECharts 的 HTML 页面
7. QwenPaw 调用发布服务上传 HTML
8. 发布服务返回访问链接
9. Portal 向用户展示“打开报表”按钮

## 9. 部署建议

### 9.1 代码启动场景

本地开发或代码方式启动时，也建议保持与 Helm 一致的模型：

- QwenPaw 不直接把文件写到 Portal 源码目录
- 发布服务可以本地运行，或先用对象存储模拟
- Portal 只接收 URL，不依赖本地静态目录

这样可以避免本地开发时走一套逻辑、线上 Helm 再走另一套逻辑。

### 9.2 Helm 场景

推荐部署形态：

- `portal` Deployment
- `qwenpaw` Deployment
- `html-publisher` Deployment
- `minio` 或外部对象存储

发布服务通过 Ingress 或统一网关暴露访问域名，例如：

```text
https://artifact.example.com
```

或内网统一入口：

```text
https://gateway.example.com/html-artifacts
```

## 10. 存储建议

优先级建议如下：

1. **MinIO / S3 / OSS**
2. **共享文件存储（NFS / NAS / PVC）**
3. **本地 Pod 文件系统（仅限调试，不推荐生产）**

原因：

- 对象存储更适合发布静态 HTML
- 便于生成稳定 URL
- 更适合权限、生命周期、跨实例访问和扩容

## 11. API 设计建议

### 11.1 上传 HTML

```http
POST /api/v1/artifacts/html
Content-Type: application/json
```

请求示例：

```json
{
  "artifactType": "html-report",
  "appId": "network-device-report",
  "versionId": "v20260513-001",
  "title": "网络设备报表展示",
  "entryFile": "index.html",
  "content": "<!doctype html>...</html>",
  "metadata": {
    "scene": "cmdb-networkdevice-report",
    "modelTypeId": 54,
    "modelName": "networkdevice",
    "dimensions": ["city", "dev_class", "vendor", "model"],
    "generatedBy": "qwenpaw"
  }
}
```

响应示例：

```json
{
  "artifactId": "html_01jv2k9abc",
  "url": "https://artifact.example.com/artifacts/html_01jv2k9abc/index.html",
  "expiresAt": null
}
```

### 11.2 查询元数据

```http
GET /api/v1/artifacts/{artifactId}
```

### 11.3 删除或下线

```http
DELETE /api/v1/artifacts/{artifactId}
```

### 11.4 列表查询

```http
GET /api/v1/artifacts?appId=network-device-report
```

## 12. 元数据模型建议

建议为每个 HTML 产物保存元数据，至少包含：

| 字段 | 说明 |
| --- | --- |
| artifactId | 唯一标识 |
| appId | 归属应用 |
| versionId | 归属版本 |
| artifactType | 产物类型，如 `html-report` |
| title | 页面标题 |
| storageKey | 对象存储路径 |
| url | 访问链接 |
| createdAt | 生成时间 |
| createdBy | 生成来源，如 `qwenpaw` |
| visibility | 可见性，如内网公开/鉴权访问 |
| ttl | 生命周期策略 |
| metadata | 业务元数据 |

## 13. HTML 产物要求

为了降低运行复杂度，第一阶段建议生成 **自包含 HTML**：

- 尽量把样式内联
- 尽量把图表配置直接内嵌
- 外部 JS 依赖尽量固定且可控
- 如需引用 ECharts，优先使用稳定来源并评估离线部署方案

更稳的方式是：

- 发布服务支持“单 HTML 文件”发布
- 后续如有需要，再扩展到“HTML + JS/CSS 附件目录”或 zip 解包发布

## 14. 权限与安全建议

根据客户环境可选三种访问模式：

| 模式 | 说明 |
| --- | --- |
| 内网公开 | 拿到链接即可访问，适合内部报表 |
| 网关鉴权 | 通过统一网关、SSO 或 Portal 登录态访问 |
| 临时签名链接 | 适合短时分享和外部协作 |

同时建议：

- 限制允许上传的文件类型
- 对 HTML 内容做大小限制
- 记录上传人、来源应用、发布时间
- 支持下线与过期清理

## 15. 与 QwenPaw 的集成建议

QwenPaw 侧建议新增一个“HTML 发布客户端”抽象，而不是让各个 skill 自己直接发请求。

建议调用链路：

1. skill 或应用逻辑产出结构化图表数据
2. QwenPaw 服务层用统一模板渲染 HTML
3. QwenPaw 服务层调用发布客户端上传
4. 返回 `artifactId` 和 `url`
5. Portal 前端直接展示链接

这样可以避免：

- 每个 skill 各自拼上传逻辑
- 不同应用返回不同字段
- 后续迁移发布服务时需要全量修改 skill

## 16. 与 Portal 的集成建议

Portal 不负责托管文件，只负责消费结果。

Portal 前端可以按以下方式处理：

1. 创建应用或执行应用后，接收后端返回的 `url`
2. 在结果卡片中展示“打开 HTML 报表”
3. 支持新窗口打开
4. 如需要，可增加“复制链接”“查看历史版本”“下线报表”等入口

## 17. 分阶段实施建议

### 第一阶段：MVP

- 定义发布服务基础 API
- 支持单 HTML 上传
- 支持返回稳定访问链接
- Portal 展示链接
- QwenPaw 接入上传逻辑

### 第二阶段：增强

- 增加历史版本与列表查询
- 增加删除、下线、TTL 和定期清理
- 增加鉴权与访问控制
- 支持完整目录或 zip 发布

### 第三阶段：平台化

- 支持多系统共用
- 增加审计、审批、运营统计
- 增加模板中心与报表资产管理

## 18. 最终建议

本问题的核心不在于“把 HTML 放到哪个 Pod 里”，而在于：

> 运行时生成的业务产物，应该由专门的发布能力负责托管，而不是依附于 Portal 的静态目录。

因此，推荐路线是：

1. **QwenPaw 负责生成**
2. **独立发布服务负责存储和发布**
3. **Portal 负责展示访问入口**

这条路线对 Helm 部署最友好，也最利于后续扩展为统一的报表/静态页面发布能力。
