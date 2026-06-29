# 图表使用指南

本文档说明设备分析结果何时该用图表、该选什么图，以及输出时的统一约束。

**重要规则**：

- 所有图表只使用 ECharts 或 Mermaid
- 优先使用 ECharts
- 不要生成或保存 PNG 图片文件
- 图表要能在页面直接渲染

## 选型原则

| 场景 | 推荐图表 | 说明 |
|------|----------|------|
| 厂商分布 / 状态分布 / 类型占比 | 饼图 / 环形图 | 适合展示占比 |
| 型号 Top N / 厂商数量对比 | 柱状图 | 适合展示数量差异 |
| 单一关键指标，如在线率 | 仪表盘 | 适合单指标强调 |
| 明细清单 | Markdown 表格 | 不建议强行图表化 |
| 综合报告 | 1 个图表 + 1 个表格起步 | 避免堆太多图 |

## 推荐使用 ECharts

ECharts 更适合：

- 交互式提示
- 更复杂的布局
- 更好的观感
- 更稳定的柱状图、环形图、仪表盘

### ECharts 使用方法

使用 ```echarts 代码块包裹 JSON 配置：

```echarts
{
  "title": {
    "text": "设备厂商分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item"
  },
  "legend": {
    "orient": "vertical",
    "left": "left"
  },
  "series": [
    {
      "name": "厂商分布",
      "type": "pie",
      "radius": "50%",
      "data": [
        { "value": 20, "name": "华为" },
        { "value": 9, "name": "中兴" },
        { "value": 4, "name": "H3C" },
        { "value": 2, "name": "其他" }
      ],
      "emphasis": {
        "itemStyle": {
          "shadowBlur": 10,
          "shadowOffsetX": 0,
          "shadowColor": "rgba(0, 0, 0, 0.5)"
        }
      }
    }
  ]
}
```

### ECharts 优势

- 图表类型更丰富
- 悬停提示更友好
- 更适合正式报告场景
- 响应式表现更好

## Mermaid 备选方案

Mermaid 适合快速、轻量的可视化，但复杂场景优先 ECharts。

## 图表类型选择

### 1. Markdown 表格
适用于：详细数据列表

**示例：设备型号统计表**

| 序号 | 设备型号 | 数量 | 厂商 | 占比 | 设备示例 |
|------|----------|------|------|------|----------|
| 1 | CX600-X8A | 6 | HW | 17% | DKCZZ-HUAWEI-DCLEAF-1, DKCZZ-HUAWEI-DCLEAF-2... |
| 2 | NE8100 | 6 | HW | 17% | DKCZZ-HUAWEI-SPINE-1, DKCZZ-HUAWEI-SPINE-2... |
| 3 | ZXCTN 9000-18EA | 4 | ZX | 11% | DKCZZ-ZTE-SSPINE-1, DKCZZ-ZTE-SSPINE-2... |
| 4 | RX8800-08 | 4 | H3 | 11% | DKCZZ-H3C-SPINE-1, DKCZZ-H3C-SPINE-2... |
| 5 | ATN980C | 2 | HW | 6% | BJ-BJ-WLKJC-A-1, BJ-BJ-WLKJC-A-2... |
| ... | ... | ... | ... | ... | ... |

### 2. Mermaid 饼图

适用于：厂商分布、状态分布、类型分布

**示例：厂商分布**

```mermaid
pie title 厂商分布（共35台）
    "华为 (HW)" : 20
    "中兴 (ZX)" : 9
    "H3C (H3)" : 4
    "其他" : 2
```

**示例：设备状态分布**

```mermaid
pie title 设备状态分布（共35台）
    "在线" : 35
    "离线" : 0
```

**示例：资源状态分布**

```mermaid
pie title 资源状态分布（共35台）
    "正常" : 33
    "异常" : 2
```

### 3. Mermaid 条形图

适用于：设备型号分布、设备类型分布

**示例：设备型号分布**

```mermaid
graph TD
    subgraph 设备型号分布[设备型号分布 - 共35台]
        A[CX600-X8A: 6台 17%]
        B[NE8100: 6台 17%]
        C[ZXCTN 9000-18EA: 4台 11%]
        D[RX8800-08: 4台 11%]
        E[ATN980C: 2台 6%]
        F[CTSN-S3100: 2台 6%]
        G[NE40E-X8: 2台 6%]
        H[NE5000E: 2台 6%]
        I[ZXCTN 9000-8EA: 2台 6%]
        J[ZXR10 M6000-18S: 2台 6%]
        K[其他: 3台 9%]
    end
```

### 4. Mermaid 仪表盘

适用于：关键指标展示、在线率等

**示例：设备在线率**

```mermaid
gauge
    title 设备在线率
    "在线" : 100
```

### 5. Mermaid 混合图表

适用于：综合分析报告

**示例：设备综合分析**

```mermaid
graph LR
    subgraph 设备总数[设备总数: 35台]
        A1[在线: 35台]
        A2[离线: 0台]
    end

    subgraph 厂商分布[厂商分布]
        B1[华为: 20台<br/>57%]
        B2[中兴: 9台<br/>26%]
        B3[H3C: 4台<br/>11%]
        B4[其他: 2台<br/>6%]
    end

    subgraph 资源状态[资源状态]
        C1[正常: 33台<br/>94%]
        C2[异常: 2台<br/>6%]
    end

    设备总数 --> 厂商分布
    设备总数 --> 资源状态
```

### 6. 综合报告模板

适用于：完整的多维度分析

```mermaid
graph TB
    subgraph 设备概览[设备概览]
        total[设备总数: 35台]
        online[在线: 35台 100%]
        offline[离线: 0台 0%]
    end

    subgraph 厂商分析[厂商分析]
        hw[华为: 20台 57%]
        zx[中兴: 9台 26%]
        h3[H3C: 4台 11%]
        other[其他: 2台 6%]
    end

    subgraph 型号分析[型号分析]
        top1[CX600-X8A: 6台]
        top2[NE8100: 6台]
        top3[ZXCTN 9000-18EA: 4台]
        top4[RX8800-08: 4台]
    end

    subgraph 状态分析[状态分析]
        res_normal[资源正常: 33台 94%]
        res_abnormal[资源异常: 2台 6%]
    end

    total --> 厂商分析
    total --> 型号分析
    total --> 状态分析
```

## 图表使用建议

### 展示顺序

1. 先给一句结论
2. 再放 1 个最关键图表
3. 再放详细表格
4. 最后补观察点

### 设计原则

- 保持简洁，不要一口气输出过多图表
- 标题里尽量带总数或时间点
- 占比场景优先饼图 / 环形图
- 对比场景优先柱状图
- 明细场景优先表格

### 什么时候不要画图

- 只有 1~2 条记录时
- 用户只要一个简单数字时
- 数据不完整时
- 用户明确只要列表时