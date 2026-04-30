import { useState } from "react";
import {
  readConversationProcessRecordDisplayMode,
  writeConversationProcessRecordDisplayMode,
  type ConversationProcessRecordDisplayMode,
} from "./conversationSettings";

const SETTINGS_TABS = [
  {
    id: "conversation",
    label: "对话",
    iconClass: "fa-comments",
    description: "过程记录、回复体验等对话偏好设置",
  },
] as const;

type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];

export function SettingsPanel() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>("conversation");
  const [processRecordDisplayMode, setProcessRecordDisplayMode] =
    useState<ConversationProcessRecordDisplayMode>(() =>
      readConversationProcessRecordDisplayMode(),
    );

  const handleProcessRecordModeChange = (mode: ConversationProcessRecordDisplayMode) => {
    setProcessRecordDisplayMode(writeConversationProcessRecordDisplayMode(mode));
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
            <span>配置范围：当前浏览器</span>
            <span>切换类型：使用顶部 Tab 分类管理</span>
            <span>已支持：过程记录默认展开方式</span>
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
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
