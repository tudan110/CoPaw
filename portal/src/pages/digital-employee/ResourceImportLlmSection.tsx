import { useEffect, useMemo, useState } from "react";

import {
  resourceImportLlmApi,
  type ResourceImportLlmPayload,
} from "../../api/settings";

interface ModelRow {
  base_url: string;
  model: string;
  vision_model: string;
  apiKey: string; // draft; "" = keep stored key for this row
}

function emptyRow(): ModelRow {
  return { base_url: "", model: "", vision_model: "", apiKey: "" };
}

/**
 * Resource-import LLM pool: 2 tuning scalars + a dynamic, add/remove list of
 * OpenAI-compatible models (round-robin per sheet). api_key is masked on
 * read; leaving a row's key blank keeps the stored one.
 */
export default function ResourceImportLlmSection() {
  const [payload, setPayload] = useState<ResourceImportLlmPayload | null>(
    null,
  );
  const [parallelism, setParallelism] = useState("4");
  const [timeout, setTimeoutValue] = useState("45");
  const [models, setModels] = useState<ModelRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);

  const applyPayload = (next: ResourceImportLlmPayload) => {
    setPayload(next);
    setParallelism(String(next.scalars.sheet_parallelism));
    setTimeoutValue(String(next.scalars.step_timeout));
    setModels(
      next.models.map((m) => ({
        base_url: m.base_url,
        model: m.model,
        vision_model: m.vision_model,
        apiKey: "",
      })),
    );
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const next = await resourceImportLlmApi.get();
        if (!cancelled) {
          applyPayload(next);
          setNotice(null);
        }
      } catch (error) {
        if (!cancelled) {
          setNotice({
            type: "error",
            text: error instanceof Error ? error.message : "加载失败",
          });
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const dirty = useMemo(() => {
    if (!payload) {
      return false;
    }
    if (String(payload.scalars.sheet_parallelism) !== parallelism.trim()) {
      return true;
    }
    if (String(payload.scalars.step_timeout) !== timeout.trim()) {
      return true;
    }
    if (models.length !== payload.models.length) {
      return true;
    }
    return models.some((row, i) => {
      const saved = payload.models[i];
      if (!saved) {
        return true;
      }
      return (
        row.apiKey.trim() !== "" ||
        row.base_url.trim() !== saved.base_url ||
        row.model.trim() !== saved.model ||
        row.vision_model.trim() !== saved.vision_model
      );
    });
  }, [payload, parallelism, timeout, models]);

  const updateRow = (index: number, patch: Partial<ModelRow>) => {
    setModels((cur) =>
      cur.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  };

  const handleSave = async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      const next = await resourceImportLlmApi.update({
        scalars: {
          sheet_parallelism: Math.max(1, Number(parallelism) || 4),
          step_timeout: Math.max(1, Number(timeout) || 45),
        },
        models: models.map((m) => ({
          base_url: m.base_url.trim(),
          model: m.model.trim(),
          vision_model: m.vision_model.trim(),
          api_key: m.apiKey.trim(),
        })),
      });
      applyPayload(next);
      setNotice({ type: "success", text: "已保存" });
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "保存失败",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="portal-model-shell">
      <section className="settings-section">
        <div className="portal-model-block-head">
          <div>
            <h4>资源导入 LLM 池</h4>
            <p>
              资源导入字段映射用的 OpenAI 兼容模型池（多模型按 sheet
              轮询分担，降低单模型 TPM 压力）。留空 api_key 表示不修改。
            </p>
          </div>
        </div>

        {notice ? (
          <div className={`settings-notice ${notice.type}`}>{notice.text}</div>
        ) : null}

        <div className="settings-form-grid">
          <div className="portal-form-group settings-field">
            <label htmlFor="ril-parallelism">并发解析 sheet 数</label>
            <input
              id="ril-parallelism"
              type="number"
              min={1}
              step={1}
              value={parallelism}
              disabled={loading || saving}
              onChange={(e) => setParallelism(e.target.value)}
            />
            <small>每次并发解析的 sheet 数（默认 4）。</small>
          </div>
          <div className="portal-form-group settings-field">
            <label htmlFor="ril-timeout">单步 LLM 超时（秒）</label>
            <input
              id="ril-timeout"
              type="number"
              min={1}
              step={1}
              value={timeout}
              disabled={loading || saving}
              onChange={(e) => setTimeoutValue(e.target.value)}
            />
            <small>单个字段映射步骤的 LLM 超时（默认 45）。</small>
          </div>
        </div>

        {models.map((row, index) => {
          const saved = payload?.models[index];
          const keyPlaceholder =
            saved && saved.api_key.is_set
              ? `已设置（${saved.api_key.masked}），留空则不修改`
              : "未设置，留空则不修改";
          return (
            <div
              key={index}
              className="portal-form-group settings-field"
              style={{
                border: "1px solid var(--border-color, #e5e7eb)",
                borderRadius: 8,
                padding: 12,
                marginTop: 10,
              }}
            >
              <div className="settings-form-grid">
                <div className="portal-form-group settings-field">
                  <label>模型 {index + 1} · Base URL</label>
                  <input
                    type="text"
                    value={row.base_url}
                    disabled={loading || saving}
                    placeholder="https://host/v1"
                    onChange={(e) =>
                      updateRow(index, { base_url: e.target.value })
                    }
                  />
                </div>
                <div className="portal-form-group settings-field">
                  <label>模型名（model）</label>
                  <input
                    type="text"
                    value={row.model}
                    disabled={loading || saving}
                    onChange={(e) =>
                      updateRow(index, { model: e.target.value })
                    }
                  />
                </div>
                <div className="portal-form-group settings-field">
                  <label>API Key</label>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={row.apiKey}
                    disabled={loading || saving}
                    placeholder={keyPlaceholder}
                    onChange={(e) =>
                      updateRow(index, { apiKey: e.target.value })
                    }
                  />
                </div>
                <div className="portal-form-group settings-field">
                  <label>视觉模型（可选）</label>
                  <input
                    type="text"
                    value={row.vision_model}
                    disabled={loading || saving}
                    placeholder="留空则用上面的 model"
                    onChange={(e) =>
                      updateRow(index, { vision_model: e.target.value })
                    }
                  />
                </div>
              </div>
              <small>
                <button
                  type="button"
                  className="settings-link-btn"
                  disabled={saving}
                  onClick={() =>
                    setModels((cur) => cur.filter((_, i) => i !== index))
                  }
                >
                  删除此模型
                </button>
              </small>
            </div>
          );
        })}

        <div className="portal-model-form-actions compact-row">
          <button
            type="button"
            className="settings-link-btn"
            disabled={loading || saving}
            onClick={() => setModels((cur) => [...cur, emptyRow()])}
          >
            ＋ 添加模型
          </button>
          <button
            type="button"
            className="portal-model-btn compact"
            disabled={loading || saving || !dirty}
            onClick={handleSave}
          >
            <i className="fas fa-floppy-disk" />
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </section>
    </div>
  );
}
