# ECharts 示例

下面是本技能最常见的 4 类图。

## 模型分组分布饼图

```echarts
{
  "title": {
    "text": "模型分组分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c} 个 ({d}%)"
  },
  "legend": {
    "right": "5%",
    "top": "center",
    "orient": "vertical"
  },
  "series": [
    {
      "name": "模型分组分布",
      "type": "pie",
      "radius": "56%",
      "data": [
        { "name": "业务", "value": 2 },
        { "name": "计算资源", "value": 8 },
        { "name": "中间件", "value": 5 }
      ]
    }
  ]
}
```

## 关系类型环形图

```echarts
{
  "title": {
    "text": "关系类型分布",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c} 个 ({d}%)"
  },
  "legend": {
    "bottom": 0,
    "left": "center"
  },
  "series": [
    {
      "name": "关系类型分布",
      "type": "pie",
      "radius": ["40%", "68%"],
      "data": [
        { "name": "contain", "value": 10 },
        { "name": "deploy", "value": 8 },
        { "name": "install", "value": 2 }
      ]
    }
  ]
}
```

## 应用关联目标柱状图

```echarts
{
  "title": {
    "text": "应用关联目标分布",
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
    "data": ["虚拟机", "mySQL", "PostgreSQL", "Kafka"],
    "axisLabel": {
      "rotate": 30
    }
  },
  "yAxis": {
    "type": "value",
    "name": "数量"
  },
  "series": [
    {
      "name": "应用关联目标分布",
      "type": "bar",
      "barMaxWidth": 40,
      "data": [1, 1, 1, 1]
    }
  ]
}
```

## 应用关系拓扑树图（从左到右）

```echarts
{
  "title": {
    "text": "应用关系拓扑",
    "left": "center"
  },
  "tooltip": {
    "trigger": "item",
    "triggerOn": "mousemove"
  },
  "series": [
    {
      "type": "tree",
      "orient": "LR",
      "top": "8%",
      "left": "8%",
      "bottom": "8%",
      "right": "22%",
      "symbol": "emptyCircle",
      "symbolSize": 10,
      "expandAndCollapse": true,
      "initialTreeDepth": -1,
      "label": {
        "position": "left",
        "verticalAlign": "middle",
        "align": "right",
        "fontSize": 12
      },
      "leaves": {
        "label": {
          "position": "right",
          "verticalAlign": "middle",
          "align": "left"
        }
      },
      "lineStyle": {
        "curveness": 0.5
      },
      "data": [
        {
          "name": "实际应用名",
          "children": [
            {
              "name": "所属产品",
              "children": [
                { "name": "实际产品名" }
              ]
            },
            {
              "name": "运行资源",
              "children": [
                {
                  "name": "虚拟机",
                  "children": [
                    { "name": "vserver-01" }
                  ]
                },
                {
                  "name": "中间件",
                  "children": [
                    { "name": "Kafka" },
                    { "name": "Redis" }
                  ]
                },
                {
                  "name": "数据库",
                  "children": [
                    { "name": "PostgreSQL" }
                  ]
                }
              ]
            },
            {
              "name": "基础设施",
              "children": [
                {
                  "name": "机柜",
                  "children": [
                    { "name": "Rack-A01" }
                  ]
                },
                {
                  "name": "IP 地址",
                  "children": [
                    { "name": "192.168.130.101" }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```
