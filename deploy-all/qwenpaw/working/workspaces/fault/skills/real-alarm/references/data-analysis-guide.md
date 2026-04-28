# 数据分析指南

本文档描述如何对告警数据进行统计分析。

## 分析维度

### 1. 告警级别分析

**分析目的**：了解告警严重程度分布，优先处理严重告警

**分析方法**：
- 统计各级别告警数量和占比
- 重点关注严重（级别1）和重要（级别2）告警
- 分析严重告警的设备和类型

**推荐图表**：环形图（donut）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode severity --output markdown
```

**分析要点**：
- 严重告警占比
- 活跃严重告警数量
- 严重告警集中在哪些设备
- 严重告警的类型分布

### 2. 告警类型分析

**分析目的**：识别最常见的告警类型，针对性优化

**分析方法**：
- 按告警标题（alarmtitle）统计
- 识别高频告警类型
- 分析高频告警的影响范围

**推荐图表**：柱状图（bar）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode title --output markdown
```

**分析要点**：
- Top 5 告警类型
- 高频告警的设备分布
- 高频告警的时间分布
- 是否存在重复告警

### 3. 设备告警分析

**分析目的**：识别告警最多的设备，重点排查

**分析方法**：
- 按设备名称（devName）统计
- 识别告警频发设备
- 分析设备告警类型

**推荐图表**：柱状图（bar）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode device --output markdown
```

**分析要点**：
- Top 10 告警设备
- 单设备告警类型集中度
- 设备告警时间模式
- 设备是否为关键设备

### 4. 专业告警分析

**分析目的**：了解各专业的告警情况，资源分配

**分析方法**：
- 按专业（speciality）统计
- 分析各专业告警特点
- 识别告警多的专业

**推荐图表**：饼图（pie）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode speciality --output markdown
```

**分析要点**：
- 各专业告警数量
- 各专业告警严重程度
- 各专业告警类型特点
- 专业间告警关联

### 5. 区域告警分析

**分析目的**：了解告警地理分布，区域运维支持

**分析方法**：
- 按区域（alarmregion）统计
- 分析各区域告警特点
- 识别告警多的区域

**推荐图表**：饼图（pie）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode region --output markdown
```

**分析要点**：
- 各区域告警数量
- 各区域告警严重程度
- 各区域告警类型特点
- 区域间告警对比

### 6. 告警状态分析

**分析目的**：了解告警处理效率，优化处理流程

**分析方法**：
- 统计活跃和已清除告警
- 分析告警清除时间
- 分析告警处理效率

**推荐图表**：环形图（donut）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode search --alarm_status 1 --output markdown
```

**分析要点**：
- 活跃告警占比
- 活跃告警持续时间
- 严重活跃告警数量
- 告警处理效率

### 7. 时间趋势分析

**分析目的**：了解告警时间分布规律，预防性维护

**分析方法**：
- 按时间段统计告警数量
- 分析告警时间模式
- 识别告警高峰时段

**推荐图表**：折线图（line）

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode summary --begin_time "2026-03-15 00:00:00" --end_time "2026-03-16 23:59:59" --output markdown
```

**分析要点**：
- 告警时间分布
- 高峰时段识别
- 告警周期性规律
- 时间与告警类型关联

### 8. 综合分析

**分析目的**：全面了解告警情况，提供决策支持

**分析方法**：
- 多维度综合分析
- 识别关键问题和风险点
- 提供改进建议

**推荐图表**：多种图表组合

**示例代码**：
```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

**分析要点**：
- 告警总体情况
- 严重告警分析
- 高频告警分析
- 设备风险分析
- 区域告警分析
- 处理建议

## 分析建议

### 分析顺序

1. **先概览**：了解告警总体情况
2. **再细化**：按级别、类型、设备等维度深入分析
3. **找重点**：识别严重告警、高频告警、问题设备
4. **给建议**：基于分析结果提供处理建议

### 数据质量

- 确保数据完整性和准确性
- 关注异常数据和重复数据
- 验证分析结果的合理性

### 分析报告

- 使用清晰的标题和结构
- 用表格和图表展示数据
- 提供关键指标和结论
- 给出可行的建议

### 持续改进

- 定期进行告警分析
- 跟踪分析结果的应用效果
- 根据反馈优化分析方法
- 建立告警分析知识库

## 分析技巧

### 数据过滤

```bash
# 只分析严重告警
uv run scripts/analyze_alarms.py --mode search --severity 1 --output markdown

# 只分析活跃告警
uv run scripts/analyze_alarms.py --mode search --alarm_status 1 --output markdown

# 分析指定时间范围
uv run scripts/analyze_alarms.py --mode summary --begin_time "2026-03-15 00:00:00" --end_time "2026-03-16 23:59:59" --output markdown

# 分析指定城市
uv run scripts/analyze_alarms.py --mode summary --cities 南京 --output markdown
```

### 组合分析

```bash
# 南京的严重告警
uv run scripts/analyze_alarms.py --mode search --severity 1 --cities 南京 --include-alarms --output markdown

# IPM专业的活跃告警
uv run scripts/analyze_alarms.py --mode search --speciality IPM --alarm_status 1 --include-alarms --output markdown

# 设备SN-XA-LHL-A的端口DOWN告警
uv run scripts/analyze_alarms.py --mode search --device_name SN-XA-LHL-A --keyword 端口DOWN --include-alarms --output markdown
```

### 结果对比

```bash
# 对比不同时间段的告警
uv run scripts/analyze_alarms.py --mode summary --begin_time "2026-03-15 00:00:00" --end_time "2026-03-15 23:59:59" --output markdown > alarm_0315.md
uv run scripts/analyze_alarms.py --mode summary --begin_time "2026-03-16 00:00:00" --end_time "2026-03-16 23:59:59" --output markdown > alarm_0316.md
```

## 注意事项

### 数据范围

- 明确分析的时间范围
- 确认数据的完整性和准确性
- 注意数据更新时间

### 告警级别

- 级别1：严重，需立即处理
- 级别2：重要，需要关注
- 级别3：一般，需要处理
- 级别4：提示，仅供参考

### 告警状态

- 状态1：活跃，告警未清除
- 状态0：已清除，告警已恢复

### 数据量

- 大量数据时先做统计分析
- 根据需要展示明细
- 使用分页避免数据过载

### 隐私和安全

- 保护敏感信息
- 不要在输出中显示完整token
- 注意设备IP等敏感信息的保护