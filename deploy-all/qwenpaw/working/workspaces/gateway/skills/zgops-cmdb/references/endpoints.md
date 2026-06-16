# ZGOPS CMDB 接口说明

## 基础信息

- 基础地址：来自 `.env` 中的 `ZGOPS_BASE_URL`
- CMDB 入口：`/cmdb/`
- 登录页跳转：`/user/login?redirect=%2Fcmdb%2F`

## 已确认的页面路由

- `/cmdb/dashboard`
- `/cmdb/topoviews`
- `/cmdb/instances/types/:typeId?`
- `/cmdb/tree_views`
- `/cmdb/adc`
- `/cmdb/ipam`
- `/cmdb/dcim`
- `/cmdb/preference`
- `/cmdb/batch`
- `/cmdb/ci_types`

## 已确认的接口

### 模型与元数据

- `GET /api/v0.1/ci_types?per_page=200` — 获取 CI 模型列表
- `GET /api/v0.1/ci_types/<type_id>/attributes` — 获取模型属性列表
- `GET /api/v0.1/ci_type_relations?ci_type_id=<type_id>` — 获取模型关系配置
- `GET /api/v0.1/relation_types` — 获取关系类型列表

### 官方文档中可用的 CMDB 接口

- `GET /api/v0.1/ci/s` — 查询 CI 实例
- `POST /api/v0.1/ci` — 创建 CI
- `PUT /api/v0.1/ci` 或 `/api/v0.1/ci/<ci_id>` — 更新 CI
- `DELETE /api/v0.1/ci/<ci_id>` — 删除 CI
- `GET /api/v0.1/ci_relations/s` — 从根 CI 出发查询关系图
- `POST /api/v0.1/ci_relations/<src_ci_id>/<dst_ci_id>` — 创建 CI 关系
- `DELETE /api/v0.1/ci_relations/<cr_id>` — 删除 CI 关系

## 已确认的关系类型

- `contain`
- `deploy`
- `install`
- `connect`

## 已确认的模型快照

- 业务: 产品, 应用
- 部门组织: 部门, 用户
- 操作系统: 操作系统
- 计算资源: 物理机, 虚拟机, 内存, 硬盘, 网卡, 宿主机, 虚拟化平台
- 数据存储: 数据库, mySQL, PostgreSQL
- IP地址管理: 子网, IP地址, 作用范围
- 网络设备: 网络设备, 端口, 链路列表
- 中间件: Redis, Kafka, elasticsearch, Nginx, Apache
- 容器: kubernetes, docker
- 数据中心: 区域, 数据中心, 机房, 机柜, 带宽线路
- Other: 合同信息

## 已确认的场景关系图

### 业务 / 应用

- `product -> contain -> project`
- `project -> deploy -> vserver`
- `project -> contain -> mysql`
- `project -> contain -> PostgreSQL`
- `project -> contain -> database`
- `project -> contain -> Kafka`
- `project -> contain -> redis`
- `project -> contain -> elasticsearch`

### DCIM / 基础设施

- `dcim_region -> contain -> dcim_idc`
- `dcim_idc -> contain -> dcim_server_room`
- `dcim_server_room -> contain -> dcim_rack`
- `dcim_rack -> contain -> PhysicalMachine`
- `dcim_rack -> contain -> networkdevice`
- `networkdevice -> contain -> port`
- `networkdevice -> contain -> link`

### IPAM

- `ipam_scope -> contain -> ipam_subnet`
- `ipam_subnet -> contain -> ipam_address`

### 安装 / 运行时

- `operatingsystem -> install -> PhysicalMachine`
- `operatingsystem -> install -> vserver`
- `vserver -> deploy -> docker`
- `docker -> deploy -> database / redis / PostgreSQL / mysql / Kafka / elasticsearch`
