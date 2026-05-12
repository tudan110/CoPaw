import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fdeApi,
  FdeWorkbenchError,
  type FdeProbeResult,
  type FdeSelfcheckResult,
  type FdeStagedDetail,
  type FdeStagedSummary,
  type FdeWorkbenchInfo,
} from "../../api/fde";
import { FdeConsoleChat } from "../../components/FdeConsoleChat";
import { FdeCreateAgentModal } from "../../components/FdeCreateAgentModal";
import { portalAgentsApi, type AgentSummary } from "../../api/portalAgents";
import "../fde-workbench.css";

const NEW_AGENT_SENTINEL = "__fde_new_agent__";

const FDE_AGENT_ID = "fde";
const FDE_AGENT_NAME = "FDE 交付助手";

const PIPELINE_STEPS = [
  { key: "talk", label: "对话生成", hint: "把需求与现状告诉 FDE" },
  { key: "review", label: "审查代码", hint: "看生成的技能文件" },
  { key: "selfcheck", label: "自检", hint: "域审查 + 沙箱试跑" },
  { key: "install", label: "确认安装", hint: "装进目标业务智能体" },
] as const;

type Notice = { type: "success" | "error" | "info"; message: string } | null;

function errMsg(error: unknown): string {
  if (error instanceof FdeWorkbenchError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "未知错误";
}

function SelfcheckBanner({
  result,
}: {
  result: FdeSelfcheckResult | undefined;
}) {
  if (!result) {
    return null;
  }
  if (result.error) {
    return (
      <div className="fde-selfcheck fde-selfcheck--bad">
        <div className="fde-selfcheck-head">
          <span className="fde-pill fde-pill--bad">自检失败</span>
          <span className="fde-selfcheck-line">{result.error}</span>
        </div>
      </div>
    );
  }
  const ready = Boolean(result.ready_for_review);
  const lists: Array<{ label: string; items: string[]; tone: string }> = [
    { label: "阻塞原因", items: result.blocked_reasons || [], tone: "bad" },
    { label: "警告", items: result.warnings || [], tone: "warn" },
    { label: "待人工补全 / 确认", items: result.todo || [], tone: "muted" },
  ];
  return (
    <div className={`fde-selfcheck fde-selfcheck--${ready ? "ok" : "bad"}`}>
      <div className="fde-selfcheck-head">
        <span className={`fde-pill fde-pill--${ready ? "ok" : "bad"}`}>
          {ready ? "自检通过 · 可进入审批" : "未通过自检"}
        </span>
      </div>
      {lists.map(({ label, items, tone }) =>
        items.length > 0 ? (
          <div className="fde-selfcheck-block" key={label}>
            <div className={`fde-selfcheck-block-title fde-tone--${tone}`}>
              {label}
            </div>
            <ul>
              {items.map((it) => (
                <li key={it}>{it}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </div>
  );
}

export function FdeWorkbenchPanel() {
  const [info, setInfo] = useState<FdeWorkbenchInfo | null>(null);
  const [staged, setStaged] = useState<FdeStagedSummary[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [detail, setDetail] = useState<FdeStagedDetail | null>(null);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [probe, setProbe] = useState<FdeProbeResult | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [genName, setGenName] = useState("");
  const [genWorkspace, setGenWorkspace] = useState("query");
  const [genDescription, setGenDescription] = useState("");
  const [chatOpen, setChatOpen] = useState(true);
  const [infoLoading, setInfoLoading] = useState(true);
  const infoRetryRef = useRef(0);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [installTarget, setInstallTarget] = useState("");
  const [createAgentFor, setCreateAgentFor] = useState<
    "gen" | "install" | null
  >(null);

  const loadStaged = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fdeApi.listStaged();
      setStaged(result.skills || []);
      setNotice((n) =>
        n && n.message.includes("加载暂存列表失败") ? null : n,
      );
    } catch (error) {
      setNotice({
        type: "error",
        message: `加载暂存列表失败：${errMsg(error)}`,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      setAgents(await portalAgentsApi.listAgents());
    } catch {
      // non-fatal — the select just shows fewer options
    }
  }, []);

  const loadInfo = useCallback(
    async (opts?: { manual?: boolean }) => {
      if (opts?.manual) {
        infoRetryRef.current = 0;
      }
      setInfoLoading(true);
      let next: FdeWorkbenchInfo;
      try {
        next = await fdeApi.getWorkbenchInfo();
      } catch (error) {
        next = { available: false, reason: errMsg(error) };
      }
      setInfo(next);
      setInfoLoading(false);
      if (next.available) {
        infoRetryRef.current = 0;
        void loadStaged();
        void loadAgents();
      } else if (infoRetryRef.current < 4) {
        // Backend may still be coming up / reloading right after `sync` —
        // give it a few quiet retries before declaring it unavailable.
        infoRetryRef.current += 1;
        window.setTimeout(() => void loadInfo(), 2500);
      }
    },
    [loadStaged, loadAgents],
  );

  const loadDetail = useCallback(async (name: string) => {
    setDetail(null);
    setProbe(null);
    try {
      const result = await fdeApi.showStaged(name);
      setDetail(result);
      const firstReadable =
        result.files.find((f) => f.path === "SKILL.md") ||
        result.files.find((f) => typeof f.content === "string");
      setActiveFile(firstReadable ? firstReadable.path : null);
    } catch (error) {
      setNotice({
        type: "error",
        message: `加载技能详情失败：${errMsg(error)}`,
      });
    }
  }, []);

  useEffect(() => {
    // loadInfo drives loadStaged once the backend reports available.
    void loadInfo();
  }, [loadInfo]);

  useEffect(() => {
    if (selectedName) {
      void loadDetail(selectedName);
    } else {
      setDetail(null);
    }
  }, [selectedName, loadDetail]);

  const selectStaged = useCallback((name: string) => {
    setNotice(null);
    setSelectedName((prev) => (prev === name ? prev : name));
  }, []);

  const handleGenerate = useCallback(async () => {
    const name = genName.trim();
    if (!name) {
      setNotice({ type: "error", message: "请填写技能名" });
      return;
    }
    setBusy("generate");
    setNotice(null);
    try {
      const result = await fdeApi.generate({
        name,
        targetWorkspace: genWorkspace.trim() || "query",
        brief: genDescription.trim()
          ? { description: genDescription.trim() }
          : undefined,
      });
      setNotice({
        type: "success",
        message: `已生成骨架 ${result.skill_name}（自检${result.selfcheck?.ready_for_review ? "通过" : "未通过"}）。接下来在上面的对话里让 FDE 把 runtime/tool_adapters.py 接上真实接口。`,
      });
      setGenName("");
      setGenDescription("");
      await loadStaged();
      setSelectedName(result.skill_name);
    } catch (error) {
      setNotice({ type: "error", message: `生成失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [genName, genWorkspace, genDescription, loadStaged]);

  const handleSelfcheck = useCallback(async () => {
    if (!selectedName) {
      return;
    }
    setBusy("selfcheck");
    try {
      const result = await fdeApi.selfcheckStaged(selectedName);
      setDetail((prev) => (prev ? { ...prev, selfcheck: result } : prev));
      setNotice({
        type: result.ready_for_review ? "success" : "info",
        message: result.ready_for_review
          ? "自检通过。"
          : "自检未通过，看下阻塞原因。",
      });
    } catch (error) {
      setNotice({ type: "error", message: `自检失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName]);

  const handleProbe = useCallback(async () => {
    if (!selectedName) {
      return;
    }
    setBusy("probe");
    setProbe(null);
    try {
      const result = await fdeApi.probeStaged(selectedName);
      setProbe(result);
      setNotice({
        type: result.ok ? "success" : "error",
        message: result.ok
          ? "沙箱试跑成功。"
          : `沙箱试跑失败：${result.error || result.stderr || "见输出"}`,
      });
    } catch (error) {
      setNotice({ type: "error", message: `沙箱试跑失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName]);

  const targetWorkspace = useMemo(() => {
    const fromList = staged.find(
      (s) => s.skill_name === selectedName,
    )?.target_workspace;
    return fromList || "";
  }, [staged, selectedName]);

  useEffect(() => {
    setInstallTarget(targetWorkspace);
  }, [selectedName, targetWorkspace]);

  const handleInstall = useCallback(async () => {
    if (!selectedName) {
      return;
    }
    const dest = installTarget.trim() || targetWorkspace;
    if (!dest) {
      setNotice({ type: "error", message: "请先选一个目标业务智能体" });
      return;
    }
    if (
      !window.confirm(
        `确认把技能 “${selectedName}” 安装到业务智能体 “${dest}” 的工作区？\n安装会再走一遍安全扫描，并以「二开」标签启用。`,
      )
    ) {
      return;
    }
    setBusy("install");
    try {
      const result = await fdeApi.installStaged(
        selectedName,
        dest !== targetWorkspace ? dest : undefined,
      );
      setNotice({
        type: "success",
        message: `已安装到 ${result.target_workspace} 工作区（标签：${result.tag}）。到技能面板确认它已启用，再去该业务智能体对话里触发它。`,
      });
    } catch (error) {
      setNotice({ type: "error", message: `安装失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName, targetWorkspace, installTarget]);

  const handleAgentCreated = useCallback(
    (agentId: string) => {
      const target = createAgentFor;
      setCreateAgentFor(null);
      void loadAgents();
      if (target === "install") {
        setInstallTarget(agentId);
      } else {
        setGenWorkspace(agentId);
      }
      setNotice({ type: "success", message: `已创建业务智能体 ${agentId}。` });
    },
    [createAgentFor, loadAgents],
  );

  const agentOptions = useCallback(
    (current: string) => {
      const known = new Set(agents.map((a) => a.id));
      const extras =
        current && !known.has(current) ? [{ id: current, name: current }] : [];
      return (
        <>
          {extras.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}（{a.id}）
            </option>
          ))}
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}（{a.id}）
            </option>
          ))}
          <option value={NEW_AGENT_SENTINEL}>＋ 新建业务智能体…</option>
        </>
      );
    },
    [agents],
  );

  const defaultModel = useMemo(() => {
    const fde = agents.find((a) => a.id === "fde");
    const def = agents.find((a) => a.id === "default");
    return (fde?.active_model || def?.active_model || null) as {
      provider_id?: string;
      model?: string;
    } | null;
  }, [agents]);

  const handleDiscard = useCallback(async () => {
    if (!selectedName) {
      return;
    }
    if (!window.confirm(`确认丢弃暂存技能 “${selectedName}”？`)) {
      return;
    }
    setBusy("discard");
    try {
      await fdeApi.discardStaged(selectedName);
      setNotice({ type: "info", message: `已丢弃 ${selectedName}。` });
      setSelectedName(null);
      await loadStaged();
    } catch (error) {
      setNotice({ type: "error", message: `丢弃失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName, loadStaged]);

  const activeFileContent = useMemo(() => {
    if (!detail || !activeFile) {
      return null;
    }
    const file = detail.files.find((f) => f.path === activeFile);
    if (!file) {
      return null;
    }
    if (file.binary) {
      return "(二进制文件)";
    }
    if (file.truncated) {
      return "(文件过大，已截断 —— 用「沙箱试跑」或在上面的对话里看完整内容)";
    }
    return file.content ?? "";
  }, [detail, activeFile]);

  const heroState: "loading" | "down" | "ok" =
    infoLoading || info === null
      ? "loading"
      : info.available
        ? "ok"
        : "down";
  const available = heroState === "ok";
  const currentStep = selectedName
    ? detail?.selfcheck?.ready_for_review
      ? 3
      : 2
    : staged.length
      ? 1
      : 0;

  return (
    <div className="fde-wb">
      <header
        className={`fde-hero${heroState === "down" ? " is-down" : ""}${
          heroState === "loading" ? " is-loading" : ""
        }`}
      >
        <div className="fde-hero-mark" aria-hidden>
          <span>⌁</span>
        </div>
        <div className="fde-hero-body">
          <div className="fde-hero-title">
            交付工作台
            <span className="fde-hero-kicker">Forward Deployed Engineer</span>
          </div>
          <p className="fde-hero-sub">
            {heroState === "ok"
              ? "把客户需求与系统现状交给 FDE，它走完「访谈 → 方案 → 生成」并把可上线的技能暂存到这里，由你审查、试跑、确认安装。"
              : heroState === "loading"
                ? "正在连接 FDE 交付助手…"
                : `FDE 交付助手暂不可用：${info?.reason || "请先 sync-qwenpaw-working.sh 同步工作区并重启服务"}`}
          </p>
        </div>
        {heroState === "ok" ? (
          <div className="fde-hero-stats">
            <span className="fde-stat">
              <span className="fde-stat-dot fde-stat-dot--ok" />
              在线
            </span>
            <span className="fde-stat">
              暂存 <strong>{staged.length}</strong>
            </span>
            <span className="fde-stat fde-stat--mono" title={info?.stagedDir}>
              {info?.onboardingSkill}
            </span>
          </div>
        ) : heroState === "loading" ? (
          <div className="fde-hero-stats">
            <span className="fde-stat">
              <span className="fde-stat-dot" />
              连接中…
            </span>
          </div>
        ) : (
          <div className="fde-hero-stats">
            <button
              type="button"
              className="fde-link-btn"
              onClick={() => void loadInfo({ manual: true })}
            >
              重试
            </button>
          </div>
        )}
      </header>

      {available ? (
        <ol className="fde-pipeline">
          {PIPELINE_STEPS.map((step, idx) => (
            <li
              key={step.key}
              className={`fde-step${
                idx < currentStep
                  ? " is-done"
                  : idx === currentStep
                    ? " is-active"
                    : ""
              }`}
            >
              <span className="fde-step-no">{idx + 1}</span>
              <span className="fde-step-text">
                <span className="fde-step-label">{step.label}</span>
                <span className="fde-step-hint">{step.hint}</span>
              </span>
            </li>
          ))}
        </ol>
      ) : null}

      {notice ? (
        <div className={`fde-notice fde-notice--${notice.type}`} role="status">
          <span className="fde-notice-glyph">
            {notice.type === "success"
              ? "✓"
              : notice.type === "error"
                ? "!"
                : "i"}
          </span>
          <span>{notice.message}</span>
          <button
            type="button"
            className="fde-notice-close"
            onClick={() => setNotice(null)}
            aria-label="关闭"
          >
            ×
          </button>
        </div>
      ) : null}

      {available ? (
        <section className="fde-section fde-chat">
          <div className="fde-section-head">
            <div className="fde-section-title">
              交付对话
              <span className="fde-section-sub">访谈 → 方案 → 生成</span>
            </div>
            <button
              type="button"
              className="fde-link-btn"
              onClick={() => setChatOpen((prev) => !prev)}
            >
              {chatOpen ? "收起" : "展开"}
            </button>
          </div>
          {chatOpen ? (
            <div className="fde-chat-stage">
              <FdeConsoleChat
                agentId={FDE_AGENT_ID}
                agentName={FDE_AGENT_NAME}
                onTurnComplete={() => void loadStaged()}
              />
            </div>
          ) : (
            <p className="fde-chat-foot">
              展开后可直接和 {FDE_AGENT_NAME}对话；它生成技能后会自动出现在右侧。
            </p>
          )}
        </section>
      ) : null}

      <div className="fde-main">
        <div className="fde-col">
          <section className="fde-section">
            <div className="fde-section-head">
              <div className="fde-section-title">
                暂存技能
                <span className="fde-count">{staged.length}</span>
              </div>
              <button
                type="button"
                className="fde-link-btn"
                onClick={() => void loadStaged()}
                disabled={loading}
              >
                {loading ? "加载…" : "刷新"}
              </button>
            </div>
            {staged.length === 0 ? (
              <div className="fde-empty">
                <span className="fde-empty-glyph">∅</span>
                还没有暂存的技能。在上面的对话里让 FDE 走完「访谈 → 方案 →
                生成」，或在下面新建一个空骨架。
              </div>
            ) : (
              <div className="fde-staged-list">
                {staged.map((item) => {
                  const pending = item.open_questions?.length || 0;
                  const active = selectedName === item.skill_name;
                  return (
                    <button
                      type="button"
                      key={item.skill_name}
                      className={`fde-staged-card${active ? " is-active" : ""}`}
                      onClick={() => selectStaged(item.skill_name)}
                    >
                      <div className="fde-staged-top">
                        <span className="fde-staged-name">
                          {item.skill_name}
                        </span>
                        <span
                          className={`fde-pill fde-pill--${pending ? "warn" : "muted"}`}
                        >
                          {pending ? `待确认 ${pending}` : "草稿"}
                        </span>
                      </div>
                      <div className="fde-staged-target">
                        <span className="fde-arrow">→</span>
                        {item.target_workspace || "未标注目标"}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section className="fde-section">
            <div className="fde-section-head">
              <div className="fde-section-title">新建空骨架</div>
            </div>
            <div className="fde-form">
              <input
                className="fde-field"
                placeholder="技能名（小写字母 / 数字 / 连字符）"
                value={genName}
                onChange={(e) => setGenName(e.target.value)}
              />
              <label className="fde-form-label">
                目标业务智能体
                <select
                  className="fde-field"
                  value={genWorkspace}
                  onChange={(e) => {
                    if (e.target.value === NEW_AGENT_SENTINEL) {
                      setCreateAgentFor("gen");
                    } else {
                      setGenWorkspace(e.target.value);
                    }
                  }}
                >
                  {agentOptions(genWorkspace)}
                </select>
              </label>
              <textarea
                className="fde-field"
                placeholder="一句话描述这个数字员工要做什么（可选）"
                value={genDescription}
                onChange={(e) => setGenDescription(e.target.value)}
              />
              <button
                type="button"
                className="fde-btn fde-btn--primary"
                onClick={() => void handleGenerate()}
                disabled={busy === "generate" || !available}
              >
                {busy === "generate" ? "生成中…" : "生成骨架"}
              </button>
            </div>
          </section>
        </div>

        <div className="fde-col">
          {!detail ? (
            <section className="fde-section fde-board-empty">
              <span className="fde-board-glyph">{selectedName ? "…" : "▤"}</span>
              <p>
                {selectedName
                  ? "正在加载技能详情…"
                  : "从左侧选一个暂存技能，在这里审查代码、查看自检结果，并确认安装。"}
              </p>
            </section>
          ) : (
            <>
              <section className="fde-section">
                <div className="fde-section-head">
                  <div className="fde-section-title">{detail.skill_name}</div>
                  <label className="fde-install-target">
                    安装到
                    <select
                      className="fde-field"
                      value={installTarget || targetWorkspace}
                      onChange={(e) => {
                        if (e.target.value === NEW_AGENT_SENTINEL) {
                          setCreateAgentFor("install");
                        } else {
                          setInstallTarget(e.target.value);
                        }
                      }}
                    >
                      {agentOptions(installTarget || targetWorkspace)}
                    </select>
                  </label>
                </div>
                <SelfcheckBanner result={detail.selfcheck} />
                <div className="fde-action-bar">
                  <button
                    type="button"
                    className="fde-btn fde-btn--ghost"
                    onClick={() => void handleSelfcheck()}
                    disabled={busy === "selfcheck"}
                  >
                    {busy === "selfcheck" ? "自检中…" : "重新自检"}
                  </button>
                  <button
                    type="button"
                    className="fde-btn fde-btn--ghost"
                    onClick={() => void handleProbe()}
                    disabled={busy === "probe"}
                  >
                    {busy === "probe" ? "试跑中…" : "沙箱试跑 diagnose"}
                  </button>
                  <button
                    type="button"
                    className="fde-btn fde-btn--primary"
                    onClick={() => void handleInstall()}
                    disabled={
                      busy === "install" || !detail.selfcheck?.ready_for_review
                    }
                    title={
                      detail.selfcheck?.ready_for_review
                        ? undefined
                        : "自检未通过，先修正"
                    }
                  >
                    {busy === "install"
                      ? "安装中…"
                      : `确认安装到 ${installTarget || targetWorkspace || "?"}`}
                  </button>
                  <button
                    type="button"
                    className="fde-btn fde-btn--danger"
                    onClick={() => void handleDiscard()}
                    disabled={busy === "discard"}
                  >
                    丢弃
                  </button>
                </div>
                {probe ? (
                  <div
                    className={`fde-terminal${probe.ok ? "" : " is-error"}`}
                  >
                    <div className="fde-terminal-bar">
                      <span className="fde-terminal-dot" />
                      <span className="fde-terminal-dot" />
                      <span className="fde-terminal-dot" />
                      <span className="fde-terminal-title">
                        chat_skill_bridge.py diagnose
                      </span>
                    </div>
                    <pre>
                      {probe.ok
                        ? probe.stdout || "(无输出)"
                        : probe.error ||
                          probe.stderr ||
                          probe.stdout ||
                          "(失败，无输出)"}
                    </pre>
                  </div>
                ) : null}
              </section>

              <section className="fde-section fde-code-section">
                <div className="fde-section-head">
                  <div className="fde-section-title">
                    代码
                    <span className="fde-count">{detail.files.length}</span>
                  </div>
                </div>
                <div className="fde-code">
                  <div className="fde-code-tree">
                    {detail.files.map((f) => (
                      <button
                        key={f.path}
                        type="button"
                        className={`fde-code-file${
                          activeFile === f.path ? " is-active" : ""
                        }`}
                        onClick={() => setActiveFile(f.path)}
                        title={f.path}
                      >
                        {f.path}
                      </button>
                    ))}
                  </div>
                  <pre className="fde-code-pane">
                    {activeFileContent ?? "选一个文件查看内容"}
                  </pre>
                </div>
              </section>
            </>
          )}
        </div>
      </div>

      <FdeCreateAgentModal
        open={createAgentFor !== null}
        defaultModel={defaultModel}
        onCreated={handleAgentCreated}
        onClose={() => setCreateAgentFor(null)}
      />
    </div>
  );
}

export default FdeWorkbenchPanel;
