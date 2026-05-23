import { useEffect, useMemo, useState } from "react";
import {
  readConversationProcessRecordDisplayMode,
  writeConversationProcessRecordDisplayMode,
  type ConversationProcessRecordDisplayMode,
} from "./conversationSettings";
import {
  readFaultAnalysisConfidenceVisible,
  writeFaultAnalysisConfidenceVisible,
} from "./faultAnalysisSettings";
import {
  settingsApi,
  type NotificationChannelScopeConfig,
  type NotificationChannelSettings,
} from "../../api/settings";

const SETTINGS_TABS = [
  {
    id: "conversation",
    label: "对话",
    iconClass: "fa-comments",
    description: "过程记录、回复体验等对话偏好设置",
  },
  {
    id: "diagnosis",
    label: "诊断",
    iconClass: "fa-stethoscope",
    description: "根因分析、诊断卡片等结果展示偏好",
  },
  {
    id: "notifications",
    label: "通知",
    iconClass: "fa-paper-plane",
    description: "巡检、建单后的 webhook 推送配置",
  },
] as const;

type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];
type NotificationScopeId = string;
type NotificationChannelForm = Omit<NotificationChannelScopeConfig, "timeout_seconds"> & {
  timeout_seconds: string;
};

const BUILTIN_NOTIFICATION_SCOPE_IDS = [
  "inspection",
  "alarm_analyst",
  "order_workflow",
] as const;

const NOTIFICATION_SCOPE_META: Record<string, {
  id: NotificationScopeId;
  label: string;
  iconClass: string;
  description: string;
}> = {
  inspection: {
    id: "inspection",
    label: "巡检结果推送",
    iconClass: "fa-stethoscope",
    description: "inspection-analyst 完成巡检后自动推送结果。",
  },
  alarm_analyst: {
    id: "alarm_analyst",
    label: "alarm-analyst 建单推送",
    iconClass: "fa-ticket",
    description: "alarm-analyst 自动建单成功后推送结果。",
  },
  order_workflow: {
    id: "order_workflow",
    label: "order 工单建单推送",
    iconClass: "fa-sitemap",
    description: "order-workflow 创建工单成功后推送结果；order 技能会优先读取这里。",
  },
};

const NOTIFICATION_TARGET_OPTIONS = [
  {
    id: "order_workflow",
    label: "order 工单建单推送",
    description: "用于当前 order-workflow 创建工单后的通知。",
  },
  {
    id: "inspection",
    label: "巡检结果推送",
    description: "用于 inspection-analyst 巡检结果通知。",
  },
  {
    id: "alarm_analyst",
    label: "alarm-analyst 建单推送",
    description: "用于 alarm-analyst 自动建单后的通知。",
  },
  {
    id: "__custom__",
    label: "自定义作用位置",
    description: "预留给后续新的 skill 或推送场景。",
  },
] as const;

const CUSTOM_NOTIFICATION_TARGET_ID = "__custom__";
const NOTIFICATION_SCOPE_ID_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;

const EMPTY_NOTIFICATION_SCOPE = (): NotificationChannelForm => ({
  push_url: "",
  dingtalk_webhook_url: "",
  dingtalk_secret: "",
  feishu_webhook_url: "",
  feishu_secret: "",
  timeout_seconds: "8",
  mention_all: false,
});

function toNotificationForm(config?: NotificationChannelScopeConfig | null): NotificationChannelForm {
  if (!config) {
    return EMPTY_NOTIFICATION_SCOPE();
  }
  return {
    push_url: config.push_url || "",
    dingtalk_webhook_url: config.dingtalk_webhook_url || "",
    dingtalk_secret: config.dingtalk_secret || "",
    feishu_webhook_url: config.feishu_webhook_url || "",
    feishu_secret: config.feishu_secret || "",
    timeout_seconds: String(config.timeout_seconds || 8),
    mention_all: Boolean(config.mention_all),
  };
}

