# Skill 参考示例

本目录提供两个完整的 Skill 参考实现，覆盖两种最常见的 Skill 类型，
供开发者快速上手 Skill 开发：

- **real-alarm**：查询类 Skill —— 调用外部接口、拉取数据、做统计分析
- **optical-module-rca**：推理类 Skill —— 不连接任何外部系统，纯本地
  按固定方法论对用户提供的参数做判断，输出结论和建议

## 目录结构

```
skills 参考示例/
├── real-alarm/               ← 查询类参考示例（实时告警查询）
│   ├── SKILL.md              ← Skill 主文档（Agent 的行为指导）
│   ├── .env.example          ← 配置样例（复制为 .env 后填写）
│   ├── mock_data.json        ← Mock 数据（USE_MOCK_DATA=true 时使用，无接口权限也能联调）
│   ├── scripts/              ← 可执行脚本
│   │   ├── pyproject.toml    ← 依赖声明
│   │   ├── get_alarms.py     ← 原始分页查询
│   │   ├── analyze_alarms.py ← 统一汇总分析（推荐入口）
│   │   ├── query_alarm_class_count.py ← 独立统计接口
│   │   └── utils/            ← 内部模块（按职责拆分）
│   │       ├── alarm_analyzer.py   ← 数据拉取与分析逻辑
│   │       ├── alarm_normalizer.py ← 字段规范化映射
│   │       ├── chart_generator.py  ← ECharts 图表生成
│   │       └── markdown_renderer.py← Markdown 输出渲染
│   └── references/           ← Agent 按需读取的参考文档
│       ├── api-specification.md  ← 接口与参数说明
│       ├── response-format.md    ← 返回数据结构
│       ├── usage-scenarios.md    ← 典型问法与推荐动作
│       ├── data-analysis-guide.md← 分析维度与方法
│       ├── chart-guide.md        ← 图表选择指南
│       └── echarts-examples.md   ← ECharts 示例代码
└── optical-module-rca/       ← 推理类参考示例（光模块老化根因分析）
    ├── SKILL.md              ← Skill 主文档（Agent 的行为指导）
    ├── scripts/               ← 可执行脚本（纯 stdlib，无第三方依赖）
    │   ├── diagnose_optical_aging.py ← 四步法诊断主脚本
    │   └── utils/
    │       └── thresholds.py ← 参数正常范围表
    └── references/            ← Agent 按需读取的参考文档
        ├── methodology.md         ← 四步法完整说明
        ├── threshold-reference.md ← 参数正常范围与故障现象表
        ├── remediation-playbook.md← 处置预案（紧急止血/根因修复/预防措施）
        └── report-template.md     ← 故障报告模板
```

## 关键规范

### SKILL.md 必备章节

| 章节 | 作用 |
|------|------|
| frontmatter（name/category/tags/triggers/description） | Agent 决定是否使用本 Skill 的依据 |
| 触发条件 | 明确哪些用户意图触发本 Skill |
| 配置 | 依赖的环境变量及优先级 |
| 主流程 | 分场景的执行策略，避免 Agent 反复试错 |
| 用户意图 → 推荐动作 | 自然语言到命令的映射，让 Agent 少问用户 |
| 输出约定 | 默认输出格式，保证回复风格一致 |
| 错误处理 | 常见错误的标准提示，避免 Agent 胡乱猜测 |
| Few-shot 示例 | 最直接的行为示范，优先级高于文字描述 |

### 脚本分层

```
get_*.py          ← 原始查询，精确控制分页/过滤参数
analyze_*.py      ← 统一入口，自动拉取全量数据后分析
query_*_count.py  ← 独立统计接口（按需添加）
utils/            ← 内部模块，按职责拆分
```

### 配置约定

```bash
# 技能目录下的 .env（复制 .env.example 后填写，回退项）
YOUR_API_BASE_URL=http://<host>:<port>
YOUR_API_TOKEN=your_token_here

# 共享 secrets/（优先，由平台注入）
```

加载优先级：共享 secrets 注入 → skill 目录 .env → 项目根目录 .env

没有接口权限时，可先设置 `USE_MOCK_DATA=true`，让脚本读取技能目录下的
`mock_data.json` 返回演示数据，用于先验证参数解析、过滤、渲染逻辑，接口权限
到位后再切回 `false`。

> 不是所有 Skill 都需要配置。`optical-module-rca` 就完全不连接外部
> 系统，所有输入都由调用方直接传参，因此没有 `.env`。写 Skill 前先
> 判断自己的场景是否真的需要外部接口，不需要就不要为了"看起来完整"
> 硬加一套配置。

### references/ 的使用原则

- Agent 默认**不**主动加载所有参考文档
- 只在用户追问细节时按需读取
- SKILL.md 里用 "何时读取参考文档" 章节声明触发条件
