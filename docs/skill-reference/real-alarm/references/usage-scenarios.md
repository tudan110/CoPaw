# 使用场景

本文档描述 `real-alarm` 技能的典型使用场景和用户问法。

## 典型问法

### 1. 查询告警总数

**用户问法**：
- "现在一共有多少条告警？"
- "当前告警总数是多少？"

**推荐动作**：
```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
```

**回复要点**：直接给出 `total` 总数，如有必要补充时间范围说明。

---

### 2. 查询告警列表

**用户问法**：
- "列出最近的告警"
- "看前10条告警"

**推荐动作**：
```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 10
```

**回复要点**：表格展示关键字段（告警标题、级别、设备、时间），如结果多展示前N条并说明总数。

---

### 3. 查询严重告警

**用户问法**：
- "有哪些严重告警？"
- "严重告警有多少条？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

**回复要点**：先给严重告警数量，表格列出详情，数量多时展示前20条并说明总数。

---

### 4. 查询活跃告警

**用户问法**：
- "有哪些活跃告警？"
- "列出未清除的告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --alarm_status 1 --include-alarms --output markdown
```

---

### 5. 按告警级别统计

**用户问法**：
- "按告警级别统计一下"
- "告警级别分布如何？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode severity --output markdown
```

**回复要点**：统计各级别数量和占比，表格展示分布，环形图可视化，重点关注严重告警。

---

### 6. 按设备统计告警

**用户问法**：
- "哪些设备告警最多？"
- "告警最多的设备是哪个？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode device --output markdown
```

---

### 7. 按告警标题统计

**用户问法**：
- "最常见的告警是什么？"
- "端口DOWN告警有多少？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode title --output markdown
```

---

### 8. 按专业统计告警

**用户问法**：
- "按专业统计告警分布"
- "IPM专业告警有多少？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode speciality --output markdown
```

---

### 9. 按区域统计告警

**用户问法**：
- "按区域统计告警"
- "哪个区域告警最多？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode region --output markdown
```

---

### 10. 综合告警分析

**用户问法**：
- "帮我分析一下告警情况"
- "给个告警分析报告"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

**回复要点**：概览（总数/严重/活跃）→ 级别分布 → 告警类型Top → 设备告警Top → 专业分布 → 严重告警预览 → 自动结论。

---

### 11. 按时间范围查询

**用户问法**：
- "昨天的告警有多少？"
- "2026-03-15到2026-03-16的告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode summary --begin_time "2026-03-15 00:00:00" --end_time "2026-03-16 23:59:59" --output markdown
```

---

### 12. 关键字搜索告警

**用户问法**：
- "查一下端口DOWN的告警"
- "搜索标题里包含端口的告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --keyword 端口 --include-alarms --output markdown
```

---

### 13. 按 CI ID 查询告警

**用户问法**：
- "帮我查 ci id 等于 18 的所有告警"
- "网元 ID 18 有哪些告警？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown
```

**回复要点**：明确筛选条件是 `CI ID = 18`，表格展示告警标题、设备名称、管理IP、CI ID、发生时间、状态。

---

### 14. 按资源分类查询当前告警

**用户问法**：
- "查询数据库当前告警"
- "网络设备现在有哪些告警？"
- "服务器实时告警有哪些？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms --output markdown
```

**资源分类映射**：
- 数据库 / database / db → `数据库`
- 网络设备 / network → `网络设备`
- 中间件 / middleware → `中间件`
- 操作系统 / os → `操作系统`
- 服务器 / 计算资源 / server → `计算资源`

**回复要点**：必须同时传 `--alarm_status 1`；不要先拉全量再本地过滤资源分类。

---

### 15. 组合条件查询

**用户问法**：
- "南京的严重告警有哪些？"
- "IPM专业的活跃告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --severity 1 --cities 南京 --include-alarms --output markdown
```

## 输出格式选择

| 场景 | 推荐格式 |
|------|----------|
| 聊天回复 | `--output markdown` |
| 只展示图表 | `--output markdown-echarts-only` |
| 程序调用/调试 | `--output json`（默认） |

## 优先使用 analyze_alarms.py 的场景

- 需要统计分析（按级别、设备、专业等）
- 需要综合概览
- 需要筛选和搜索
- 需要图表展示

## 优先使用 get_alarms.py 的场景

- 只需要原始分页数据
- 需要精确控制页码和页大小
- 需要指定时间范围但不需要统计分析