function createNotificationForms(
  settings?: Partial<NotificationChannelSettings> | null,
): Record<NotificationScopeId, NotificationChannelForm> {
  const forms: Record<NotificationScopeId, NotificationChannelForm> = {};
  for (const scope of BUILTIN_NOTIFICATION_SCOPE_IDS) {
    forms[scope] = toNotificationForm(settings?.[scope]);
  }
  Object.entries(settings || {}).forEach(([scope, config]) => {
    forms[scope] = toNotificationForm(config);
  });
  return forms;
}

function getNotificationScopeLabel(scope: NotificationScopeId) {
  return NOTIFICATION_SCOPE_META[scope]?.label || scope;
}

function getNotificationScopeMeta(scope: NotificationScopeId) {
  return NOTIFICATION_SCOPE_META[scope] || {
    id: scope,
    label: scope,
    iconClass: "fa-paper-plane",
    description: `自定义通知作用位置：${scope}`,
  };
}

function getSortedNotificationScopes(
  forms: Record<NotificationScopeId, NotificationChannelForm>,
) {
  const existing = new Set(Object.keys(forms));
  const builtinScopes = BUILTIN_NOTIFICATION_SCOPE_IDS.filter((scope) => existing.has(scope));
  const customScopes = Object.keys(forms)
    .filter((scope) => !BUILTIN_NOTIFICATION_SCOPE_IDS.includes(scope as (typeof BUILTIN_NOTIFICATION_SCOPE_IDS)[number]))
    .sort((left, right) => left.localeCompare(right));
  return [...builtinScopes, ...customScopes];
}

function notificationFormsEqual(
  left: NotificationChannelForm,
  right: NotificationChannelForm,
) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function serializeNotificationForm(
  form: NotificationChannelForm,
): NotificationChannelScopeConfig {
  const timeoutSeconds = Number.parseInt(form.timeout_seconds, 10);
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
    throw new Error("通知超时时间必须是大于 0 的整数");
  }

  return {
    push_url: form.push_url.trim(),
    dingtalk_webhook_url: form.dingtalk_webhook_url.trim(),
    dingtalk_secret: form.dingtalk_secret.trim(),
    feishu_webhook_url: form.feishu_webhook_url.trim(),
    feishu_secret: form.feishu_secret.trim(),
    timeout_seconds: timeoutSeconds,
    mention_all: form.mention_all,
  };
}

