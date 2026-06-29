# 响应格式

本文档描述设备接口返回的结构，以及 Agent 应如何把原始字段转成用户可读信息。

## 顶层结构

返回值为对象，常见字段如下：

- `code`：业务状态码，`200` 表示成功
- `msg`：结果消息
- `total`：总记录数
- `rows`：设备记录数组

推荐判断顺序：

1. 先看 `code`
2. 再看 `total`
3. 再处理 `rows`

## 设备记录字段

| 字段名 | 类型 | 说明 | 常见用途 |
|--------|------|------|----------|
| `id` | str | 设备唯一标识 | 内部标识，一般不必优先展示 |
| `devName` | str | 设备名称 | 列表、搜索、明细 |
| `devNo` | str | 设备编号 | 补充标识 |
| `manageIp` | str | 管理 IP 地址 | 精确查找、表格展示 |
| `vendorId` | str | 厂商标识 | 厂商分布、明细 |
| `modelId` | str | 设备型号 | 型号统计、明细 |
| `devClass` | str | 设备类型 | 类型统计、筛选 |
| `delStatus` | str | 设备状态 | 在线/离线统计 |
| `resStatus` | str | 资源状态 | 正常/异常筛选 |
| `countryId` | str | 国家/地区 | 地域维度补充信息 |
| `accessTime` | str | 最后访问时间 | 异常排查辅助字段 |
| `createdBy` | str | 创建人 | 一般不优先展示 |
| `createdTime` | str | 创建时间 | 明细场景可用 |
| `updatedBy` | str | 更新人 | 明细场景可用 |
| `updatedTime` | str | 更新时间 | 明细场景可用 |
| `rmDeviceExtend` | object | 扩展信息 | 只有用户明确要求时再展开 |

## 展示字段优先级

默认优先展示：

1. `devName`
2. `manageIp`
3. `delStatus`
4. `resStatus`
5. `modelId`
6. `vendorId`
7. `devClass`

只有在单设备详情或用户明确要求时，再展示创建时间、更新时间、扩展信息。

## 常见值映射

### 厂商 `vendorId`

| 值 | 建议展示 |
|----|----------|
| `HW` | 华为 |
| `ZX` | 中兴 |
| `H3` | H3C |
| 其他 | 原样或“其他厂商” |

### 类型 `devClass`

| 值 | 建议展示 |
|----|----------|
| `route` | 路由器 |
| `switch` | 交换机 |
| 其他 | 原样或“其他类型” |

### 设备状态 `delStatus`

| 值 | 建议展示 |
|----|----------|
| `online` | 在线 |
| `offline` | 离线 |
| 其他 | 原样 |

### 资源状态 `resStatus`

| 值 | 建议展示 |
|----|----------|
| `normal` | 正常 |
| `abnormal` | 异常 |
| 其他 | 原样 |

## 空值处理

- 空字符串或缺失字段：展示为 `-`
- `rows = []`：明确回复“未找到匹配设备”
- `total = 0`：不要继续做分布或占比分析

## Agent 输出建议

- 原始字段名可用于内部处理，但用户回复尽量用中文含义
- 表格列名建议使用：设备名称、管理 IP、设备状态、资源状态、型号、厂商、类型
- 统计场景下，不需要把每条记录全部展开

## 返回示例

```json
{
  "total": 34,
  "rows": [
    {
      "id": "3e688223abc8435d8d4a9f6ad7210f0b",
      "devName": "DKCZZ-HUAWEI-P",
      "devNo": "DKCZZ-HUAWEI-P",
      "manageIp": "172.27.34.1",
      "vendorId": "HW",
      "modelId": "NE5000E",
      "devClass": "route",
      "delStatus": "online",
      "resStatus": "abnormal",
      "countryId": "北京市",
      "accessTime": "2025-06-30",
      "createdBy": "xiaok",
      "createdTime": "2025-06-30 10:31:34"
    }
  ],
  "code": 200,
  "msg": "查询成功"
}
```