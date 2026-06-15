# ECharts 示例

本文档提供告警数据可视化的 ECharts 示例代码，可直接复制替换数据使用。

## 示例 1：告警级别分布（环形图）

```echarts
{
  "title": {
    "text": "告警级别分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c}条 ({d}%)"
  },
  "legend": {
    "bottom": 0,
    "left": "center",
    "data": ["紧急", "严重", "普通", "预警"]
  },
  "series": [
    {
      "name": "告警级别分布",
      "type": "pie",
      "radius": ["40%", "68%"],
      "data": [
        {"name": "紧急", "value": 5, "itemStyle": {"color": "#ff4d4f"}},
        {"name": "严重", "value": 8, "itemStyle": {"color": "#fa8c16"}},
        {"name": "普通", "value": 12, "itemStyle": {"color": "#1890ff"}},
        {"name": "预警", "value": 3, "itemStyle": {"color": "#52c41a"}}
      ]
    }
  ]
}
```

## 示例 2：告警标题 Top（柱状图）

```echarts
{
  "title": {
    "text": "告警标题 Top",
    "left": "center"
  },
  "tooltip": {
    "trigger": "axis",
    "axisPointer": {"type": "shadow"}
  },
  "grid": {
    "left": 48,
    "right": 24,
    "bottom": 72,
    "top": 56,
    "containLabel": true
  },
  "xAxis": {
    "type": "category",
    "data": ["端口DOWN", "链路中断", "CPU过高", "内存不足", "磁盘满"],
    "axisLabel": {"rotate": 30, "interval": 0}
  },
  "yAxis": {
    "type": "value",
    "name": "数量（条）"
  },
  "series": [
    {
      "name": "告警数量",
      "type": "bar",
      "barMaxWidth": 40,
      "data": [10, 8, 6, 4, 3],
      "itemStyle": {"color": "#1890ff"}
    }
  ]
}
```

## 示例 3：设备告警 Top（柱状图）

```echarts
{
  "title": {
    "text": "设备告警 Top",
    "left": "center"
  },
  "tooltip": {
    "trigger": "axis",
    "axisPointer": {"type": "shadow"}
  },
  "grid": {
    "left": 48,
    "right": 24,
    "bottom": 72,
    "top": 56,
    "containLabel": true
  },
  "xAxis": {
    "type": "category",
    "data": ["device-core-01", "device-core-02", "device-core-03"],
    "axisLabel": {"rotate": 30, "interval": 0}
  },
  "yAxis": {
    "type": "value",
    "name": "数量（条）"
  },
  "series": [
    {
      "name": "告警数量",
      "type": "bar",
      "barMaxWidth": 40,
      "data": [15, 12, 8],
      "itemStyle": {"color": "#722ed1"}
    }
  ]
}
```

## 示例 4：专业分布（饼图）

```echarts
{
  "title": {
    "text": "专业分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c}条 ({d}%)"
  },
  "legend": {
    "bottom": 0,
    "left": "center"
  },
  "series": [
    {
      "name": "专业分布",
      "type": "pie",
      "radius": "56%",
      "data": [
        {"name": "IPM", "value": 20},
        {"name": "TRM", "value": 8},
        {"name": "SEC", "value": 5},
        {"name": "NET", "value": 3}
      ]
    }
  ]
}
```

## 示例 5：区域分布（饼图）

```echarts
{
  "title": {
    "text": "区域分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c}条 ({d}%)"
  },
  "legend": {
    "bottom": 0,
    "left": "center"
  },
  "series": [
    {
      "name": "区域分布",
      "type": "pie",
      "radius": "56%",
      "data": [
        {"name": "区域A", "value": 15},
        {"name": "区域B", "value": 12},
        {"name": "区域C", "value": 8},
        {"name": "区域D", "value": 5}
      ]
    }
  ]
}
```

## 示例 6：告警状态分布（环形图）

```echarts
{
  "title": {
    "text": "告警状态分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c}条 ({d}%)"
  },
  "legend": {
    "bottom": 0,
    "left": "center"
  },
  "series": [
    {
      "name": "告警状态分布",
      "type": "pie",
      "radius": ["40%", "68%"],
      "data": [
        {"name": "活跃", "value": 25, "itemStyle": {"color": "#ff4d4f"}},
        {"name": "已清除", "value": 18, "itemStyle": {"color": "#52c41a"}}
      ]
    }
  ]
}
```

## 示例 7：告警时间趋势（折线图）

```echarts
{
  "title": {
    "text": "告警时间趋势",
    "left": "center"
  },
  "tooltip": {
    "trigger": "axis"
  },
  "grid": {
    "left": 48,
    "right": 24,
    "bottom": 48,
    "top": 56,
    "containLabel": true
  },
  "xAxis": {
    "type": "category",
    "data": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]
  },
  "yAxis": {
    "type": "value",
    "name": "数量（条）"
  },
  "series": [
    {
      "name": "告警数量",
      "type": "line",
      "data": [5, 3, 8, 12, 10, 6],
      "smooth": true,
      "itemStyle": {"color": "#1890ff"},
      "areaStyle": {
        "color": {
          "type": "linear",
          "x": 0, "y": 0, "x2": 0, "y2": 1,
          "colorStops": [
            {"offset": 0, "color": "rgba(24, 144, 255, 0.3)"},
            {"offset": 1, "color": "rgba(24, 144, 255, 0.05)"}
          ]
        }
      }
    }
  ]
}
```

## 使用说明

1. 复制所需示例代码
2. 替换 `data` 数组为实际统计结果
3. 在支持 ECharts 的环境中渲染（`echarts` 代码块）

## 颜色参考

```javascript
const colors = {
  critical: "#ff4d4f",   // 紧急 - 红色
  major:    "#fa8c16",   // 严重 - 橙色
  minor:    "#1890ff",   // 普通 - 蓝色
  info:     "#52c41a",   // 预警 - 绿色
  purple:   "#722ed1",
  cyan:     "#13c2c2"
};
```
