import { useEffect, useMemo, useState } from "react";

import {
  DIAGNOSIS_TOKEN_CLEAR,
  type DiagnosisSettingsPayload,
  type MaskedSecret,
  type ProviderSettingsApi,
} from "../../api/settings";

export interface ProviderFieldDesc {
  key: string;
  label: string;
  sensitive?: boolean;
  hint?: string;
  placeholder?: string;
}

interface ProviderSettingsSectionProps {
  api: ProviderSettingsApi;
  title: string;
  description: string;
  fields: ProviderFieldDesc[];
}

function isMaskedSecret(value: unknown): value is MaskedSecret {
  return (
    typeof value === "object" &&
    value !== null &&
    "masked" in value &&
    "is_set" in value
  );
}

/**
 * Generic settings section for a model-provider adapter (Qiming / Xingchen).
 * Data-driven: renders one text/password field per descriptor, with the same
 * "DB override > env > default" semantics as the INOE section — masked
 * secrets, "留空则不修改", per-field 恢复默认, and a single 保存 button.
 */
export default function ProviderSettingsSection({
  api,
  title,
  description,
  fields,
}: ProviderSettingsSectionProps) {
  const [payload, setPayload] = useState<DiagnosisSettingsPayload | null>(
    null,
  );
  // Plain (non-sensitive) field values being edited.
  const [draft, setDraft] = useState<Record<string, string>>({});
  // Sensitive field inputs; start empty (empty = keep stored secret).
  const [secretDraft, setSecretDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);

  const plainKeys = useMemo(
    () => fields.filter((f) => !f.sensitive).map((f) => f.key),
    [fields],
  );

  const applyPayload = (next: DiagnosisSettingsPayload) => {
    setPayload(next);
    const nextDraft: Record<string, string> = {};
    plainKeys.forEach((key) => {
      const value = next.effective[key];
      nextDraft[key] = isMaskedSecret(value) ? "" : String(value ?? "");
    });
    setDraft(nextDraft);
    setSecretDraft({});
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const next = await api.get();
        if (!cancelled) {
          applyPayload(next);
          setNotice(null);
        }
      } catch (error) {
        if (!cancelled) {
          setNotice({
            type: "error",
            text: error instanceof Error ? error.message : "设置加载失败",
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
    // api/fields are stable for a given mounted section.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = useMemo(() => {
    if (!payload) {
      return false;
    }
    if (Object.values(secretDraft).some((v) => v.trim() !== "")) {
      return true;
    }
    return plainKeys.some((key) => {
      const current = (draft[key] ?? "").trim();
      const effective = String(payload.effective[key] ?? "");
      return current !== effective;
    });
  }, [payload, draft, secretDraft, plainKeys]);

  const handleSave = async () => {
    if (!payload || saving) {
      return;
    }
    const body: Record<string, string> = {};
    plainKeys.forEach((key) => {
      const current = (draft[key] ?? "").trim();
      if (current !== String(payload.effective[key] ?? "")) {
        body[key] = current;
      }
    });
    Object.entries(secretDraft).forEach(([key, value]) => {
      if (value.trim() !== "") {
        body[key] = value.trim();
      }
    });
    if (Object.keys(body).length === 0) {
      setNotice({ type: "success", text: "没有需要保存的改动" });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      const next = await api.update(body);
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

  const handleResetField = async (field: ProviderFieldDesc) => {
    if (saving) {
      return;
    }
    setNotice(null);
    try {
      const next = field.sensitive
        ? await api.update({ [field.key]: DIAGNOSIS_TOKEN_CLEAR })
        : await api.reset(field.key);
      applyPayload(next);
      setNotice({ type: "success", text: "已恢复为环境默认值" });
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "恢复默认失败",
      });
    }
  };

  const renderField = (field: ProviderFieldDesc) => {
    const inputId = `provider-${field.key}`;
    const overridden = Boolean(payload?.overrides[field.key]);
    const resetBtn = overridden ? (
      <>
        {"　"}
        <button
          type="button"
          className="settings-link-btn"
          disabled={saving}
          onClick={() => handleResetField(field)}
        >
          恢复默认
        </button>
      </>
    ) : null;

    if (field.sensitive) {
      const eff = payload?.effective[field.key];
      const placeholder =
        isMaskedSecret(eff) && eff.is_set
          ? `已设置（${eff.masked}），留空则不修改`
          : "未设置，留空则不修改";
      return (
        <div className="portal-form-group settings-field" key={field.key}>
          <label htmlFor={inputId}>{field.label}</label>
          <input
            id={inputId}
            type="password"
            autoComplete="new-password"
            value={secretDraft[field.key] ?? ""}
            disabled={loading || saving}
            placeholder={placeholder}
            onChange={(event) =>
              setSecretDraft((cur) => ({
                ...cur,
                [field.key]: event.target.value,
              }))
            }
          />
          <small>
            {field.hint}
            {resetBtn}
          </small>
        </div>
      );
    }

    const envValue = payload?.env[field.key];
    const envHint =
      !isMaskedSecret(envValue) && String(envValue ?? "") !== ""
        ? `　环境默认：${String(envValue)}`
        : "";
    return (
      <div className="portal-form-group settings-field" key={field.key}>
        <label htmlFor={inputId}>{field.label}</label>
        <input
          id={inputId}
          type="text"
          value={draft[field.key] ?? ""}
          disabled={loading || saving}
          placeholder={field.placeholder}
          onChange={(event) =>
            setDraft((cur) => ({ ...cur, [field.key]: event.target.value }))
          }
        />
        <small>
          {field.hint}
          {envHint}
          {resetBtn}
        </small>
      </div>
    );
  };

  return (
    <div className="portal-model-shell">
      <section className="settings-section">
        <div className="portal-model-block-head">
          <div>
            <h4>{title}</h4>
            <p>{description}</p>
          </div>
        </div>

        {notice ? (
          <div className={`settings-notice ${notice.type}`}>{notice.text}</div>
        ) : null}

        <div className="settings-form-grid">{fields.map(renderField)}</div>

        <div className="portal-model-form-actions compact-row">
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
