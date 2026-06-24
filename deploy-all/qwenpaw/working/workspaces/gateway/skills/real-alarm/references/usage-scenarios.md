# 使用场景

本文档描述 `real-alarm` 技能的典型使用场景和用户问法。

## 典型问法

### 1. 查询告警总数

**用户问法示例**：
- "现在一共有多少条告警？"
- "当前告警总数是多少？"
- "有多少活跃告警？"

**推荐动作**：
```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
```

**回复要点**：
- 直接给出总数
- 如有必要补充时间范围说明
- 可补充活跃告警数量（如果用户询问）

### 2. 查询告警列表

**用户问法示例**：
- "列出最近的告警"
- "看前10条告警"
- "展示告警列表"

**推荐动作**：
```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 10
```

**回复要点**：
- 表格展示关键字段（告警标题、级别、设备、时间）
- 如结果较多，展示前N条并说明总数
- 可补充简单摘要（如严重告警数量）

### 3. 查询严重告警

**用户问法示例**：
- "有哪些严重告警？"
- "列出所有严重级别的告警"
- "严重告警有多少条？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

**回复要点**：
- 先给严重告警数量
- 表格列出严重告警详情
- 如数量很多，展示前20条并说明总数
- 建议优先处理

### 4. 查询活跃告警

**用户问法示例**：
- "有哪些活跃告警？"
- "列出未清除的告警"
- "当前还有哪些告警？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --alarm_status 1 --include-alarms --output markdown
```

**回复要点**：
- 说明活跃告警数量
- 表格展示活跃告警
- 按时间或级别排序

### 5. 按告警级别统计

**用户问法示例**：
- "按告警级别统计一下"
- "各个级别的告警分别有多少？"
- "告警级别分布如何？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode severity --output markdown
```

**回复要点**：
- 统计各级别告警数量和占比
- 表格展示分布
- 环形图可视化
- 重点关注严重告警

### 6. 按设备统计告警

**用户问法示例**：
- "哪些设备告警最多？"
- "按设备统计告警数量"
- "告警最多的设备是哪个？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode device --output markdown
```

**回复要点**：
- 统计各设备告警数量
- 按告警数量降序排列
- 柱状图展示Top设备
- 重点关注告警最多的设备

### 7. 按告警标题统计

**用户问法示例**：
- "最常见的告警是什么？"
- "按告警类型统计"
- "端口DOWN告警有多少？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode title --output markdown
```

**回复要点**：
- 统计各告警标题出现次数
- 按出现次数降序排列
- 柱状图展示Top告警类型
- 重点关注高频告警

### 8. 按专业统计告警

**用户问法示例**：
- "按专业统计告警分布"
- "各个专业的告警情况"
- "IPM专业告警有多少？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode speciality --output markdown
```

**回复要点**：
- 统计各专业告警数量
- 饼图展示分布
- 按专业分析告警特点

### 9. 按区域统计告警

**用户问法示例**：
- "按区域统计告警"
- "哪个区域告警最多？"
- "XA区域告警情况"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode region --output markdown
```

**回复要点**：
- 统计各区域告警数量
- 饼图展示分布
- 重点关注告警多的区域

### 10. 综合告警分析

**用户问法示例**：
- "帮我分析一下告警情况"
- "告警整体情况怎么样？"
- "给个告警分析报告"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

**回复要点**：
- 概览：总数、严重告警、活跃告警
- 级别分布
- 告警类型Top
- 设备告警Top
- 专业分布
- 严重告警预览
- 活跃告警预览
- 自动结论和建议

### 11. 按时间范围查询

**用户问法示例**：
- "昨天的告警有多少？"
- "最近24小时的告警"
- "2026-03-15到2026-03-16的告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode summary --begin_time "2026-03-15 00:00:00" --end_time "2026-03-16 23:59:59" --output markdown
```

**回复要点**：
- 明确时间范围
- 展示该时间范围的告警统计
- 可与历史数据对比

### 12. 关键字搜索告警

**用户问法示例**：
- "查一下端口DOWN的告警"
- "搜索标题里包含端口的告警"
- "设备SN-XA-LHL-A的告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --keyword 端口 --include-alarms --output markdown
```

**回复要点**：
- 说明匹配数量
- 表格展示匹配告警
- 支持多字段搜索

### 13. 按 CI ID 查询告警

**用户问法示例**：
- "帮我查 ci id 等于 18 的所有告警"
- "查询 neId 为 18 的告警"
- "网元 ID 18 有哪些告警？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown
```

**回复要点**：
- 明确筛选条件是 `CI ID = 18`
- 说明匹配数量
- 表格展示告警标题、设备名称、管理IP、CI ID、发生时间、状态

### 14. 按城市筛选告警

**用户问法示例**：
- "南京的告警有多少？"
- "秦淮区的告警情况"
- "查询指定城市的告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode summary --cities 南京 --output markdown
```

**回复要点**：
- 明确筛选条件
- 展示该城市的告警统计
- 可与其他区域对比

### 15. 组合条件查询

**用户问法示例**：
- "南京的严重告警有哪些？"
- "IPM专业的活跃告警"
- "设备4.155.10.35的端口DOWN告警"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --severity 1 --cities 南京 --include-alarms --output markdown
```

**回复要点**：
- 明确所有筛选条件
- 展示匹配结果
- 精准定位问题

### 16. 按资源分类查询当前告警

**用户问法示例**：
- "查询数据库当前告警"
- "查询当前数据库告警"
- "当前数据库告警"
- "网络设备现在有哪些告警？"
- "服务器实时告警有哪些？"

**推荐动作**：
```bash
uv run scripts/analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms --output markdown
```

**资源分类映射**：
- 数据库 / database / db -> `数据库`
- 网络设备 / network -> `网络设备`
- 中间件 / middleware -> `中间件`
- 操作系统 / os -> `操作系统`
- 服务器 / 计算资源 / server -> `计算资源`

**回复要点**：
- 明确筛选条件是接口字段 `neAlias`
- 当前告警应同时传 `--alarm_status 1`
- 不要先拉全量告警再本地过滤资源分类

## 使用建议

### 优先使用 analyze_alarms.py

以下场景优先使用 `analyze_alarms.py`：
- 需要统计分析（按级别、设备、专业等）
- 需要综合概览
- 需要筛选和搜索
- 需要图表展示

### 优先使用 get_alarms.py

以下场景优先使用 `get_alarms.py`：
- 只需要原始分页数据
- 需要精确控制页码和页大小
- 需要指定时间范围但不需要统计分析

### 输出格式选择

- **聊天场景**：使用 `--output markdown`
- **只展示图表**：使用 `--output markdown-echarts-only`
- **程序调用**：使用 `--output json`（默认）

### 数据量控制

- 小于100条：一次性展示
- 100-1000条：分页展示，每次20-50条
- 大于1000条：先统计，再按需展示明细

### 重点关注

- 严重告警（级别1）
- 活跃告警（状态1）
- 高频告警类型
- 告警最多的设备
- 告警多的区域
