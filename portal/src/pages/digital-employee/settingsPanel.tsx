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
type NotificationScopeId = keyof NotificationChannelSettings;
type NotificationChannelForm = Omit<NotificationChannelScopeConfig, "timeout_seconds"> & {
  timeout_seconds: string;
};

const NOTIFICATION_SCOPE_META: Array<{
  id: NotificationScopeId;
  label: string;
  iconClass: string;
  description: string;
}> = [
  {
    id: "inspection",
    label: "巡检结果推送",
    iconClass: "fa-stethoscope",
    description: "inspection-analyst 完成巡检后自动推送结果。",
  },
  {
    id: "alarm_analyst",
    label: "alarm-analyst 建单推送",
    iconClass: "fa-ticket",
    description: "alarm-analyst 自动建单成功后推送结果。",
  },
  {
    id: "order_workflow",
    label: "order-workflow 建单推送",
    iconClass: "fa-sitemap",
    description: "order-workflow 创建工单成功后推送结果。",
  },
];

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
  return {
    inspection: toNotificationForm(settings?.inspection),
    alarm_analyst: toNotificationForm(settings?.alarm_analyst),
    order_workflow: toNotificationForm(settings?.order_workflow),
  };
}

function getNotificationScopeLabel(scope: NotificationScopeId) {
  return NOTIFICATION_SCOPE_META.find((item) => item.id === scope)?.label || scope;
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

  const notificationDirty = useMemo(
    () => ({
      inspection: !notificationFormsEqual(
        notificationForms.inspection,
        savedNotificationForms.inspection,
      ),
      alarm_analyst: !notificationFormsEqual(
        notificationForms.alarm_analyst,
        savedNotificationForms.alarm_analyst,
      ),
      order_workflow: !notificationFormsEqual(
        notificationForms.order_workflow,
        savedNotificationForms.order_workflow,
      ),
    }),
    [notificationForms, savedNotificationForms],
  );

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
    setNotificationForms((current) => ({
      ...current,
      [scope]: {
        ...savedNotificationForms[scope],
      },
    }));
    setNotificationNotice(null);
  };

  const handleSaveNotificationScope = async (scope: NotificationScopeId) => {
    try {
      setSavingNotificationScope(scope);
      const payload = await settingsApi.updateNotificationChannels({
        [scope]: serializeNotificationForm(notificationForms[scope]),
      });
      const nextScopeForm = toNotificationForm(payload[scope]);
      setNotificationForms((current) => ({
        ...current,
        [scope]: nextScopeForm,
      }));
      setSavedNotificationForms((current) => ({
        ...current,
        [scope]: nextScopeForm,
      }));
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

  return (
    <div className="model-config-page settings-page">
      <div className="model-config-body">
        <div className="model-config-scroll">
          <div className="portal-model-page-header">
            <div className="portal-model-page-title">
              设置 <small>偏好与默认行为</small>
            </div>
          </div>

          <div className="portal-model-scope-bar settings-scope-bar">
            <span>配置范围：浏览器偏好 + 当前工作空间</span>
            <span>切换类型：使用顶部 Tab 分类管理</span>
            <span>已支持：过程记录、诊断展示、通知推送地址</span>
          </div>

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
                      <div className="settings-sync-badge">
                        {notificationLoading ? "读取中..." : "当前工作空间"}
                      </div>
                    </div>

                    {notificationNotice ? (
                      <div className={`settings-notice ${notificationNotice.type}`}>
                        {notificationNotice.text}
                      </div>
                    ) : null}

                    <div className="settings-notification-stack">
                      {NOTIFICATION_SCOPE_META.map((scope) => {
                        const form = notificationForms[scope.id];
                        const dirty = notificationDirty[scope.id];
                        const saving = savingNotificationScope === scope.id;
                        const disabled = notificationLoading || Boolean(savingNotificationScope);

                        return (
                          <section
                            key={scope.id}
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
                                <label htmlFor={`${scope.id}-push-url`}>消息中心推送地址</label>
                                <input
                                  id={`${scope.id}-push-url`}
                                  type="url"
                                  value={form.push_url}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scope.id,
                                      "push_url",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="http://ip:port/api/push/your-token"
                                />
                                <small>消息中心 `/api/push/{'{token}'}` 应用推送接口。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scope.id}-timeout`}>通知超时（秒）</label>
                                <input
                                  id={`${scope.id}-timeout`}
                                  type="number"
                                  min="1"
                                  step="1"
                                  value={form.timeout_seconds}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scope.id,
                                      "timeout_seconds",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="8"
                                />
                                <small>超时时间会同时作用于应用、钉钉、飞书通知请求。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scope.id}-dingtalk-webhook`}>钉钉 Webhook</label>
                                <input
                                  id={`${scope.id}-dingtalk-webhook`}
                                  type="url"
                                  value={form.dingtalk_webhook_url}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scope.id,
                                      "dingtalk_webhook_url",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                                />
                                <small>用于发送 markdown 通知消息。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scope.id}-dingtalk-secret`}>钉钉加签 Secret</label>
                                <input
                                  id={`${scope.id}-dingtalk-secret`}
                                  type="password"
                                  value={form.dingtalk_secret}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scope.id,
                                      "dingtalk_secret",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="SEC..."
                                />
                                <small>开启钉钉机器人加签时填写；未启用可留空。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scope.id}-feishu-webhook`}>飞书 Webhook</label>
                                <input
                                  id={`${scope.id}-feishu-webhook`}
                                  type="url"
                                  value={form.feishu_webhook_url}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scope.id,
                                      "feishu_webhook_url",
                                      event.target.value,
                                    );
                                  }}
                                  placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                                />
                                <small>用于发送 interactive 卡片通知消息。</small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scope.id}-feishu-secret`}>飞书签名 Secret</label>
                                <input
                                  id={`${scope.id}-feishu-secret`}
                                  type="password"
                                  value={form.feishu_secret}
                                  disabled={disabled}
                                  onChange={(event) => {
                                    handleNotificationFieldChange(
                                      scope.id,
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
                                  onClick={() => handleNotificationFieldChange(scope.id, "mention_all", true)}
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
                                  onClick={() => handleNotificationFieldChange(scope.id, "mention_all", false)}
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
                                onClick={() => handleResetNotificationScope(scope.id)}
                              >
                                重置
                              </button>
                              <button
                                type="button"
                                className="portal-model-btn compact"
                                disabled={disabled || !dirty}
                                onClick={() => void handleSaveNotificationScope(scope.id)}
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
