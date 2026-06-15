# 数据分析指南

本文档描述如何对告警数据进行统计分析。

## 分析维度

### 1. 告警级别分析

**分析目的**：了解告警严重程度分布，优先处理严重告警

**推荐图表**：环形图（donut）

```bash
uv run scripts/analyze_alarms.py --mode severity --output markdown
```

**分析要点**：严重告警占比、活跃严重告警数量、严重告警集中在哪些设备。

---

### 2. 告警类型分析

**分析目的**：识别最常见的告警类型，针对性优化

**推荐图表**：柱状图（bar）

```bash
uv run scripts/analyze_alarms.py --mode title --output markdown
```

**分析要点**：Top 5 告警类型、高频告警的设备分布、是否存在重复告警。

---

### 3. 设备告警分析

**分析目的**：识别告警最多的设备，重点排查

**推荐图表**：柱状图（bar）

```bash
uv run scripts/analyze_alarms.py --mode device --output markdown
```

**分析要点**：Top 10 告警设备、单设备告警类型集中度、设备是否为关键设备。

---

### 4. 专业告警分析

**分析目的**：了解各专业的告警情况

**推荐图表**：饼图（pie）

```bash
uv run scripts/analyze_alarms.py --mode speciality --output markdown
```

---

### 5. 区域告警分析

**分析目的**：了解告警地理分布，支持区域运维

**推荐图表**：饼图（pie）

```bash
uv run scripts/analyze_alarms.py --mode region --output markdown
```

---

### 6. 综合分析

**分析目的**：全面了解告警情况，提供决策支持

**推荐图表**：多种图表组合

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

## 分析顺序建议

1. **先概览**：了解告警总体情况（`mode summary`）
2. **再细化**：按级别、类型、设备等维度深入（`mode severity / device / title`）
3. **找重点**：识别严重告警、高频告警、问题设备
4. **给建议**：基于分析结果提供处理建议

## 数据过滤技巧

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

## 组合分析示例

```bash
# 南京的严重告警
uv run scripts/analyze_alarms.py --mode search --severity 1 --cities 南京 --include-alarms --output markdown

# IPM专业的活跃告警
uv run scripts/analyze_alarms.py --mode search --speciality IPM --alarm_status 1 --include-alarms --output markdown

# 关键字 + 设备名称组合搜索
uv run scripts/analyze_alarms.py --mode search --device_name device-core-01 --keyword 端口DOWN --include-alarms --output markdown
```

## 注意事项

- **数据量**：统计或筛选前先确认数据是否已全量获取
- **告警级别**：级别1（紧急）需立即处理，级别2（严重）需重点关注
- **告警状态**：状态1（活跃）表示告警未清除
- **资源分类**：必须通过 `--ne_alias` 传给接口；不能先查全量再本地过滤
- **Token 安全**：不在对话中回显 Token，只放在 `.env` 或环境变量中
