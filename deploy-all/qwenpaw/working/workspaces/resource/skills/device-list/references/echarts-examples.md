# ECharts 图表示例

本文档提供 `device-list` 技能最常用的 ECharts 模板。目标不是覆盖所有图表类型，而是让 Agent 能快速挑一个合适模板直接改数据。

## 使用规则

- 优先复用本文模板，不要临时拼很复杂的配置
- 一次回复通常 1 个图表就够了
- 先写结论，再贴图表
- 图表标题尽量带总数，例如“共 35 台设备”

## 模板 1：厂商分布饼图

适用场景：厂商占比、状态占比、类型占比。

```echarts
{
  "title": {
    "text": "设备厂商分布",
    "subtext": "共35台设备",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c}台 ({d}%)"
  },
  "legend": {
    "orient": "vertical",
    "left": "left"
  },
  "series": [
    {
      "name": "厂商分布",
      "type": "pie",
      "radius": "56%",
      "data": [
        { "value": 20, "name": "华为" },
        { "value": 9, "name": "中兴" },
        { "value": 4, "name": "H3C" },
        { "value": 2, "name": "其他" }
      ]
    }
  ]
}
```

## 模板 2：资源状态环形图

适用场景：正常/异常、在线/离线这类二分类或少量分类。

```echarts
{
  "title": {
    "text": "资源状态分布",
    "subtext": "共35台设备",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item"
  },
  "legend": {
    "bottom": 0,
    "left": "center"
  },
  "series": [
    {
      "name": "资源状态",
      "type": "pie",
      "radius": ["42%", "68%"],
      "data": [
        { "value": 33, "name": "正常" },
        { "value": 2, "name": "异常" }
      ]
    }
  ]
}
```

## 模板 3：型号 Top N 柱状图

适用场景：型号数量对比、厂商数量对比、类型数量对比。

```echarts
{
  "title": {
    "text": "设备型号 Top 5",
    "left": "center"
  },
  "tooltip": {
    "trigger": "axis",
    "axisPointer": {
      "type": "shadow"
    }
  },
  "grid": {
    "left": 48,
    "right": 24,
    "bottom": 72,
    "top": 56
  },
  "xAxis": {
    "type": "category",
    "data": ["CX600-X8A", "NE8100", "ZXCTN 9000-18EA", "RX8800-08", "ATN980C"],
    "axisLabel": {
      "rotate": 30
    }
  },
  "yAxis": {
    "type": "value",
    "name": "数量（台）"
  },
  "series": [
    {
      "name": "设备数量",
      "type": "bar",
      "barMaxWidth": 40,
      "data": [6, 6, 4, 4, 2],
      "itemStyle": {
        "color": "#5470c6"
      }
    }
  ]
}
```

## 模板 4：按厂商堆叠状态柱状图

适用场景：比较不同厂商下的在线/离线、正常/异常分布。

```echarts
{
  "title": {
    "text": "各厂商设备状态分布"
  },
  "tooltip": {
    "trigger": "axis",
    "axisPointer": {
      "type": "shadow"
    }
  },
  "legend": {
    "data": ["在线", "离线"]
  },
  "xAxis": {
    "type": "category",
    "data": ["华为", "中兴", "H3C", "其他"]
  },
  "yAxis": {
    "type": "value",
    "name": "数量（台）"
  },
  "series": [
    {
      "name": "在线",
      "type": "bar",
      "stack": "total",
      "data": [20, 9, 4, 2]
    },
    {
      "name": "离线",
      "type": "bar",
      "stack": "total",
      "data": [0, 0, 0, 0]
    }
  ]
}
```

## 模板 5：在线率仪表盘

适用场景：单一关键指标展示。只有一个核心百分比时再用。

```echarts
{
  "title": {
    "text": "设备在线率",
    "left": "center"
  },
  "series": [
    {
      "type": "gauge",
      "min": 0,
      "max": 100,
      "progress": {
        "show": true,
        "width": 12
      },
      "axisLine": {
        "lineStyle": {
          "width": 12
        }
      },
      "detail": {
        "formatter": "{value}%",
        "fontSize": 24,
        "offsetCenter": [0, "60%"]
      },
      "data": [
        {
          "value": 100,
          "name": "在线率"
        }
      ]
    }
  ]
}
```

## 选图速查

| 用户问题 | 推荐图表 |
|----------|----------|
| 按厂商统计设备数量 | 饼图 |
| 资源状态正常/异常分布 | 环形图 |
| 设备型号 Top 5 | 柱状图 |
| 各厂商在线/离线对比 | 堆叠柱状图 |
| 当前在线率是多少 | 仪表盘 |

## 不建议使用图表的情况

- 只需要返回一个总数
- 只有 1~2 条记录
- 数据还没全量拿到
- 用户明确说只要表格或列表

## 最后检查

输出图表前，确认：

1. 标题和数据一致
2. 总数没有写错
3. 中文标签可直接阅读
4. 图表和文字结论一致