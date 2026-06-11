import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fdeApi,
  FdeWorkbenchError,
  type FdeInstalledSkill,
  type FdeProbeResult,
  type FdeReviewState,
  type FdeSelfcheckResult,
  type FdeStagedDetail,
  type FdeStagedSummary,
  type FdeWorkbenchInfo,
} from "../../api/fde";
import { SelfcheckReport } from "./SelfcheckReport";
import { FdeConsoleChat } from "../../components/FdeConsoleChat";
import { FdeCreateAgentModal } from "../../components/FdeCreateAgentModal";
import { portalAgentsApi, type AgentSummary } from "../../api/portalAgents";
import "../fde-workbench.css";

const NEW_AGENT_SENTINEL = "__fde_new_agent__";

const FDE_AGENT_ID = "fde";
const FDE_AGENT_NAME = "FDE 交付助手";

// 顺序必须与 currentStep 的闸门映射一致：
// AI 自检（gate 1）在前，人工审查（gate 2）在后，两道都过才能安装。
const PIPELINE_STEPS = [
  { key: "talk", label: "对话生成", hint: "把需求与现状告诉 FDE" },
  { key: "selfcheck", label: "AI 自检", hint: "域审查 + 安全扫描 + 语法" },
  { key: "review", label: "人工审查", hint: "审查代码后标记通过" },
  { key: "install", label: "确认安装", hint: "装进目标业务智能体" },
] as const;

// staged 内部簿记文件：服务端拒绝改写，代码 Tab 里只读展示。
const STAGED_INTERNAL_FILES = new Set(["_fde_meta.json", "GENERATION.md"]);

type Notice = { type: "success" | "error" | "info"; message: string } | null;

