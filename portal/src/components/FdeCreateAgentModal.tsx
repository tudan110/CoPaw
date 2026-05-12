import { useEffect, useMemo, useState } from "react";

import { modelsApi, type ProviderInfo } from "../api/models";
import { portalAgentsApi } from "../api/portalAgents";

const ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$/;

function eligibleProviders(providers: ProviderInfo[]) {
  return providers
    .filter((p) => {
      const hasModels =
        (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
      if (!hasModels) {
        return false;
      }
      if (p.require_api_key === false) {
        return Boolean(p.base_url);
      }
      if (p.is_custom) {
        return Boolean(p.base_url);
      }
      if (p.require_api_key ?? true) {
        return Boolean(p.api_key);
      }
      return true;
    })
    .map((p) => ({
      id: p.id,
      name: p.name,
      models: [...(p.models ?? []), ...(p.extra_models ?? [])],
    }));
}

export function FdeCreateAgentModal({
  open,
  defaultModel,
  onCreated,
  onClose,
}: {
  open: boolean;
  /** Pre-select this provider/model if it's still eligible. */
  defaultModel?: { provider_id?: string; model?: string } | null;
  onCreated: (agentId: string, agentName: string) => void;
  onClose: () => void;
}) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [workspaceDir, setWorkspaceDir] = useState("");
  const [providerId, setProviderId] = useState("");
  const [modelId, setModelId] = useState("");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setId("");
    setName("");
    setDescription("");
    setWorkspaceDir("");
    setError(null);
    setSubmitting(false);
    setLoadingProviders(true);
    modelsApi
      .listProviders()
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setProviders(list);
        const elig = eligibleProviders(list);
        const wantProvider = defaultModel?.provider_id || "";
        const pick =
          elig.find((p) => p.id === wantProvider) || elig[0] || null;
        if (pick) {
          setProviderId(pick.id);
          const wantModel = defaultModel?.model || "";
          setModelId(
            pick.models.find((m) => m.id === wantModel)?.id ||
              pick.models[0]?.id ||
              "",
          );
        } else {
          setProviderId("");
          setModelId("");
        }
      })
      .catch(() => setProviders([]))
      .finally(() => setLoadingProviders(false));
  }, [open, defaultModel?.provider_id, defaultModel?.model]);

  const elig = useMemo(() => eligibleProviders(providers), [providers]);
  const models = useMemo(
    () => elig.find((p) => p.id === providerId)?.models ?? [],
    [elig, providerId],
  );

  if (!open) {
    return null;
  }

  const idTrim = id.trim();
  const idValid = !idTrim || ID_PATTERN.test(idTrim);

  const submit = async () => {
    if (!name.trim()) {
      setError("请填写智能体名称");
      return;
    }
    if (!idValid) {
      setError("ID 只能用字母/数字/下划线/连字符，且不以连字符开头或结尾");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const ref = await portalAgentsApi.createAgent({
        id: idTrim || undefined,
        name: name.trim(),
        description: description.trim() || undefined,
        workspace_dir: workspaceDir.trim() || undefined,
        skill_names: [],
        active_model:
          providerId && modelId
            ? { provider_id: providerId, model: modelId }
            : undefined,
      });
      onCreated(ref.id, name.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
      setSubmitting(false);
    }
  };

  return (
    <div className="fde-modal-backdrop" onClick={submitting ? undefined : onClose}>
      <div
        className="fde-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="fde-modal-head">
          <span>新建业务智能体</span>
          <button
            type="button"
            className="fde-modal-close"
            onClick={onClose}
            disabled={submitting}
            aria-label="关闭"
          >
            ×
          </button>
        </div>
        <div className="fde-modal-body">
          <p className="fde-modal-hint">
            和 QwenPaw 控制台的「创建智能体」一致 —— 建好后这次生成的技能会装进它。新智能体不会出现在左侧精选清单里，但可正常对话、技能也跑在它里面。
          </p>
          <label className="fde-modal-field">
            <span>
              ID <em>（可选，留空自动生成）</em>
            </span>
            <input
              className={`fde-field${idValid ? "" : " is-invalid"}`}
              placeholder="如 order-export"
              value={id}
              onChange={(e) => setId(e.target.value)}
            />
          </label>
          <label className="fde-modal-field">
            <span>
              名称 <em>（必填）</em>
            </span>
            <input
              className="fde-field"
              placeholder="如 工单导出助手"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="fde-modal-field">
            <span>一句话职责</span>
            <textarea
              className="fde-field"
              placeholder="这个数字员工负责什么"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label className="fde-modal-field">
            <span>
              模型{" "}
              {loadingProviders ? <em>（加载中…）</em> : null}
            </span>
            <div className="fde-modal-model-row">
              <select
                className="fde-field"
                value={providerId}
                onChange={(e) => {
                  setProviderId(e.target.value);
                  const ms =
                    elig.find((p) => p.id === e.target.value)?.models ?? [];
                  setModelId(ms[0]?.id || "");
                }}
              >
                {elig.length === 0 ? (
                  <option value="">（暂无已配置的模型）</option>
                ) : null}
                {elig.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <select
                className="fde-field"
                value={modelId}
                disabled={!providerId}
                onChange={(e) => setModelId(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name || m.id}
                  </option>
                ))}
              </select>
            </div>
          </label>
          <label className="fde-modal-field">
            <span>
              工作区目录 <em>（可选）</em>
            </span>
            <input
              className="fde-field"
              placeholder="~/.qwenpaw/workspaces/<id>"
              value={workspaceDir}
              onChange={(e) => setWorkspaceDir(e.target.value)}
            />
          </label>
          {error ? <div className="fde-modal-err">⚠ {error}</div> : null}
        </div>
        <div className="fde-modal-foot">
          <button
            type="button"
            className="fde-link-btn"
            onClick={onClose}
            disabled={submitting}
          >
            取消
          </button>
          <button
            type="button"
            className="fde-btn fde-btn--primary"
            onClick={() => void submit()}
            disabled={submitting || !name.trim()}
          >
            {submitting ? "创建中…" : "创建并选用"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default FdeCreateAgentModal;
