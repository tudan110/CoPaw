# AI 大屏 · 扩展数据能力(不改代码)

大屏的数据能力不再写死在 `descriptors.py`。除了内置的告警/工单/日志/CMDB,你可以用两种方式**不改代码**地新增能力;LLM 会在生成大屏时按名称/描述自动匹配并填参,取真实数据渲染。

> 安全边界:LLM 只能**选择**已注册的连接器 / 已安装的技能并填写**声明过的参数**,永远不会自己拼装内网 URL 或脚本去调用。无匹配能力时仍走 web-live-data(公网检索)或诚实的 capability-gap,绝不编数据。

---

## 方式 A:注册一个 HTTP 连接器(Phase B)

适合"系统里有接口、但大屏没接入"的场景(如巡检指标接口)。后端已带 SSRF 防护、限流、服务端鉴权注入。

`POST /api/portal/proxy/datasources`,在普通连接器字段上加一个 `big_screen` 绑定:

```json
{
  "id": "inspection-metrics",
  "name": "系统巡检指标",
  "description": "按资源ID查询巡检指标(CPU/内存/磁盘等)。当用户要看巡检、指标体检、资源健康时使用。",
  "url_template": "http://172.28.75.4:30080/inspect/metrics/{resId}",
  "method": "GET",
  "headers": { "Authorization": "Bearer <token>" },
  "timeout": 20,
  "enabled": true,
  "big_screen": {
    "enabled": true,
    "domain": "inspection",
    "rows_path": "data.items",
    "value_path": "data.total",
    "unit": "项",
    "fields": [
      { "key": "metricName", "label": "指标" },
      { "key": "value", "label": "当前值" },
      { "key": "threshold", "label": "阈值" },
      { "key": "status", "label": "状态" }
    ],
    "params": [
      { "name": "resId", "label": "资源ID", "required": true }
    ],
    "examplePrompts": ["巡检 7953 的指标", "看一下这台机器的体检结果"]
  }
}
```

要点:
- `url_template` 的主机部分**必须写死**(不能放 `{占位符}`);参数只填路径/查询位。
- `rows_path` 是响应里行数组的点路径(如 `data.items`);留空表示响应本身就是数组或含 `items/rows/data` 字段。
- `fields` 是要展示的列;`params` 是允许 LLM 填的参数(会以 `?name=value` 或路径占位形式带上)。
- 注册后**重启后端**(读的是磁盘配置),大屏即多出能力 `proxy:inspection-metrics`,用自然语言"查询巡检……"就会被选中。

---

## 方式 B:给技能加大屏声明(Phase C)

适合已有 skill、其脚本能输出 JSON 的场景。在技能的 `SKILL.md` front matter 里加 `bigscreen:` 块:

```yaml
---
name: my-skill
description: ……
bigscreen:
  domain: custom
  script: scripts/query.py        # 相对技能目录,必须输出 JSON 到 stdout
  args: ["--output", "json"]      # 固定参数
  rowsPath: data.items            # JSON 里行数组的点路径
  valuePath: data.total           # 可选:KPI 标量
  unit: 条
  fields:
    - { key: title, label: 标题 }
    - { key: status, label: 状态 }
  params:                          # LLM 可填,带成 --<name> <value>
    - { name: limit, default: 20 }
  examplePrompts: ["查询最近的 xxx"]
---
```

要点:
- 脚本以 argv 形式运行(无 shell 注入风险),限定在技能自己的目录内,有超时,强制 UTF-8。
- 扫描的是 `WORKING_DIR/workspaces/*/skills/*/SKILL.md`;加完**重启后端**即出现能力 `skill:<workspace>:<skill>`。
- 告警/工单/日志/CMDB 已有内置静态能力,**不要**再给它们加 bigscreen 块(会重复)。这条用于新接入的技能。

---

## 验证

注册/声明后重启后端,到大屏工坊用对应的自然语言生成一屏,确认:能力被选中、显示真实字段;无数据时诚实显示空/失败;无网络/接口不通时不编造。能力目录也可在生成请求的意图阶段看到(`list_capability_metadata` 已动态合并)。