function errMsg(error: unknown): string {
  if (error instanceof FdeWorkbenchError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "未知错误";
}

// Mirrors the backend `parse_env_example` — keep the two in sync.
type EnvField = { key: string; default: string; hint: string };

function parseEnvExample(text: string | null | undefined): EnvField[] {
  if (!text) return [];
  const fields: EnvField[] = [];
  let pending: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const stripped = raw.trim();
    if (!stripped) {
      pending = [];
      continue;
    }
    if (stripped.startsWith("#")) {
      pending.push(stripped.replace(/^#+/, "").trim());
      continue;
    }
    const idx = stripped.indexOf("=");
    if (idx <= 0) {
      pending = [];
      continue;
    }
    const key = stripped.slice(0, idx).trim();
    const def = stripped
      .slice(idx + 1)
      .trim()
      .replace(/^["']|["']$/g, "");
    if (!key) {
      pending = [];
      continue;
    }
    fields.push({ key, default: def, hint: pending.join("\n") });
    pending = [];
  }
  return fields;
}

const DOMAIN_UNAVAILABLE_MARKER = "技能领域审核未完成";

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
  // Operator-supplied .env values, keyed by skillName -> {key -> value}.
  // Survives switching between staged skills so half-filled forms don't reset.
  const [envByName, setEnvByName] = useState<
    Record<string, Record<string, string>>
  >({});
  // Surfaced when the previous install failed specifically with the
  // "领域审核服务不可用" finding — gates the "强制安装" override button.
  const [domainBlocked, setDomainBlocked] = useState(false);
  // Cross-agent "已交付技能" view (skills tagged 二开 in any business agent).
  const [installed, setInstalled] = useState<FdeInstalledSkill[]>([]);
  const [installedLoading, setInstalledLoading] = useState(false);
  const [tab, setTab] = useState<"overview" | "code" | "probe">("overview");
  // edited code buffer per path; only dirty files get saved
  const [codeEdits, setCodeEdits] = useState<Record<string, string>>({});
  // guided-field draft for the selected skill
  const [fieldDraft, setFieldDraft] = useState<{
    description: string;
    triggers: string;
  }>({ description: "", triggers: "" });

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

  const loadInstalled = useCallback(async () => {
    setInstalledLoading(true);
    try {
      const res = await fdeApi.listInstalled();
      setInstalled(res.skills || []);
    } catch (error) {
      // non-fatal: just leave the list empty + show a soft notice
      setInstalled([]);
      setNotice((n) =>
        n
          ? n
          : { type: "info", message: `加载已交付技能失败：${errMsg(error)}` },
      );
    } finally {
      setInstalledLoading(false);
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
        void loadInstalled();
      } else if (infoRetryRef.current < 4) {
        // Backend may still be coming up / reloading right after `sync` —
        // give it a few quiet retries before declaring it unavailable.
        infoRetryRef.current += 1;
        window.setTimeout(() => void loadInfo(), 2500);
      }
    },
    [loadStaged, loadAgents, loadInstalled],
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
        message: `已生成骨架 ${result.skill_name}（自检${
          result.selfcheck?.ready_for_review ? "通过" : "未通过"
        }）。接下来在上面的对话里让 FDE 把 runtime/tool_adapters.py 接上真实接口。`,
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

  const applyMutation = useCallback(
    (res: { staged: FdeStagedDetail; selfcheck: FdeSelfcheckResult }) => {
      setDetail({ ...res.staged, selfcheck: res.selfcheck });
    },
    [],
  );

  const handleSaveFields = useCallback(async () => {
    if (!selectedName) return;
    setBusy("save-fields");
    try {
      const env = selectedName ? envByName[selectedName] : undefined;
      const res = await fdeApi.editStagedFields(selectedName, {
        description: fieldDraft.description,
        triggers: fieldDraft.triggers
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        env,
      });
      applyMutation(res);
      setNotice({ type: "success", message: "已保存并重新自检。" });
    } catch (error) {
      setNotice({ type: "error", message: `保存失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName, fieldDraft, envByName, applyMutation]);

  const handleSaveCode = useCallback(async () => {
    if (!selectedName) return;
    const files = Object.entries(codeEdits).map(([path, content]) => ({
      path,
      content,
    }));
    if (files.length === 0) {
      setNotice({ type: "info", message: "没有改动的文件。" });
      return;
    }
    setBusy("save-code");
    try {
      const res = await fdeApi.editStagedFiles(selectedName, files);
      applyMutation(res);
      setCodeEdits({});
      setNotice({ type: "success", message: "代码已保存并重新自检。" });
    } catch (error) {
      setNotice({ type: "error", message: `保存失败：${errMsg(error)}` });
    } finally {
      setBusy(null);
    }
  }, [selectedName, codeEdits, applyMutation]);

  const handleReview = useCallback(
    async (action: "approve" | "reset") => {
      if (!selectedName) return;
      setBusy(`review-${action}`);
      try {
        const res = await fdeApi.reviewStaged(selectedName, action);
        applyMutation(res);
        setNotice({
          type: "success",
          message: action === "approve" ? "已标记审查通过。" : "已撤回审查。",
        });
      } catch (error) {
        setNotice({ type: "error", message: `操作失败：${errMsg(error)}` });
      } finally {
        setBusy(null);
      }
    },
    [selectedName, applyMutation],
  );

  const targetWorkspace = useMemo(() => {
    const fromList = staged.find((s) => s.skill_name === selectedName)
      ?.target_workspace;
    return fromList || "";
  }, [staged, selectedName]);

  useEffect(() => {
    setInstallTarget(targetWorkspace);
    setDomainBlocked(false);
  }, [selectedName, targetWorkspace]);

  const review: FdeReviewState | undefined = detail?.review;
  const reviewOk = review?.effective === "approved";
  const aiOk = Boolean(detail?.selfcheck?.ready_for_review);
  // 加载详情时安全扫描被跳过（秒回）；区分"待体检"与"未通过"。
  const scanPending = detail?.selfcheck?.scan?.status === "skipped";

  // 只在「换了一个技能」时重置 Tab / 未保存编辑 / 引导字段草稿。
  // detail 在自检、保存等操作后也会整体替换 —— 那些场景不能清掉用户
  // 正在编辑的内容，也不该把 Tab 跳回概览。
  const seededSkillRef = useRef<string | null>(null);
  useEffect(() => {
    const name = detail?.skill_name ?? null;
    if (name === seededSkillRef.current) {
      return;
    }
    seededSkillRef.current = name;
    // seed guided fields from the freshly-loaded SKILL.md frontmatter
    setCodeEdits({});
    setTab("overview");
    if (!detail) {
      setFieldDraft({ description: "", triggers: "" });
      return;
    }
    const md = detail.files.find((f) => f.path === "SKILL.md")?.content || "";
    const desc = /^description:\s*(.*)$/m.exec(md)?.[1] || "";
    const trig = /^triggers:\s*\[(.*)\]/m.exec(md)?.[1] || "";
    setFieldDraft({
      description: desc.replace(/^["']|["']$/g, "").trim(),
      triggers: trig
        .split(",")
        .map((s) => s.replace(/^\s*["']?|["']?\s*$/g, ""))
        .filter(Boolean)
        .join(", "),
    });
  }, [detail]);

  // .env.example fields for the currently-selected staged skill, parsed
  // from the file we already fetched with show-staged.
  const envFields = useMemo<EnvField[]>(() => {
    if (!detail) return [];
    const file = detail.files.find(
      (f) => f.path === ".env.example" && typeof f.content === "string",
    );
    return parseEnvExample(file?.content || "");
  }, [detail]);

  const envValuesForSelected = useMemo(
    () => (selectedName ? envByName[selectedName] || {} : {}),
    [envByName, selectedName],
  );

  const updateEnvValue = useCallback(
    (key: string, value: string) => {
      if (!selectedName) return;
      setEnvByName((prev) => {
        const next = { ...(prev[selectedName] || {}) };
        next[key] = value;
        return { ...prev, [selectedName]: next };
      });
    },
    [selectedName],
  );

  const runInstall = useCallback(
    async (
      destOverride: string | null,
      opts: {
        skipDomainCheck?: boolean;
        confirm?: boolean;
        envValues?: Record<string, string>;
      } = {},
    ) => {
      if (!selectedName) {
        return;
      }
      const dest = (destOverride ?? installTarget).trim() || targetWorkspace;
      if (!dest) {
        setNotice({ type: "error", message: "请先选一个目标业务智能体" });
        return;
      }
      const known = new Set(agents.map((a) => a.id));
      const willAutoCreate = !known.has(dest);
      const willOverrideDomain = !!opts.skipDomainCheck;
      const envCount = Object.values(opts.envValues || {}).filter(
        (v) => v && v.trim(),
      ).length;
      if (opts.confirm !== false) {
        const parts: string[] = [];
        if (willOverrideDomain) {
          parts.push(
            `领域审核服务暂时不可用，你已经审过代码、确认是网管/运维域。\n` +
              `点击确认会跳过这一项检查继续安装（其他安全扫描仍会跑）。`,
          );
        }
        if (willAutoCreate) {
          parts.push(
            `目标业务智能体 “${dest}” 还不存在，会先用它做 id 自动建一个，再装技能。`,
          );
        } else {
          parts.push(
            `把技能 “${selectedName}” 装到业务智能体 “${dest}” 的工作区。`,
          );
        }
        if (envCount > 0) {
          parts.push(`同时把 ${envCount} 项凭证写入该技能的 .env。`);
        }
        parts.push("安装会再走一遍安全扫描，「二开」标签启用。");
        if (!window.confirm(parts.join("\n\n"))) {
          return;
        }
      }
      setBusy(willOverrideDomain ? "install-force" : "install");
      try {
        const result = await fdeApi.installStaged(
          selectedName,
          dest !== targetWorkspace ? dest : undefined,
          {
            skipDomainCheck: opts.skipDomainCheck,
            envValues: opts.envValues,
          },
        );
        setDomainBlocked(false);
        const created = result.target_created;
        const envWritten = result.env_written || [];
        const mirror = result.gateway_mirror;
        const fragments = [
          created
            ? `已自动创建业务智能体 ${result.target_workspace}，并把技能 ${result.name} 装进它的工作区`
            : `已把技能 ${result.name} 装进业务智能体 ${result.target_workspace} 的工作区`,
          `标签：${result.tag}`,
        ];
        if (mirror?.mirrored) {
          fragments.push(
            `已同时镜像到 ${mirror.gateway_agent}（portal 入口直接可用）`,
          );
        } else if (mirror?.skipped_reason) {
          fragments.push(`gateway 镜像未做：${mirror.skipped_reason}`);
        }
        fragments.push(
          mirror?.mirrored
            ? "在 portal 入口直接说就能触发它，或去 employee/" +
                `${result.target_workspace} 那边对话`
            : "在左下『已交付技能』里能直接看到；要触发它，去 employee/" +
                `${result.target_workspace} 那边对话`,
        );
        if (result.domain_override_applied) {
          fragments.push("（已跳过领域审核 - 操作员确认）");
        }
        if (envWritten.length > 0) {
          fragments.push(`凭证已写入：${envWritten.join(" / ")}`);
        }
        if (result.env_error) {
          fragments.push(`但 .env 写入失败：${result.env_error}`);
        }
        setNotice({
          type: result.env_error ? "info" : "success",
          message: fragments.join("；") + "。",
        });
        if (created) {
          await loadAgents();
        }
        // Refresh the "已交付技能" list — this is where the user expects to
        // find the just-installed skill (the upstream skill pool panel is
        // gateway-only, so cross-agent installs were previously invisible).
        void loadInstalled();
      } catch (error) {
        const msg = errMsg(error);
        const isDomainIssue = msg.includes(DOMAIN_UNAVAILABLE_MARKER);
        setDomainBlocked(isDomainIssue);
        setNotice({
          type: "error",
          message: isDomainIssue
            ? `安装失败（领域审核服务暂时不可用）：${msg}\n如代码已审过，可以点下方的「强制安装」跳过该项检查。`
            : `安装失败：${msg}`,
        });
      } finally {
        setBusy(null);
      }
    },
    [
      selectedName,
      targetWorkspace,
      installTarget,
      agents,
      loadAgents,
      loadInstalled,
    ],
  );

  const handleInstall = useCallback(() => {
    const env = selectedName ? envByName[selectedName] : undefined;
    void runInstall(null, { envValues: env });
  }, [runInstall, selectedName, envByName]);

  const handleForceInstall = useCallback(() => {
    const env = selectedName ? envByName[selectedName] : undefined;
    void runInstall(null, { skipDomainCheck: true, envValues: env });
  }, [runInstall, selectedName, envByName]);

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

  const handleDeleteInstalled = useCallback(
    async (skill: FdeInstalledSkill) => {
      if (
        !window.confirm(
          `确认从业务智能体 “${skill.agent_id}” 的工作区删除技能 “${skill.skill_name}” 吗？\n` +
            `\n这会：\n` +
            `  1) 把它从 ${skill.agent_id} 工作区移除（先 disable 再 delete）；\n` +
            `  2) 同名的 gateway 镜像（如果有）一并清掉，避免留下孤儿代码。\n\n` +
            `如果只是想换个智能体放，用旁边的「迁移到其他智能体…」更安全。`,
        )
      ) {
        return;
      }
      setBusy(`delete-${skill.agent_id}-${skill.skill_name}`);
      try {
        const result = await fdeApi.deleteInstalled(
          skill.agent_id,
          skill.skill_name,
        );
        const fragments = [
          `已删除 ${result.target_workspace} 工作区的 ${result.skill_name}`,
        ];
        if (result.gateway_mirror_removed) {
          fragments.push("gateway 镜像也清掉了");
        } else if (result.gateway_mirror_skipped_reason) {
          fragments.push(result.gateway_mirror_skipped_reason);
        }
        setNotice({
          type: "success",
          message: fragments.join("；") + "。",
        });
        void loadInstalled();
      } catch (error) {
        setNotice({
          type: "error",
          message: `删除失败：${errMsg(error)}`,
        });
      } finally {
        setBusy(null);
      }
    },
    [loadInstalled],
  );

  const handleMigrateInstalled = useCallback(
    async (skill: FdeInstalledSkill) => {
      // Quick path: prompt for target id. Could later be a proper modal,
      // but a prompt covers the common "fix wrong destination" case in
      // one click without dragging in a whole picker UI.
      const knownIds = agents
        .map((a) => a.id)
        .filter((id) => id !== skill.agent_id);
      const hint =
        knownIds.length > 0
          ? `\n\n已有业务智能体（建议从中选）：\n  ${knownIds.join("  /  ")}`
          : "";
      const dest = window.prompt(
        `把技能 “${skill.skill_name}” 迁到哪个业务智能体？\n` +
          `当前在：${skill.agent_id}` +
          hint +
          "\n\n直接输入目标 id；不存在的会自动建空壳再装。",
        "",
      );
      if (!dest) return;
      const target = dest.trim();
      if (!target || target === skill.agent_id) return;
      const move = window.confirm(
        `确认把 “${skill.skill_name}” 从 ${skill.agent_id} 迁到 ${target}？\n\n` +
          `点【确定】= 迁移（也删掉源 ${skill.agent_id} 那份）\n` +
          `点【取消】= 不动\n\n` +
          "（如果只想「复制一份留底」，取消后从 cli/手动复制吧 —— 面板默认是迁移）",
      );
      if (!move) return;
      setBusy(`migrate-${skill.skill_name}`);
      try {
        const result = await fdeApi.copyInstalled(
          skill.agent_id,
          skill.skill_name,
          target,
          { removeSource: true },
        );
        const fragments = [
          result.target_created
            ? `已自动创建 ${result.target_workspace}，并迁入技能 ${result.name}`
            : `已迁入 ${result.target_workspace}`,
          result.removed_source
            ? `源 ${result.source_agent} 已清除`
            : `源 ${result.source_agent} 没能清除`,
          `标签：${result.tag}`,
        ];
        if (result.remove_error) {
          fragments.push(`清除源失败原因：${result.remove_error}`);
        }
        setNotice({
          type: result.remove_error ? "info" : "success",
          message: fragments.join("；") + "。",
        });
        void loadInstalled();
        if (result.target_created) {
          await loadAgents();
        }
      } catch (error) {
        setNotice({
          type: "error",
          message: `迁移失败：${errMsg(error)}`,
        });
      } finally {
        setBusy(null);
      }
    },
    [agents, loadInstalled, loadAgents],
  );

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
    infoLoading || info === null ? "loading" : info.available ? "ok" : "down";
  const available = heroState === "ok";
  // 步进贴合状态：没选→对话生成；选了但 AI 自检没过→AI 自检；
  // AI 自检过、人工审查没过→人工审查；两道闸门都过→确认安装。
  const currentStep = !selectedName ? 0 : !aiOk ? 1 : !reviewOk ? 2 : 3;

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
              : `FDE 交付助手暂不可用：${
                  info?.reason ||
                  "请先 sync-qwenpaw-working.sh 同步工作区并重启服务"
                }`}
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
              <i className="fas fa-rotate-right" />
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
              <i
                className={`fas ${
                  chatOpen ? "fa-chevron-up" : "fa-chevron-down"
                }`}
              />
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
              展开后可直接和 {FDE_AGENT_NAME}
              对话；它生成技能后会自动出现在右侧。
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
                <i
                  className={`fas ${
                    loading ? "fa-spinner fa-spin" : "fa-arrows-rotate"
                  }`}
                />
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
                          className={`fde-pill fde-pill--${
                            pending ? "warn" : "muted"
                          }`}
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
              <div className="fde-section-title">
                已交付技能
                <span className="fde-count">{installed.length}</span>
              </div>
              <button
                type="button"
                className="fde-link-btn"
                onClick={() => void loadInstalled()}
                disabled={installedLoading}
                title="跨智能体扫描所有带「二开」标签的技能 —— FDE 装出去的都在这里"
              >
                <i
                  className={`fas ${
                    installedLoading ? "fa-spinner fa-spin" : "fa-arrows-rotate"
                  }`}
                />
                {installedLoading ? "扫描…" : "刷新"}
              </button>
            </div>
            {installed.length === 0 ? (
              <div className="fde-empty">
                <span className="fde-empty-glyph">∅</span>
                还没有装出去的技能。在上面的对话里走完「访谈 → 方案 →
                生成」，再点 「确认安装」就会出现在这里。
              </div>
            ) : (
              <div className="fde-staged-list">
                {installed.map((it) => (
                  <div
                    key={`${it.agent_id}/${it.skill_name}`}
                    className="fde-staged-card fde-installed-card"
                    title={
                      `${it.skill_name} → ${it.agent_name}（${it.agent_id}）` +
                      (it.description ? `\n${it.description}` : "")
                    }
                  >
                    <div className="fde-staged-top">
                      <span className="fde-staged-name">{it.skill_name}</span>
                      <span
                        className={`fde-pill fde-pill--${
                          it.enabled ? "ok" : "muted"
                        }`}
                      >
                        {it.enabled ? "已启用" : "未启用"}
                      </span>
                    </div>
                    <div className="fde-staged-target">
                      <span className="fde-arrow">→</span>
                      {it.agent_name}
                      <span className="fde-installed-agent-id">
                        ({it.agent_id})
                      </span>
                    </div>
                    {it.description ? (
                      <div className="fde-installed-desc">{it.description}</div>
                    ) : null}
                    <div className="fde-installed-actions">
                      <button
                        type="button"
                        className="fde-link-btn"
                        onClick={() => void handleMigrateInstalled(it)}
                        disabled={busy === `migrate-${it.skill_name}`}
                        title={
                          "如果 gateway 路由不知道当前所属智能体（比如 FDE 选了个新建的 export），" +
                          "把它迁到正确的业务智能体（如 order / gateway / query）就能被触发"
                        }
                      >
                        <i
                          className={`fas ${
                            busy === `migrate-${it.skill_name}`
                              ? "fa-spinner fa-spin"
                              : "fa-arrow-right-arrow-left"
                          }`}
                        />
                        {busy === `migrate-${it.skill_name}`
                          ? "迁移中…"
                          : "迁移"}
                      </button>
                      <button
                        type="button"
                        className="fde-link-btn fde-link-btn--danger"
                        onClick={() => void handleDeleteInstalled(it)}
                        disabled={
                          busy === `delete-${it.agent_id}-${it.skill_name}`
                        }
                        title="从该业务智能体（以及 gateway 镜像）删掉这个技能"
                      >
                        <i
                          className={`fas ${
                            busy === `delete-${it.agent_id}-${it.skill_name}`
                              ? "fa-spinner fa-spin"
                              : "fa-trash"
                          }`}
                        />
                        {busy === `delete-${it.agent_id}-${it.skill_name}`
                          ? "删除中…"
                          : "删除"}
                      </button>
                    </div>
                  </div>
                ))}
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
                <i
                  className={`fas ${
                    busy === "generate"
                      ? "fa-spinner fa-spin"
                      : "fa-wand-magic-sparkles"
                  }`}
                />
                {busy === "generate" ? "生成中…" : "生成骨架"}
              </button>
            </div>
          </section>
        </div>

        <div className="fde-col">
          {!detail ? (
            <section className="fde-section fde-board-empty">
              <span className="fde-board-glyph">
                {selectedName ? "…" : "▤"}
              </span>
              <p>
                {selectedName
                  ? "正在加载技能详情…"
                  : "从左侧选一个暂存技能，在这里审查代码、查看自检结果，并确认安装。"}
              </p>
            </section>
          ) : (
            <section className="fde-section fde-board">
              {/* 常驻状态条 */}
              <div className="fde-strip">
                <span className="fde-strip-name">{detail.skill_name}</span>
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
                <span className="fde-strip-gap" />
                <span
                  className={`fde-gate ${
                    aiOk ? "is-ok" : scanPending ? "is-wait" : "is-bad"
                  }`}
                  title={
                    scanPending
                      ? "加载只呈现文件（秒回）；点「重新自检」跑安全扫描+语法。域审查在确认安装时校验。"
                      : "AI 自检（安全扫描 + 语法）；域审查在确认安装时校验"
                  }
                >
                  AI自检 {aiOk ? "✓ 通过" : scanPending ? "○ 待体检" : "✗ 未过"}
                </span>
                <span
                  className={`fde-gate ${
                    reviewOk
                      ? "is-ok"
                      : review?.effective === "stale"
                      ? "is-warn"
                      : "is-wait"
                  }`}
                  title="人工审查闸门"
                >
                  人工审查{" "}
                  {reviewOk
                    ? "✓ 通过"
                    : review?.effective === "stale"
                    ? "⚠ 已失效"
                    : "○ 待审"}
                </span>
              </div>

              {/* Tabs */}
              <div className="fde-tabs">
                {(
                  [
                    ["overview", "概览"],
                    ["code", `代码 · ${detail.files.length}`],
                    ["probe", "试跑"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={`fde-tab${tab === key ? " is-on" : ""}`}
                    onClick={() => setTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {tab === "overview" ? (
                <div className="fde-tabpane">
                  <SelfcheckReport result={detail.selfcheck} />
                  <div className="fde-guide">
                    <div className="fde-guide-head">
                      引导字段
                      <span className="fde-report-hint">
                        改完点「保存并重检」
                      </span>
                    </div>
                    <label className="fde-guide-row">
                      <span className="fde-guide-key">描述</span>
                      <input
                        className="fde-field"
                        value={fieldDraft.description}
                        onChange={(e) =>
                          setFieldDraft((d) => ({
                            ...d,
                            description: e.target.value,
                          }))
                        }
                      />
                    </label>
                    <label className="fde-guide-row">
                      <span className="fde-guide-key">触发词</span>
                      <input
                        className="fde-field"
                        placeholder="逗号分隔"
                        value={fieldDraft.triggers}
                        onChange={(e) =>
                          setFieldDraft((d) => ({
                            ...d,
                            triggers: e.target.value,
                          }))
                        }
                      />
                    </label>
                    {envFields.map((field) => (
                      <label className="fde-guide-row" key={field.key}>
                        <span className="fde-guide-key" title={field.key}>
                          {field.key}
                        </span>
                        <input
                          className="fde-field"
                          type={
                            /token|secret|password|cookie|key|auth/i.test(
                              field.key,
                            )
                              ? "password"
                              : "text"
                          }
                          placeholder={field.default || "（留空表示暂不配置）"}
                          value={envValuesForSelected[field.key] || ""}
                          onChange={(e) =>
                            updateEnvValue(field.key, e.target.value)
                          }
                          autoComplete="off"
                          spellCheck={false}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ) : tab === "code" ? (
                <div className="fde-tabpane fde-code">
                  <div className="fde-code-tree">
                    {detail.files.map((f) => (
                      <button
                        key={f.path}
                        type="button"
                        className={`fde-code-file${
                          activeFile === f.path ? " is-active" : ""
                        }${codeEdits[f.path] != null ? " is-dirty" : ""}`}
                        onClick={() => setActiveFile(f.path)}
                        title={f.path}
                      >
                        {f.path}
                        {codeEdits[f.path] != null ? " ●" : ""}
                      </button>
                    ))}
                  </div>
                  {(() => {
                    const file = detail.files.find(
                      (f) => f.path === activeFile,
                    );
                    const editable = Boolean(
                      file &&
                        !file.binary &&
                        !file.truncated &&
                        !STAGED_INTERNAL_FILES.has(file.path),
                    );
                    const value =
                      activeFile != null && codeEdits[activeFile] != null
                        ? codeEdits[activeFile]
                        : activeFileContent ?? "";
                    return (
                      <textarea
                        className="fde-code-edit"
                        value={value}
                        readOnly={!editable}
                        title={
                          editable
                            ? undefined
                            : "该文件只读（内部簿记 / 二进制 / 超大文件）"
                        }
                        spellCheck={false}
                        onChange={(e) => {
                          if (!activeFile) return;
                          const v = e.target.value;
                          setCodeEdits((prev) => ({
                            ...prev,
                            [activeFile]: v,
                          }));
                        }}
                      />
                    );
                  })()}
                </div>
              ) : (
                <div className="fde-tabpane">
                  <button
                    type="button"
                    className="fde-btn fde-btn--ghost"
                    onClick={() => void handleProbe()}
                    disabled={busy === "probe"}
                  >
                    <i
                      className={`fas ${
                        busy === "probe" ? "fa-spinner fa-spin" : "fa-play"
                      }`}
                    />
                    {busy === "probe" ? "试跑中…" : "沙箱试跑 diagnose"}
                  </button>
                  {probe ? (
                    <div
                      className={`fde-terminal${probe.ok ? "" : " is-error"}`}
                    >
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
                </div>
              )}

              {/* Sticky footer：双闸门 + 安装 */}
              <div className="fde-foot">
                <button
                  type="button"
                  className="fde-btn fde-btn--ghost"
                  onClick={() => void handleSelfcheck()}
                  disabled={busy === "selfcheck"}
                  title="不改动，仅重新跑一遍 AI 自检"
                >
                  {busy === "selfcheck" ? "自检中…" : "重新自检"}
                </button>
                <button
                  type="button"
                  className="fde-btn fde-btn--ghost"
                  onClick={() =>
                    void (tab === "code"
                      ? handleSaveCode()
                      : handleSaveFields())
                  }
                  disabled={busy === "save-fields" || busy === "save-code"}
                >
                  {busy === "save-fields" || busy === "save-code"
                    ? "保存中…"
                    : "保存并重检"}
                </button>
                <span className="fde-foot-gap" />
                {reviewOk ? (
                  <button
                    type="button"
                    className="fde-btn fde-btn--ghost"
                    onClick={() => void handleReview("reset")}
                    disabled={busy === "review-reset"}
                  >
                    撤回审查
                  </button>
                ) : (
                  <button
                    type="button"
                    className="fde-btn fde-btn--warn"
                    onClick={() => void handleReview("approve")}
                    disabled={busy === "review-approve" || !aiOk}
                    title={aiOk ? undefined : "AI 自检未通过，先修正"}
                  >
                    {busy === "review-approve" ? "标记中…" : "审查通过 ▸"}
                  </button>
                )}
                <button
                  type="button"
                  className="fde-btn fde-btn--primary"
                  onClick={() => void handleInstall()}
                  disabled={
                    busy === "install" ||
                    busy === "install-force" ||
                    !aiOk ||
                    !reviewOk
                  }
                  title={
                    !aiOk
                      ? "AI 自检未通过"
                      : !reviewOk
                      ? "人工审查未通过"
                      : undefined
                  }
                >
                  {busy === "install"
                    ? "安装中…"
                    : `确认安装到 ${installTarget || targetWorkspace || "?"}`}
                </button>
                {domainBlocked ? (
                  <button
                    type="button"
                    className="fde-btn fde-btn--warn"
                    onClick={() => void handleForceInstall()}
                    disabled={busy === "install" || busy === "install-force"}
                  >
                    {busy === "install-force"
                      ? "强制安装中…"
                      : "强制安装（领域审核暂不可用）"}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="fde-btn fde-btn--danger"
                  onClick={() => void handleDiscard()}
                  disabled={busy === "discard"}
                >
                  丢弃
                </button>
              </div>
            </section>
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
