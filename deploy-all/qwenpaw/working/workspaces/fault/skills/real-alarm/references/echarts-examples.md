# ECharts 示例

本文档提供告警数据可视化的 ECharts 示例代码。

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
    "data": ["严重", "重要", "一般", "提示"]
  },
  "series": [
    {
      "name": "告警级别分布",
      "type": "pie",
      "radius": ["40%", "68%"],
      "data": [
        {"name": "严重", "value": 5, "itemStyle": {"color": "#ff4d4f"}},
        {"name": "重要", "value": 8, "itemStyle": {"color": "#fa8c16"}},
        {"name": "一般", "value": 12, "itemStyle": {"color": "#1890ff"}},
        {"name": "提示", "value": 3, "itemStyle": {"color": "#52c41a"}}
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
    "data": ["SN-XA-LHL-A.Leaf-4", "SN-BJ-CP-B.Leaf-2", "SN-SZ-FG-C.Leaf-1"],
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
        {"name": "XA", "value": 15},
        {"name": "BJ", "value": 12},
        {"name": "SH", "value": 8},
        {"name": "SZ", "value": 5},
        {"name": "HZ", "value": 3}
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
    "data": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
    "axisLabel": {"rotate": 0}
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
          "x": 0,
          "y": 0,
          "x2": 0,
          "y2": 1,
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

## 示例 8：严重告警占比（环形图）

```echarts
{
  "title": {
    "text": "严重告警占比",
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
      "name": "严重告警占比",
      "type": "pie",
      "radius": ["40%", "68%"],
      "data": [
        {"name": "严重", "value": 5, "itemStyle": {"color": "#ff4d4f"}},
        {"name": "其他", "value": 23, "itemStyle": {"color": "#1890ff"}}
      ]
    }
  ]
}
```

## 示例 9：设备告警分布（堆叠柱状图）

```echarts
{
  "title": {
    "text": "设备告警分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "axis",
    "axisPointer": {"type": "shadow"}
  },
  "legend": {
    "top": 30,
    "data": ["严重", "重要", "一般"]
  },
  "grid": {
    "left": 48,
    "right": 24,
    "bottom": 72,
    "top": 72,
    "containLabel": true
  },
  "xAxis": {
    "type": "category",
    "data": ["设备A", "设备B", "设备C", "设备D", "设备E"],
    "axisLabel": {"rotate": 30}
  },
  "yAxis": {
    "type": "value",
    "name": "数量（条）"
  },
  "series": [
    {
      "name": "严重",
      "type": "bar",
      "stack": "total",
      "data": [2, 3, 1, 0, 1],
      "itemStyle": {"color": "#ff4d4f"}
    },
    {
      "name": "重要",
      "type": "bar",
      "stack": "total",
      "data": [3, 2, 4, 2, 1],
      "itemStyle": {"color": "#fa8c16"}
    },
    {
      "name": "一般",
      "type": "bar",
      "stack": "total",
      "data": [5, 3, 2, 4, 2],
      "itemStyle": {"color": "#1890ff"}
    }
  ]
}
```

## 示例 10：告警处理效率（漏斗图）

```echarts
{
  "title": {
    "text": "告警处理流程",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{a} <br/>{b}: {c}条 ({d}%)"
  },
  "legend": {
    "top": 30,
    "left": "center",
    "data": ["新产生", "已确认", "处理中", "已解决", "已关闭"]
  },
  "series": [
    {
      "name": "告警处理流程",
      "type": "funnel",
      "left": "10%",
      "top": 60,
      "bottom": 60,
      "width": "80%",
      "min": 0,
      "max": 100,
      "minSize": "0%",
      "maxSize": "100%",
      "sort": "descending",
      "gap": 2,
      "label": {
        "show": true,
        "position": "inside"
      },
      "labelLine": {
        "length": 10,
        "lineStyle": {
          "width": 1,
          "type": "solid"
        }
      },
      "itemStyle": {
        "borderColor": "#fff",
        "borderWidth": 1
      },
      "data": [
        {"value": 50, "name": "新产生"},
        {"value": 40, "name": "已确认"},
        {"value": 30, "name": "处理中"},
        {"value": 25, "name": "已解决"},
        {"value": 20, "name": "已关闭"}
      ]
    }
  ]
}
```

## 使用说明

### 基本使用

1. 复制所需示例代码
2. 替换为实际数据
3. 在支持 ECharts 的环境中渲染

### 数据替换

- `data` 数组：替换为实际统计结果
- `xAxis.data`：替换为实际类别标签
- 数值字段：确保为数字类型

### 样式调整

- `color`：修改颜色配置
- `radius`：调整图表大小
- `itemStyle`：自定义样式

### 交互增强

- 添加 `animation`：启用动画
- 配置 `toolbox`：添加工具栏
- 设置 `brush`：启用刷选

## 颜色方案

### 推荐配色

```javascript
const colors = {
  critical: "#ff4d4f",    // 严重 - 红色
  major: "#fa8c16",       // 重要 - 橙色
  minor: "#1890ff",       // 一般 - 蓝色
  info: "#52c41a",        // 提示 - 绿色
  purple: "#722ed1",      // 紫色
  cyan: "#13c2c2",        // 青色
  yellow: "#fadb14",      // 黄色
  magenta: "#eb2f96"      // 洋红
};
```

### 按级别配色

```javascript
const severityColors = {
  1: "#ff4d4f",  // 严重
  2: "#fa8c16",  // 重要
  3: "#1890ff",  // 一般
  4: "#52c41a"   // 提示
};
```

## 注意事项

### 数据格式

- 确保数据为正确的 JSON 格式
- 数值类型必须是数字
- 字符串类型必须加引号

### 图表尺寸

- 设置合适的容器高度
- 响应式适配不同屏幕
- 避免图表过小或过大

### 性能优化

- 大数据量时使用抽样
- 避免过多动画效果
- 合理设置刷新频率

### 兼容性

- 使用标准 ECharts API
- 避免使用实验性功能
- 测试多浏览器兼容