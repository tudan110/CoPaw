import "../inspiration-panel.css";

type InspirationAction =
  | { type: "employee"; value: string }
  | { type: "view"; value: "overview" | "dashboard" | "tasks" }
  | { type: "panel"; value: "ops-expert" | "knowledge-base" }
  | { type: "knowledge-flow"; value: string };

type InspirationItem = {
  title: string;
  desc: string;
  icon: string;
  bg: string;
  steps: string[];
  tryText: string;
  action: InspirationAction;
};

const inspirationItems: InspirationItem[] = [
  {
    title: "智能故障预测与自愈",
    desc: "让故障分析专家和运维巡检专员联动，实现故障预测、自动诊断、一键修复的全闭环。",
    icon: "🧪",
    bg: "linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(99, 102, 241, 0.14))",
    steps: [
      "配置运维巡检专员执行定时健康巡检，建议每 2 小时一次。",
      "为故障分析专家设置告警接入和自动修复策略。",
      "在看板中观察故障从发现到修复的完整闭环。",
    ],
    tryText: "开始配置",
    action: { type: "employee", value: "fault" },
  },
  {
    title: "零人工值守日常运维",
    desc: "通过每日待办任务板，让数字员工自动完成巡检、报告、清理等日常工作。",
    icon: "🔄",
    bg: "linear-gradient(135deg, rgba(59, 130, 246, 0.18), rgba(14, 165, 233, 0.12))",
    steps: [
      "在定时任务中配置每日巡检、日志清理和报表生成。",
      "在运维看板查看每日待办，确认关键节点状态。",
      "由数字员工自动执行，异常时再通知人工确认。",
    ],
    tryText: "查看运维看板",
    action: { type: "view", value: "dashboard" },
  },
  {
    title: "自然语言查询运维数据",
    desc: "用自然语言向数据分析专家提问，秒级获取 CPU、内存、磁盘、网络等监控数据和趋势分析。",
    icon: "📊",
    bg: "linear-gradient(135deg, rgba(34, 197, 94, 0.18), rgba(16, 185, 129, 0.12))",
    steps: [
      "打开数据分析专家对话。",
      "输入类似“查询 CPU 使用率 TOP10”或“生成本月可用性报表”。",
      "自动生成查询并返回结构化分析结果。",
    ],
    tryText: "开始提问",
    action: { type: "employee", value: "query" },
  },
  {
    title: "构建运维知识图谱",
    desc: "让知识库助手整理历史故障案例、最佳实践，构建团队专属运维知识库。",
    icon: "🗈",
    bg: "linear-gradient(135deg, rgba(6, 182, 212, 0.18), rgba(59, 130, 246, 0.1))",
    steps: [
      "进入知识库助手对话上传 SOP、复盘文档和最佳实践。",
      "在对话中检索验证资料是否能命中，并按需手动沉淀经验。",
      "让知识库助手基于已入库资料回答问题。",
    ],
    tryText: "探索知识库",
    action: { type: "knowledge-flow", value: "知识库检索" },
  },
  {
    title: "工单全流程自动化",
    desc: "工单处置专员自动创建、分派、跟踪、关闭工单，实现从发现问题到闭环的自动流转。",
    icon: "📈",
    bg: "linear-gradient(135deg, rgba(245, 158, 11, 0.18), rgba(249, 115, 22, 0.12))",
    steps: [
      "巡检发现异常后自动创建标准工单。",
      "工单处置专员按技能和负载智能分派处理人。",
      "处理完成后自动验证、关闭并生成统计报表。",
    ],
    tryText: "体验工单流程",
    action: { type: "employee", value: "order" },
  },
  {
    title: "资产全生命周期管理",
    desc: "资产管理专员自动发现、纳管、监控资产，逐步构建完整的 CMDB 资源拓扑。",
    icon: "🌀",
    bg: "linear-gradient(135deg, rgba(239, 68, 68, 0.16), rgba(244, 114, 182, 0.12))",
    steps: [
      "配置网段扫描，自动发现网络设备和服务器。",
      "导入云账号，一键同步云资源到 CMDB。",
      "自动生成资源拓扑图，实现资产可视化管理。",
    ],
    tryText: "开始资产发现",
    action: { type: "employee", value: "resource" },
  },
  {
    title: "多数字员工协同作战",
    desc: "让数字员工自动协作：巡检发现问题 → 故障诊断 → 创建工单 → 知识沉淀。",
    icon: "🤝",
    bg: "linear-gradient(135deg, rgba(236, 72, 153, 0.18), rgba(217, 70, 239, 0.12))",
    steps: [
      "运维巡检专员发现磁盘告警后通知故障分析专家。",
      "故障分析专家自动诊断并同步给工单处置专员。",
      "知识库助手将处置过程沉淀成可复用案例。",
    ],
    tryText: "了解协作流程",
    action: { type: "employee", value: "inspection" },
  },
  {
    title: "运维专家按需扩展",
    desc: "从运维专家库中将垂直领域专家纳入统一入口，获得更专业的运维支持。",
    icon: "💡",
    bg: "linear-gradient(135deg, rgba(100, 116, 139, 0.18), rgba(148, 163, 184, 0.12))",
    steps: [
      "进入高级功能里的运维专家。",
      "浏览 K8s、DBA、安全等垂直领域专家。",
      "把需要的专家加入统一入口，按需增强能力矩阵。",
    ],
    tryText: "浏览专家库",
    action: { type: "panel", value: "ops-expert" },
  },
];

export function InspirationPanel({
  onOpenEmployeeChat,
  onOpenView,
  onOpenPanel,
  onOpenKnowledgeBase,
}: {
  onOpenEmployeeChat: (employeeId: string) => void;
  onOpenView: (view: "overview" | "dashboard" | "tasks") => void;
  onOpenPanel: (panel: "ops-expert" | "knowledge-base") => void;
  onOpenKnowledgeBase: (visibleContent?: string) => void;
}) {
  const handleAction = (action: InspirationAction) => {
    if (action.type === "employee") {
      onOpenEmployeeChat(action.value);
      return;
    }
    if (action.type === "view") {
      onOpenView(action.value);
      return;
    }
    if (action.type === "knowledge-flow") {
      onOpenKnowledgeBase(action.value);
      return;
    }
    onOpenPanel(action.value);
  };

  return (
    <div className="inspiration-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          灵感中心 <small>探索 AI 运维新范式</small>
        </div>
      </div>

      <div className="inspiration-content">
        <section className="inspiration-hero">
          <div className="inspiration-hero-copy">
            <h2>探索 AI 运维新范式</h2>
            <p>
              利用数字员工重新定义运维流程，从故障预测到自动修复，从智能巡检到知识沉淀，把一次次临时响应沉淀为长期可复制的运维范式。
            </p>
          </div>
        </section>

        <section className="inspiration-grid">
          {inspirationItems.map((item) => (
            <article
              key={item.title}
              className="inspiration-card"
              role="button"
              tabIndex={0}
              onClick={() => handleAction(item.action)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  handleAction(item.action);
                }
              }}
            >
              <div className="inspiration-card-glow" />
              <div className="inspiration-icon" style={{ background: item.bg }}>
                {item.icon}
              </div>
              <h4>{item.title}</h4>
              <p>{item.desc}</p>
              <div className="inspiration-steps">
                {item.steps.map((step, index) => (
                  <div key={step} className="inspiration-step">
                    <span className="inspiration-step-num">{index + 1}</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="inspiration-try-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  handleAction(item.action);
                }}
              >
                {item.tryText}
              </button>
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