export function SettingsPanel() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>("conversation");
  const [processRecordDisplayMode, setProcessRecordDisplayMode] =
    useState<ConversationProcessRecordDisplayMode>(() =>
      readConversationProcessRecordDisplayMode(),
    );
  const [showFaultAnalysisConfidence, setShowFaultAnalysisConfidence] =
    useState(() => readFaultAnalysisConfidenceVisible());
  const [notificationForms, setNotificationForms] = useState<Record<
    NotificationScopeId,
    NotificationChannelForm
  >>(() => createNotificationForms());
  const [savedNotificationForms, setSavedNotificationForms] = useState<Record<
    NotificationScopeId,
    NotificationChannelForm
  >>(() => createNotificationForms());
  const [notificationLoading, setNotificationLoading] = useState(true);
  const [notificationNotice, setNotificationNotice] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [savingNotificationScope, setSavingNotificationScope] =
    useState<NotificationScopeId | null>(null);
  const [newNotificationTarget, setNewNotificationTarget] =
    useState<string>("order_workflow");
  const [newCustomNotificationScope, setNewCustomNotificationScope] = useState("");

  const handleProcessRecordModeChange = (mode: ConversationProcessRecordDisplayMode) => {
    setProcessRecordDisplayMode(writeConversationProcessRecordDisplayMode(mode));
  };
  const handleFaultAnalysisConfidenceVisibilityChange = (visible: boolean) => {
    setShowFaultAnalysisConfidence(writeFaultAnalysisConfidenceVisible(visible));
  };

  useEffect(() => {
    let cancelled = false;

    const loadNotificationSettings = async () => {
      setNotificationLoading(true);
      try {
        const payload = await settingsApi.getNotificationChannels();
        if (cancelled) {
          return;
        }
        const nextForms = createNotificationForms(payload);
        setNotificationForms(nextForms);
        setSavedNotificationForms(nextForms);
        setNotificationNotice(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setNotificationNotice({
          type: "error",
          text: error instanceof Error ? error.message : "通知设置加载失败",
        });
      } finally {
        if (!cancelled) {
          setNotificationLoading(false);
        }
      }
    };

    void loadNotificationSettings();

    return () => {
      cancelled = true;
    };
  }, []);

  const notificationScopeIds = useMemo(
    () => getSortedNotificationScopes(notificationForms),
    [notificationForms],
  );

  const notificationDirty = useMemo(() => {
    const dirty: Record<NotificationScopeId, boolean> = {};
    Object.keys(notificationForms).forEach((scope) => {
      dirty[scope] = !notificationFormsEqual(
        notificationForms[scope],
        savedNotificationForms[scope] || EMPTY_NOTIFICATION_SCOPE(),
      );
    });
    return dirty;
  }, [notificationForms, savedNotificationForms]);

  const handleNotificationFieldChange = <
    TKey extends keyof NotificationChannelForm,
  >(
    scope: NotificationScopeId,
    key: TKey,
    value: NotificationChannelForm[TKey],
  ) => {
    setNotificationForms((current) => ({
      ...current,
      [scope]: {
        ...current[scope],
        [key]: value,
      },
    }));
  };

  const handleResetNotificationScope = (scope: NotificationScopeId) => {
    setNotificationForms((current) => {
      if (!savedNotificationForms[scope]) {
        const next = { ...current };
        delete next[scope];
        return next;
      }
      return {
        ...current,
        [scope]: {
          ...savedNotificationForms[scope],
        },
      };
    });
    setNotificationNotice(null);
  };

  const handleSaveNotificationScope = async (scope: NotificationScopeId) => {
    try {
      setSavingNotificationScope(scope);
      const payload = await settingsApi.updateNotificationChannels({
        [scope]: serializeNotificationForm(notificationForms[scope]),
      });
      const nextForms = createNotificationForms(payload);
      setNotificationForms(nextForms);
      setSavedNotificationForms(nextForms);
      setNotificationNotice({
        type: "success",
        text: `${getNotificationScopeLabel(scope)}配置已保存`,
      });
    } catch (error) {
      setNotificationNotice({
        type: "error",
        text: error instanceof Error ? error.message : "通知设置保存失败",
      });
    } finally {
      setSavingNotificationScope(null);
    }
  };

  const handleAddNotificationScope = () => {
    const scope = newNotificationTarget === CUSTOM_NOTIFICATION_TARGET_ID
      ? newCustomNotificationScope.trim()
      : newNotificationTarget;

    if (!NOTIFICATION_SCOPE_ID_PATTERN.test(scope)) {
      setNotificationNotice({
        type: "error",
        text: "作用位置标识只能使用 1-64 位字母、数字、下划线、短横线或点号，并且必须以字母开头",
      });
      return;
    }

    if (notificationForms[scope]) {
      setNotificationNotice({
        type: "success",
        text: `${getNotificationScopeLabel(scope)}已存在，可直接编辑`,
      });
      return;
    }

    setNotificationForms((current) => ({
      ...current,
      [scope]: EMPTY_NOTIFICATION_SCOPE(),
    }));
    setNotificationNotice({
      type: "success",
      text: `${getNotificationScopeLabel(scope)}已添加，填写后保存生效`,
    });
    setNewCustomNotificationScope("");
  };

  const handleDeleteNotificationScope = async (scope: NotificationScopeId) => {
    if (BUILTIN_NOTIFICATION_SCOPE_IDS.includes(scope as (typeof BUILTIN_NOTIFICATION_SCOPE_IDS)[number])) {
      return;
    }
    if (!savedNotificationForms[scope]) {
      setNotificationForms((current) => {
        const next = { ...current };
        delete next[scope];
        return next;
      });
      setNotificationNotice(null);
      return;
    }

    try {
      setSavingNotificationScope(scope);
      const payload = await settingsApi.deleteNotificationChannel(scope);
      const nextForms = createNotificationForms(payload);
      setNotificationForms(nextForms);
      setSavedNotificationForms(nextForms);
      setNotificationNotice({
        type: "success",
        text: `${scope} 配置已删除`,
      });
    } catch (error) {
      setNotificationNotice({
        type: "error",
        text: error instanceof Error ? error.message : "通知设置删除失败",
      });
    } finally {
      setSavingNotificationScope(null);
    }
  };

  return (
    <div className="model-config-page settings-page">
      <div className="model-config-body">
        <div className="model-config-static">
          <div className="portal-model-page-header">
            <div className="portal-model-page-title">
              设置 <small>偏好与默认行为</small>
            </div>
          </div>
        </div>

        <div className="model-config-scroll">
          <div className="settings-layout">
            <aside className="portal-advanced-config-panel settings-tab-panel">
              <div className="settings-tab-panel-title">设置分类</div>
              <div className="settings-tab-list" role="tablist" aria-label="设置分类">
                {SETTINGS_TABS.map((tab) => {
                  const active = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      className={active ? "settings-tab active" : "settings-tab"}
                      onClick={() => setActiveTab(tab.id)}
                    >
                      <span className="settings-tab-icon">
                        <i className={`fas ${tab.iconClass}`} />
                      </span>
                      <span className="settings-tab-copy">
                        <strong>{tab.label}</strong>
                        <small>{tab.description}</small>
                      </span>
                    </button>
                  );
                })}
              </div>
            </aside>

            <section className="portal-advanced-config-panel settings-content-panel">
              {activeTab === "conversation" ? (
                <div className="portal-model-shell">
                  <section className="settings-section">
                    <div className="portal-model-block-head">
                      <div>
                        <h4>过程记录默认展开方式</h4>
                        <p>
                          控制对话里的“过程记录”默认展开还是折叠。流式回复过程中也会遵循这里的设置，避免展示状态前后不一致。
                        </p>
                      </div>
                    </div>

                    <div className="settings-choice-grid">
                      <button
                        type="button"
                        className={processRecordDisplayMode === "expanded"
                          ? "portal-managed-config-toggle active"
                          : "portal-managed-config-toggle"}
                        onClick={() => handleProcessRecordModeChange("expanded")}
                      >
                        <i className="fas fa-angles-down" />
                        默认展开
                      </button>
                      <button
                        type="button"
                        className={processRecordDisplayMode === "collapsed"
                          ? "portal-managed-config-toggle active"
                          : "portal-managed-config-toggle"}
                        onClick={() => handleProcessRecordModeChange("collapsed")}
                      >
                        <i className="fas fa-angles-right" />
                        默认折叠
                      </button>
                    </div>

                    <div className="portal-managed-config-hint settings-inline-hint">
                      当前默认：{processRecordDisplayMode === "expanded" ? "展开过程记录" : "折叠过程记录"}
                    </div>
                  </section>
                </div>
              ) : null}

              {activeTab === "diagnosis" ? (
                <div className="portal-model-shell">
                  <section className="settings-section">
                    <div className="portal-model-block-head">
                      <div>
                        <h4>根因分析卡片是否展示置信度</h4>
                        <p>
                          控制故障根因分析 skill 的卡片里是否展示置信度，包括右上角徽标和“定位置信度”等字段，避免影响用户判断。
                        </p>
                      </div>
                    </div>

                    <div className="settings-choice-grid">
                      <button
                        type="button"
                        className={showFaultAnalysisConfidence
                          ? "portal-managed-config-toggle active"
                          : "portal-managed-config-toggle"}
                        onClick={() => handleFaultAnalysisConfidenceVisibilityChange(true)}
                      >
                        <i className="fas fa-eye" />
                        展示置信度
                      </button>
                      <button
                        type="button"
                        className={!showFaultAnalysisConfidence
                          ? "portal-managed-config-toggle active"
                          : "portal-managed-config-toggle"}
                        onClick={() => handleFaultAnalysisConfidenceVisibilityChange(false)}
                      >
                        <i className="fas fa-eye-slash" />
                        隐藏置信度
                      </button>
                    </div>

                    <div className="portal-managed-config-hint settings-inline-hint">
                      当前默认：{showFaultAnalysisConfidence ? "展示根因分析置信度" : "隐藏根因分析置信度"}
                    </div>
                  </section>
                </div>
              ) : null}

              {activeTab === "notifications" ? (
                <div className="portal-model-shell">
                  <section className="settings-section">
                    <div className="portal-model-block-head">
                      <div>
                        <h4>通知推送配置</h4>
                        <p>
                          将巡检结果与自动建单结果直接推送到应用、钉钉和飞书。相关 skill
                          会优先读取这里的设置，未设置时再回退到原有 `.env` 配置。
                        </p>
                      </div>
                    </div>

                    {notificationNotice ? (
                      <div className={`settings-notice ${notificationNotice.type}`}>
                        {notificationNotice.text}
                      </div>
                    ) : null}

                    <section className="portal-advanced-config-panel settings-notification-card">
                      <div className="portal-model-block-head">
                        <div>
                          <h4>
                            <i className="fas fa-plus-circle" /> 新增通知作用位置
                          </h4>
                          <p>
                            选择这组 webhook 要作用的业务位置。当前 order 使用
                            `order_workflow`，后续新 skill 可用自定义标识接入同一配置文件。
                          </p>
                        </div>
                      </div>

                      <div className="settings-form-grid">
                        <div className="portal-form-group settings-field">
                          <label htmlFor="notification-target-scope">作用位置</label>
                          <select
                            id="notification-target-scope"
                            value={newNotificationTarget}
                            disabled={notificationLoading || Boolean(savingNotificationScope)}
                            onChange={(event) => setNewNotificationTarget(event.target.value)}
                          >
                            {NOTIFICATION_TARGET_OPTIONS.map((option) => (
                              <option key={option.id} value={option.id}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          <small>
                            {NOTIFICATION_TARGET_OPTIONS.find((option) => option.id === newNotificationTarget)
                              ?.description || "选择通知配置生效的业务位置。"}
                          </small>
                        </div>

                        {newNotificationTarget === CUSTOM_NOTIFICATION_TARGET_ID ? (
                          <div className="portal-form-group settings-field">
                            <label htmlFor="notification-custom-scope">自定义标识</label>
                            <input
                              id="notification-custom-scope"
                              type="text"
                              value={newCustomNotificationScope}
                              disabled={notificationLoading || Boolean(savingNotificationScope)}
                              onChange={(event) => setNewCustomNotificationScope(event.target.value)}
                              placeholder="例如 web_monitor 或 change_workflow"
                            />
                            <small>只能使用字母、数字、下划线、短横线和点号，并且以字母开头。</small>
                          </div>
                        ) : null}
                      </div>

                      <div className="portal-model-form-actions compact-row">
                        <button
                          type="button"
                          className="portal-model-btn compact"
                          disabled={notificationLoading || Boolean(savingNotificationScope)}
                          onClick={handleAddNotificationScope}
                        >
                          <i className="fas fa-plus" />
                          添加配置
                        </button>
                      </div>
                    </section>

                    <div className="settings-notification-stack">
                      {notificationScopeIds.map((scopeId) => {
                        const scope = getNotificationScopeMeta(scopeId);
                        const form = notificationForms[scopeId] || EMPTY_NOTIFICATION_SCOPE();
                        const dirty = notificationDirty[scopeId];
                        const saving = savingNotificationScope === scopeId;
                        const disabled = notificationLoading || Boolean(savingNotificationScope);
                        const isBuiltin = BUILTIN_NOTIFICATION_SCOPE_IDS.includes(
                          scopeId as (typeof BUILTIN_NOTIFICATION_SCOPE_IDS)[number],
                        );

                        return (
                          <section
                            key={scopeId}
                            className="portal-advanced-config-panel settings-notification-card"
                          >
                            <div className="portal-model-block-head">
                              <div>
                                <h4>
                                  <i className={`fas ${scope.iconClass}`} /> {scope.label}
                                </h4>
                                <p>{scope.description}</p>
                              </div>
                            </div>

                            <div className="settings-form-grid">
                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-push-url`}>消息中心推送地址</label>
                                <input
                                  id={`${scopeId}-push-url`}
                                  type="url"
                                  value={form.push_url}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "push_url",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="http://ip:port/api/push/your-token"
                                />
                                <small>消息中心 `/api/push/{'{token}'}` 应用推送接口。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-timeout`}>通知超时（秒）</label>
                                <input
                                  id={`${scopeId}-timeout`}
                                  type="number"
                                  min="1"
                                  step="1"
                                  value={form.timeout_seconds}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "timeout_seconds",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="8"
                                />
                                <small>超时时间会同时作用于应用、钉钉、飞书通知请求。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-dingtalk-webhook`}>钉钉 Webhook</label>
                                <input
                                  id={`${scopeId}-dingtalk-webhook`}
                                  type="url"
                                  value={form.dingtalk_webhook_url}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "dingtalk_webhook_url",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                                />
                                <small>用于发送 markdown 通知消息。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-dingtalk-secret`}>钉钉加签 Secret</label>
                                <input
                                  id={`${scopeId}-dingtalk-secret`}
                                  type="password"
                                  value={form.dingtalk_secret}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "dingtalk_secret",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="SEC..."
                                />
                                <small>开启钉钉机器人加签时填写；未启用可留空。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-feishu-webhook`}>飞书 Webhook</label>
                                <input
                                  id={`${scopeId}-feishu-webhook`}
                                  type="url"
                                  value={form.feishu_webhook_url}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "feishu_webhook_url",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                                />
                                <small>用于发送 interactive 卡片通知消息。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-feishu-secret`}>飞书签名 Secret</label>
                                <input
                                  id={`${scopeId}-feishu-secret`}
                                  type="password"
                                  value={form.feishu_secret}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "feishu_secret",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="your-feishu-secret"
                                />
                                <small>开启飞书签名校验时填写；未启用可留空。</small>
                              </div>
                            </div>

                            <div className="settings-choice-block">
                              <div className="settings-choice-title">是否 @ 所有人</div>
                              <div className="settings-choice-grid">
                                <button
                                  type="button"
                                  className={form.mention_all
                                    ? "portal-managed-config-toggle active"
                                    : "portal-managed-config-toggle"}
                                  disabled={disabled}
                                  onClick={() => handleNotificationFieldChange(scopeId, "mention_all", true)}
                                >
                                  <i className="fas fa-at" />
                                  开启 @所有人
                                </button>
                                <button
                                  type="button"
                                  className={!form.mention_all
                                    ? "portal-managed-config-toggle active"
                                    : "portal-managed-config-toggle"}
                                  disabled={disabled}
                                  onClick={() => handleNotificationFieldChange(scopeId, "mention_all", false)}
                                >
                                  <i className="fas fa-user-minus" />
                                  不 @所有人
                                </button>
                              </div>
                            </div>

                            <div className="portal-managed-config-hint settings-inline-hint">
                              当前状态：{dirty ? "有未保存修改" : "已与工作空间设置同步"}
                            </div>

                            <div className="portal-model-form-actions compact-row">
                              <button
                                type="button"
                                className="portal-model-btn secondary compact"
                                disabled={disabled || !dirty}
                                onClick={() => handleResetNotificationScope(scopeId)}
                              >
                                重置
                              </button>
                              {!isBuiltin ? (
                                <button
                                  type="button"
                                  className="portal-model-btn secondary compact"
                                  disabled={disabled}
                                  onClick={() => void handleDeleteNotificationScope(scopeId)}
                                >
                                  删除
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="portal-model-btn compact"
                                disabled={disabled || !dirty}
                                onClick={() => void handleSaveNotificationScope(scopeId)}
                              >
                                <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-floppy-disk"}`} />
                                {saving ? "保存中" : "保存"}
                              </button>
                            </div>
                          </section>
                        );
                      })}
                    </div>
                  </section>
                </div>
              ) : null}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
