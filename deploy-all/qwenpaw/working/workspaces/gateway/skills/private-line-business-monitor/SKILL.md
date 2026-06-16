---
name: private-line-business-monitor
description: 查询“专线业务监控”页面中的专线与割接数据。适用于用户询问专线列表、状态统计、异常专线、某条电路详情、A/Z 端地址、时延、可用率、带宽、割接通知、割接影响范围、按类型或客户筛选专线时使用。回答必须以页面字段为准；页面没有的内容要明确说明未提供。
---

# 专线业务监控

这是 gateway 本地的 **专线业务监控演示页查询** 技能，对应页面：

`http://82.156.83.38:30081/circuit/zhunneng-private-line-monitor.html`

## 边界

- 本技能只回答该页面里已经出现的专线、电路、割接通知和统计数据。
- 如果用户追问“最新实时状态 / 当前是否已恢复 / 现在流量是多少 / 是否真的在告警 / 为什么告警”，要明确说明：**页面未提供该数据**。
- 实时告警、监控总览、CMDB、巡检、Web 页面监测等需求，继续使用对应现有 skill。

## 已封装数据

- 页面标题：`专线业务监控`
- 数据范围：6 条专线电路、1 条割接通知
- 支持查询字段：
  - 电路编码
  - 专线业务类型
  - 状态（正常 / 预警 / 告警 / 割接中）
  - 客户名称
  - 上下行带宽
  - A/Z 端名称
  - A/Z 端地址
  - 时延
  - 可用率
  - 页面中用于趋势模拟的上下行利用率
  - 割接通知标题、类型、系统、区段、时间、原因、影响电路

## 常用命令

查看监控概览：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py summary --output markdown
```

查看全部专线列表：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py list-circuits --output markdown
```

查看异常专线：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py list-circuits --status abnormal --output markdown
```

查看某条电路详情：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py detail --code ZN-INET-202307-0118 --output markdown
```

按关键字查询：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py list-circuits --keyword "大准铁路" --output markdown
```

查看割接通知：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py cutover --output markdown
```

查看指标排行：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py rank --metric latency --output markdown
```

直接按用户问题查询：

```bash
cd skills/private-line-business-monitor
python3 scripts/private_line_business_monitor.py ask --question "当前有哪些异常专线？" --output markdown
```

## 自然语言映射

- “专线总数 / 当前有多少条专线 / 页面概览 / 状态统计”：执行 `summary`
- “有哪些专线 / 列出全部专线 / 看看所有电路”：执行 `list-circuits`
- “有哪些异常专线 / 告警专线 / 预警专线 / 割接中的专线”：执行 `list-circuits --status ...`
- “某条专线详情 / 电路编码 xxx / A 端在哪里 / Z 端地址 / 带宽 / 时延 / 可用率”：执行 `detail --code ...`
- “当前有哪些割接 / 割接通知 / 割接通知单 / 割接影响了哪些电路”：执行 `cutover`
- “哪个专线时延最高 / 可用率最低 / 带宽最大”：执行 `rank`
- 如果用户直接用自然语言提问且不确定该走哪个命令，优先执行 `ask`

## 执行要求

1. **优先使用脚本查询，不要靠模型记忆手写数据**
2. **默认直接返回脚本结果或只做最小改写，不要自行扩写成“注意 / 建议 / 推断 / 影响分析”**
3. **正常回答不要额外输出“静态演示数据 / 不代表实时状态”这类提醒卡片**；只有当用户明确追问数据来源、实时性、恢复情况时，再说明页面未提供实时数据
4. 如果用户问到页面中不存在的数据字段，要明确说“页面未提供该数据”
5. 如果用户只提供了客户名、类型、地址片段等模糊条件，先执行 `list-circuits --keyword ...`
6. 如果命中多条电路，不要擅自挑一条，先把候选列表返回

## 返回要求

- 统计问题：优先返回摘要 + 表格
- 电路详情：返回字段明细；只有用户明确问到关联割接时，再附上割接通知
- 割接问题：用户只问“有哪些割接中的专线/电路”时，只返回专线列表；明确问通知单、影响范围、开始/结束时间、割接原因时，再返回通知详情
- 排行问题：返回排序规则 + Top 列表
- 若脚本已输出 markdown 表格或分段内容，agent 层应尽量保留结构，不要压成一段话，更不要补充页面里没有的解释
