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
  diagnosisSettingsApi,
  inoeSettingsApi,
  qimingSettingsApi,
  xingchenSettingsApi,
  kunlunSettingsApi,
  zgopsSettingsApi,
  operatorSettingsApi,
  orderSettingsApi,
  n9eSettingsApi,
  ssoSettingsApi,
  DIAGNOSIS_TOKEN_CLEAR,
  type NotificationChannelScopeConfig,
  type NotificationChannelSettings,
  type DiagnosisSettingsPayload,
  type MaskedSecret,
} from "../../api/settings";
import ProviderSettingsSection, {
  type ProviderFieldDesc,
} from "./ProviderSettingsSection";
import ResourceImportLlmSection from "./ResourceImportLlmSection";

// Editable numeric fields in the diagnosis tab, grouped for rendering.
type DiagnosisNumberField = {
  key: string;
  label: string;
  group: "polling" | "query_window" | "recovery" | "alarm_analyst";
  min?: number;
  max?: number;
  step?: number;
  hint: string;
};

const DIAGNOSIS_NUMBER_FIELDS: DiagnosisNumberField[] = [
  {
    key: "auto_takeover_interval_seconds",
    label: "轮询间隔（秒）",
    group: "polling",
    min: 60,
    step: 10,
    hint: "两轮自动接管之间的间隔，最小 60 秒。调大可降低分析频率、省 token。",
  },
  {
    key: "auto_takeover_limit",
    label: "每轮抓取告警数",
    group: "polling",
    min: 1,
    step: 1,
    hint: "每轮最多拉取并评估多少条告警。",
  },
  {
    key: "max_active_analyses",
    label: "最大并发分析数",
    group: "polling",
    min: 1,
    step: 1,
    hint: "同时进行的告警分析数量，直接决定并发调用大模型的规模。",
  },
  {
    key: "alarm_analyst_metric_timeout_seconds",
    label: "告警分析·接口超时（秒）",
    group: "alarm_analyst",
    min: 1,
    step: 10,
    hint: "alarm-analyst 拉取指标定义的请求超时，接口较慢可调大。",
  },
  {
    key: "alarm_analyst_metric_page_size",
    label: "告警分析·分页大小",
    group: "alarm_analyst",
    min: 1,
    step: 10,
    hint: "每页拉取多少条指标定义，配合翻页。",
  },
  {
    key: "inspection_metric_timeout_seconds",
    label: "巡检·接口超时（秒）",
    group: "alarm_analyst",
    min: 1,
    step: 10,
    hint: "inspection-analyst 拉取指标定义的请求超时，接口较慢可调大。",
  },
  {
    key: "inspection_metric_page_size",
    label: "巡检·分页大小",
    group: "alarm_analyst",
    min: 1,
    step: 10,
    hint: "每页拉取多少条指标定义（巡检脚本默认 100），配合翻页。",
  },
  {
    key: "analysis_lookback_hours",
    label: "分析回溯（小时）",
    group: "polling",
    min: 0,
    max: 720,
    step: 1,
    hint:
      "开启实时分析后，分析最近 N 小时内仍在更新的活动告警（按最新告警时间）；" +
      "0 = 仅分析开启后还在刷新的。重新开关会重新锚定起点。",
  },
  {
    key: "timezone_offset_hours",
    label: "时区偏移（小时）",
    group: "query_window",
    min: -12,
    max: 14,
    step: 1,
    hint: "告警平台时间的时区偏移，默认东八区 8。",
  },
  {
    key: "cache_ttl_seconds",
    label: "告警列表刷新间隔（秒）",
    group: "query_window",
    min: 0,
    step: 5,
    hint: "前台告警列表多久向平台重新拉取一次数据，默认 30 秒。",
  },
  {
    key: "alarm_list_limit",
    label: "告警列表条数",
    group: "query_window",
    min: 1,
    max: 200,
    step: 1,
    hint: "前台告警列表与告警角标计数最多展示多少条，上限 200。",
  },
  {
    key: "alarm_query_window_hours",
    label: "告警查询时间窗（小时）",
    group: "query_window",
    min: 1,
    step: 1,
    hint: "按最新告警时间拉取：只取最近这么多小时内仍在更新的活动告警。默认 24；调小会漏掉一段时间没再上报但仍未恢复的告警。",
  },
  {
    key: "recovery_verify_delay_seconds",
    label: "首次验证延迟（秒）",
    group: "recovery",
    min: 0,
    step: 30,
    hint: "收到清除通知后等待多久做首次恢复验证，给指标留回落时间。",
  },
  {
    key: "recovery_verify_retry_count",
    label: "验证重试次数",
    group: "recovery",
    min: 0,
    step: 1,
    hint: "验证未通过时的最大重试次数，超过后判定为未恢复/未知。",
  },
  {
    key: "recovery_verify_retry_interval_seconds",
    label: "重试间隔（秒）",
    group: "recovery",
    min: 10,
    step: 30,
    hint: "两次验证之间的间隔。",
  },
  {
    key: "recovery_observation_minutes",
    label: "复发观察期（分钟）",
    group: "recovery",
    min: 0,
    step: 5,
    hint: "验证通过后继续观察是否复发的时长，0 表示关闭观察。",
  },
  {
    key: "recovery_verify_batch_limit",
    label: "每轮验证上限",
    group: "recovery",
    min: 1,
    step: 1,
    hint: "验证循环每个周期最多处理的清除事件数，防止指标查询被打满。",
  },
];

const DIAGNOSIS_GROUP_META: {
  id: "polling" | "query_window" | "recovery" | "alarm_analyst";
  title: string;
  description: string;
}[] = [
  {
    id: "polling",
    title: "轮询与并发",
    description: "控制自动接管的频率、批量与并发，直接影响 token 消耗。",
  },
  {
    id: "query_window",
    title: "告警查询窗口",
    description: "时区与缓存等查询相关参数。",
  },
  {
    id: "recovery",
    title: "恢复验证",
    description:
      "INOE 推送告警清除通知后，自动复核活动列表并验证关键指标是否真正恢复。",
  },
  {
    id: "alarm_analyst",
    title: "指标拉取（告警分析 / 巡检）",
    description:
      "告警分析与巡检 skill 从平台拉取指标定义的请求超时与分页大小。处置建议详细展示模式可切换三级结构化输出。",
  },
];

// INOE gateway connection lives in its own settings tab (see inoeSettingsApi).
// It is shared infrastructure (monitoring overview, real-alarm list,
// workorders), not a diagnosis-only knob.
const INOE_TEXT_FIELD = {
  key: "inoe_api_base_url",
  label: "INOE 网关地址",
  placeholder: "http://gateway:8080",
  hint: "平台网关 base URL。",
};
const INOE_NUMBER_FIELD = {
  key: "inoe_api_timeout_seconds",
  label: "INOE 接口超时（秒）",
  min: 1,
  step: 1,
  hint: "调用平台网关的请求超时。",
};
const INOE_TOKEN_KEY = "inoe_api_token";
const INOE_BOOL_FIELD = {
  key: "inoe_enable_curl_fallback",
  label: "启用 curl 兜底",
  hint: "调用网关失败（网络异常）时，技能自动改用系统 curl 重试一次。",
};

function isMaskedSecret(value: unknown): value is MaskedSecret {
  return (
    typeof value === "object" &&
    value !== null &&
    "masked" in value &&
    "is_set" in value
  );
}

const SETTINGS_TABS = [
  {
    id: "conversation",
    label: "对话",
    iconClass: "fa-comments",
    description: "过程记录、回复体验等对话偏好设置",
  },
  {
    id: "inoe",
    label: "平台",
    iconClass: "fa-tower-broadcast",
    description: "INOE 平台网关地址、令牌与超时",
  },
  {
    id: "sso",
    label: "单点登录",
    iconClass: "fa-key",
    description: "INOE OAuth2 单点登录的网关、client 凭据与回调地址",
  },
  {
    id: "diagnosis",
    label: "告警 / 巡检",
    iconClass: "fa-stethoscope",
    description: "实时告警分析、根因卡片，以及告警/巡检的指标拉取参数",
  },
  {
    id: "notifications",
    label: "通知",
    iconClass: "fa-paper-plane",
    description: "巡检、建单后的 webhook 推送配置",
  },
  {
    id: "cmdb",
    label: "CMDB / 资源导入",
    iconClass: "fa-database",
    description: "zgops CMDB 连接与资源导入 LLM 池",
  },
  {
    id: "order",
    label: "工单",
    iconClass: "fa-clipboard-list",
    description: "工单（ferry）接口连接，留空回退平台 INOE",
  },
  {
    id: "n9e",
    label: "日志",
    iconClass: "fa-file-lines",
    description: "夜莺（N9E）日志查询连接",
  },
  {
    id: "model-adapters",
    label: "模型适配",
    iconClass: "fa-robot",
    description: "启明、星辰、昆仑网关等大模型 adapter 的网关、凭证与模型",
  },
  {
    id: "operator",
    label: "操作",
    iconClass: "fa-hand-pointer",
    description: "页面操作助手（operator）的菜单接口连接",
  },
] as const;

// SSO field keys match the backend FieldSpec keys in sso_settings_store.py.
const SSO_FIELDS: ProviderFieldDesc[] = [
  {
    key: "sso_userinfo_path",
    label: "用户信息接口路径",
    placeholder: "/admin/user/getInfo",
    hint: "token 直通用它验证登录态并取用户；相对「平台」tab 的 INOE 网关根。默认 /admin/user/getInfo（实测可用）；若同事部署了 /auth/oauth2/userinfo 可改这里。",
  },
  {
    key: "sso_gateway_base_url",
    label: "授权码网关 base_url（可选覆盖）",
    placeholder: "留空 = 平台 INOE 网关地址 + /auth/oauth2",
    hint: "仅授权码模式用；默认自动取「平台」INOE 网关地址 + /auth/oauth2。token 直通不用此项。",
  },
  {
    key: "sso_client_id",
    label: "Client ID（授权码模式）",
    placeholder: "ndai",
    hint: "仅授权码模式需要；token 直通可留空。",
  },
  {
    key: "sso_client_secret",
    label: "Client Secret（授权码模式）",
    sensitive: true,
    hint: "仅授权码模式的 HMAC 签名密钥，只在后端使用；token 直通可留空。",
  },
  {
    key: "sso_redirect_uri",
    label: "回调地址 redirect_uri（授权码模式）",
    placeholder: "https://<portal>/sso/callback",
    hint: "仅授权码模式需要，须与 INOE 白名单一致；token 直通可留空。",
  },
];

const N9E_FIELDS: ProviderFieldDesc[] = [
  {
    key: "n9e_api_base_url",
    label: "N9E 地址（base_url）",
    hint: "夜莺日志网关 base URL。",
    placeholder: "http://host:17001",
  },
  {
    key: "n9e_user_token",
    label: "User Token",
    sensitive: true,
    hint: "夜莺访问令牌，留空则不修改。",
  },
  {
    key: "n9e_log_datasource_id",
    label: "日志数据源 ID",
    hint: "datasource id（默认 1）。",
  },
  {
    key: "n9e_log_index",
    label: "日志索引",
    hint: "如 casaos-syslog-*。",
  },
  {
    key: "n9e_log_timestamp_field",
    label: "时间字段",
    hint: "日志时间戳字段（默认 @timestamp）。",
  },
];

const ZGOPS_FIELDS: ProviderFieldDesc[] = [
  {
    key: "zgops_base_url",
    label: "ZGOPS 地址（base_url）",
    hint: "zgops CMDB 的 base URL。",
    placeholder: "http://host:31089",
  },
  { key: "zgops_username", label: "用户名", hint: "登录账号。" },
  {
    key: "zgops_password",
    label: "密码",
    sensitive: true,
    hint: "登录密码，留空则不修改。",
  },
  {
    key: "zgops_session_name",
    label: "Session 名",
    hint: "会话标识（可选）。",
  },
];

// Menu / page-navigation API fields (page-navigator getRouters). They live in
// the same `inoe` namespace as the platform connection, so they render as a
// second section on the 平台 tab via the shared inoeSettingsApi. Empty
// base_url / token fall back to the INOE connection above.
const INOE_MENU_FIELDS: ProviderFieldDesc[] = [
  {
    key: "inoe_menu_base_url",
    label: "菜单接口地址（可选）",
    hint: "页面导航 getRouters 接口的 base URL，留空则复用上面的 INOE 网关地址。",
    placeholder: "http://host:port",
  },
  {
    key: "inoe_menu_token",
    label: "菜单接口令牌（可选）",
    sensitive: true,
    hint: "留空则复用上面的 INOE 访问令牌。",
  },
  {
    key: "inoe_menu_app_code",
    label: "应用编码（app）",
    hint: "getRouters/{app}，默认 inoe。",
  },
  {
    key: "inoe_menu_timeout_seconds",
    label: "菜单接口超时（秒）",
    hint: "拉取菜单的请求超时，默认 20。",
  },
  {
    key: "inoe_menu_cache_ttl_seconds",
    label: "菜单缓存 TTL（秒）",
    hint: "菜单内存缓存时长，默认 600。",
  },
];

// Operator (page-operator) menu connection — its own OPERATOR_MENU_* env vars,
// independent of page-navigator. Keys match operator_settings_store.
const OPERATOR_FIELDS: ProviderFieldDesc[] = [
  {
    key: "operator_menu_base_url",
    label: "菜单接口地址（可选）",
    hint: "操作助手 getRouters 接口的 base URL，留空则回退共享 INOE 菜单 / 网关地址。",
    placeholder: "http://host:port",
  },
  {
    key: "operator_menu_token",
    label: "菜单接口令牌（可选）",
    sensitive: true,
    hint: "留空则回退共享 INOE 访问令牌。",
  },
  {
    key: "operator_menu_app_code",
    label: "应用编码（app）",
    hint: "getRouters/{app}，默认 inoe。",
  },
  {
    key: "operator_menu_timeout_seconds",
    label: "菜单接口超时（秒）",
    hint: "拉取菜单的请求超时，默认 20。",
  },
  {
    key: "operator_menu_cache_ttl_seconds",
    label: "菜单缓存 TTL（秒）",
    hint: "菜单内存缓存时长，默认 600。",
  },
];

// Work-order (order-workflow / ferry) connection — its own ORDER_* env vars.
// Keys match order_settings_store. Empty 地址 / 令牌 fall back to the shared
// INOE connection (平台 tab).
const ORDER_FIELDS: ProviderFieldDesc[] = [
  {
    key: "order_api_base_url",
    label: "工单接口地址（可选）",
    hint: "ferry 工单 API 的 base URL（如 http://host:port/ferry），留空则回退平台 INOE 地址。",
    placeholder: "http://host:port/ferry",
  },
  {
    key: "order_authorization",
    label: "工单接口令牌（可选）",
    sensitive: true,
    hint: "ferry 的 Authorization（含 Bearer 前缀），留空则回退平台 INOE 令牌。",
  },
  {
    key: "order_timeout_seconds",
    label: "工单接口超时（秒）",
    hint: "工单请求超时，默认 20。",
  },
  {
    key: "order_verify_ssl",
    label: "校验 SSL 证书",
    hint: "是否校验 HTTPS 证书，默认开启（true）。",
  },
  {
    key: "order_enable_curl_fallback",
    label: "启用 curl 回退",
    hint: "请求失败时是否回退到 curl，默认开启（true）。",
  },
];

// Field descriptors for the model-provider settings sections. Keys must
// match the backend FieldSpec keys (qiming_settings_store /
// xingchen_settings_store / kunlun_settings_store). Sensitive fields
// render masked + 留空则不修改.
const QIMING_FIELDS: ProviderFieldDesc[] = [
  {
    key: "qiming_base_url",
    label: "网关地址（base_url）",
    hint: "启明完成接口的 base URL。",
    placeholder: "http://host:port",
  },
  {
    key: "qiming_completions_path",
    label: "完成接口路径",
    hint: "拼在 base_url 后的路径。",
  },
  {
    key: "qiming_completions_url",
    label: "完整完成接口 URL（可选）",
    hint: "设置后直接使用，覆盖 base_url + 路径。",
  },
  { key: "qiming_models", label: "模型列表", hint: "逗号分隔。" },
  { key: "qiming_app_id", label: "App ID", hint: "请求头 X-APP-ID。" },
  {
    key: "qiming_app_key",
    label: "App Key",
    sensitive: true,
    hint: "请求头 X-APP-KEY。",
  },
  {
    key: "qiming_bearer_token",
    label: "Bearer Token（可选）",
    sensitive: true,
    hint: "Authorization 头，留空则不发送。",
  },
];

const XINGCHEN_FIELDS: ProviderFieldDesc[] = [
  {
    key: "xingchen_base_url",
    label: "网关地址（base_url）",
    hint: "星辰对话接口的 base URL。",
    placeholder: "http://host:port",
  },
  {
    key: "xingchen_chat_path",
    label: "对话接口路径",
    hint: "拼在 base_url 后的路径。",
  },
  {
    key: "xingchen_chat_url",
    label: "完整对话接口 URL（可选）",
    hint: "设置后直接使用，覆盖 base_url + 路径。",
  },
  { key: "xingchen_models", label: "模型列表", hint: "逗号分隔。" },
  { key: "xingchen_app_id", label: "App ID", hint: "请求头 X-APP-ID。" },
  {
    key: "xingchen_order_num",
    label: "Order Num",
    hint: "请求头 Order-Num。",
  },
  {
    key: "xingchen_authorization",
    label: "Authorization",
    sensitive: true,
    hint: "鉴权令牌，请求头 Authorization。",
  },
];

const KUNLUN_FIELDS: ProviderFieldDesc[] = [
  {
    key: "kunlun_base_url",
    label: "网关地址（base_url）",
    hint: "昆仑能力开放网关根地址。",
    placeholder: "https://ogw.klnaas.189.cn:21000",
  },
  {
    key: "kunlun_chat_path",
    label: "对话接口路径",
    hint: "拼在 base_url 后的路径（智算大模型会话接口）。",
  },
  {
    key: "kunlun_chat_url",
    label: "完整对话接口 URL（可选）",
    hint: "设置后直接使用，覆盖 base_url + 路径。",
  },
  {
    key: "kunlun_auth_url",
    label: "Token 端点 URL（可选）",
    hint: "OAuth2 client_credentials 换 token 的地址；留空 = base_url + /kunlun-auth-service/oauth2/token。",
  },
  {
    key: "kunlun_app_code",
    label: "App Code",
    hint: "订阅交付物里的 appCode，作 Basic Auth 用户名。",
  },
  {
    key: "kunlun_app_secret",
    label: "App Secret",
    sensitive: true,
    hint: "订阅交付物里的 appSecret，作 Basic Auth 密码。",
  },
  {
    key: "kunlun_sk_key",
    label: "后端大模型凭据（sk-proj）",
    sensitive: true,
    hint: "后端大模型自己的 sk-proj-* 密钥，经 X-Authorization 头下发，网关转成后端 Authorization。填裸 key 即可（含 Bearer 前缀会自动纠正）；留空则不修改。",
  },
  {
    key: "kunlun_models",
    label: "模型列表",
    hint: "逗号分隔。默认 14ebe9de-f4aa-4eeb-830f-45b7821a2ddf（chat 真实 model id，已实测可用）。",
  },
  {
    key: "kunlun_model_id_header",
    label: "X-Model-Id（可选）",
    hint: "应用标识请求头；留空则取请求体里的 model。",
  },
  {
    key: "kunlun_client_id",
    label: "X-Client-Id（可选）",
    hint: "平台标识请求头，网关方给定值 zgops（默认）。实测 curl 未带亦可通；留空则回退默认。",
  },
  {
    key: "kunlun_ai_user_id",
    label: "X-AI-User-Id",
    hint: "调用方用户标识请求头。",
  },
  {
    key: "kunlun_verify_ssl",
    label: "校验网关证书",
    hint: "网关为企业自签证书、官方 SDK 也不校验，默认 False。",
  },
];

type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];
type NotificationScopeId = string;
type NotificationChannelForm = Omit<
  NotificationChannelScopeConfig,
  "timeout_seconds"
> & {
  timeout_seconds: string;
};

const BUILTIN_NOTIFICATION_SCOPE_IDS = [
  "inspection",
  "alarm_analyst",
  "order_workflow",
] as const;

const NOTIFICATION_SCOPE_META: Record<
  string,
  {
    id: NotificationScopeId;
    label: string;
    iconClass: string;
    description: string;
  }
> = {
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
    description:
      "order-workflow 创建工单成功后推送结果；order 技能会优先读取这里。",
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

function toNotificationForm(
  config?: NotificationChannelScopeConfig | null,
): NotificationChannelForm {
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
  return (
    NOTIFICATION_SCOPE_META[scope] || {
      id: scope,
      label: scope,
      iconClass: "fa-paper-plane",
      description: `自定义通知作用位置：${scope}`,
    }
  );
}

function getSortedNotificationScopes(
  forms: Record<NotificationScopeId, NotificationChannelForm>,
) {
  const existing = new Set(Object.keys(forms));
  const builtinScopes = BUILTIN_NOTIFICATION_SCOPE_IDS.filter((scope) =>
    existing.has(scope),
  );
  const customScopes = Object.keys(forms)
    .filter(
      (scope) =>
        !BUILTIN_NOTIFICATION_SCOPE_IDS.includes(
          scope as (typeof BUILTIN_NOTIFICATION_SCOPE_IDS)[number],
        ),
    )
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
  const [notificationForms, setNotificationForms] = useState<
    Record<NotificationScopeId, NotificationChannelForm>
  >(() => createNotificationForms());
  const [savedNotificationForms, setSavedNotificationForms] = useState<
    Record<NotificationScopeId, NotificationChannelForm>
  >(() => createNotificationForms());
  const [notificationLoading, setNotificationLoading] = useState(true);
  const [notificationNotice, setNotificationNotice] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [savingNotificationScope, setSavingNotificationScope] =
    useState<NotificationScopeId | null>(null);
  const [newNotificationTarget, setNewNotificationTarget] =
    useState<string>("order_workflow");
  const [newCustomNotificationScope, setNewCustomNotificationScope] =
    useState("");

  const handleProcessRecordModeChange = (
    mode: ConversationProcessRecordDisplayMode,
  ) => {
    setProcessRecordDisplayMode(
      writeConversationProcessRecordDisplayMode(mode),
    );
  };
  const handleFaultAnalysisConfidenceVisibilityChange = (visible: boolean) => {
    setShowFaultAnalysisConfidence(
      writeFaultAnalysisConfidenceVisible(visible),
    );
  };

  // --- Alarm diagnosis settings (backend-persisted, DB > env > default) ---
  const [diagnosisPayload, setDiagnosisPayload] =
    useState<DiagnosisSettingsPayload | null>(null);
  const [diagnosisDraft, setDiagnosisDraft] = useState<Record<string, string>>(
    {},
  );
  const [diagnosisLoading, setDiagnosisLoading] = useState(true);
  const [diagnosisSaving, setDiagnosisSaving] = useState(false);
  const [diagnosisTogglePending, setDiagnosisTogglePending] = useState(false);
  const [diagnosisNotice, setDiagnosisNotice] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const buildDiagnosisDraft = (payload: DiagnosisSettingsPayload) => {
    const draft: Record<string, string> = {};
    DIAGNOSIS_NUMBER_FIELDS.forEach((field) => {
      const value = payload.effective[field.key];
      draft[field.key] =
        value === undefined || value === null || isMaskedSecret(value)
          ? ""
          : String(value);
    });
    return draft;
  };

  const applyDiagnosisPayload = (payload: DiagnosisSettingsPayload) => {
    setDiagnosisPayload(payload);
    setDiagnosisDraft(buildDiagnosisDraft(payload));
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setDiagnosisLoading(true);
      try {
        const payload = await diagnosisSettingsApi.get();
        if (!cancelled) {
          applyDiagnosisPayload(payload);
          setDiagnosisNotice(null);
        }
      } catch (error) {
        if (!cancelled) {
          setDiagnosisNotice({
            type: "error",
            text: error instanceof Error ? error.message : "告警设置加载失败",
          });
        }
      } finally {
        if (!cancelled) {
          setDiagnosisLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const diagnosisEnabled = Boolean(
    diagnosisPayload?.effective.auto_takeover_enabled,
  );
  const recoveryVerificationEnabled = Boolean(
    diagnosisPayload?.effective.recovery_verification_enabled,
  );
  // When real-time analysis was last switched on, formatted local time.
  const diagnosisAnchorLabel = useMemo(() => {
    const raw = diagnosisPayload?.state?.analysis_started_at || "";
    if (!raw) {
      return "";
    }
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) {
      return "";
    }
    return parsed.toLocaleString("zh-CN", { hour12: false });
  }, [diagnosisPayload]);

  const handleDiagnosisToggle = async (enabled: boolean) => {
    if (diagnosisTogglePending || enabled === diagnosisEnabled) {
      return;
    }
    setDiagnosisTogglePending(true);
    setDiagnosisNotice(null);
    try {
      const payload = await diagnosisSettingsApi.update({
        auto_takeover_enabled: enabled,
      });
      applyDiagnosisPayload(payload);
      setDiagnosisNotice({
        type: "success",
        text: enabled ? "已开启实时告警分析" : "已暂停实时告警分析",
      });
    } catch (error) {
      setDiagnosisNotice({
        type: "error",
        text: error instanceof Error ? error.message : "切换失败",
      });
    } finally {
      setDiagnosisTogglePending(false);
    }
  };

  const handleRecoveryVerificationToggle = async (enabled: boolean) => {
    if (diagnosisTogglePending || enabled === recoveryVerificationEnabled) {
      return;
    }
    setDiagnosisTogglePending(true);
    setDiagnosisNotice(null);
    try {
      const payload = await diagnosisSettingsApi.update({
        recovery_verification_enabled: enabled,
      });
      applyDiagnosisPayload(payload);
      setDiagnosisNotice({
        type: "success",
        text: enabled ? "已开启告警恢复验证" : "已暂停告警恢复验证",
      });
    } catch (error) {
      setDiagnosisNotice({
        type: "error",
        text: error instanceof Error ? error.message : "切换失败",
      });
    } finally {
      setDiagnosisTogglePending(false);
    }
  };

  const disposalDetailMode = Boolean(
    diagnosisPayload?.effective.alarm_analyst_disposal_detail_mode,
  );

  const handleDisposalDetailModeToggle = async (enabled: boolean) => {
    if (diagnosisTogglePending || enabled === disposalDetailMode) {
      return;
    }
    setDiagnosisTogglePending(true);
    setDiagnosisNotice(null);
    try {
      const payload = await diagnosisSettingsApi.update({
        alarm_analyst_disposal_detail_mode: enabled,
      });
      applyDiagnosisPayload(payload);
      setDiagnosisNotice({
        type: "success",
        text: enabled ? "已开启处置建议详细展示" : "已关闭处置建议详细展示",
      });
    } catch (error) {
      setDiagnosisNotice({
        type: "error",
        text: error instanceof Error ? error.message : "切换失败",
      });
    } finally {
      setDiagnosisTogglePending(false);
    }
  };

  const handleDiagnosisFieldChange = (key: string, value: string) => {
    setDiagnosisDraft((current) => ({ ...current, [key]: value }));
  };

  // Mirrors the diff logic in handleSaveDiagnosisSettings: the save
  // button stays disabled until something actually changed. Invalid
  // (non-numeric) input counts as dirty so clicking surfaces the error.
  const diagnosisDirty = useMemo(() => {
    if (!diagnosisPayload) {
      return false;
    }
    for (const field of DIAGNOSIS_NUMBER_FIELDS) {
      const raw = (diagnosisDraft[field.key] ?? "").trim();
      if (raw === "") {
        continue;
      }
      const num = Number(raw);
      if (Number.isNaN(num)) {
        return true;
      }
      if (String(diagnosisPayload.effective[field.key]) !== String(num)) {
        return true;
      }
    }
    return false;
  }, [diagnosisPayload, diagnosisDraft]);

  const handleSaveDiagnosisSettings = async () => {
    if (!diagnosisPayload || diagnosisSaving) {
      return;
    }
    const body: Record<string, number | string> = {};
    for (const field of DIAGNOSIS_NUMBER_FIELDS) {
      const raw = (diagnosisDraft[field.key] ?? "").trim();
      if (raw === "") {
        continue;
      }
      const num = Number(raw);
      if (Number.isNaN(num)) {
        setDiagnosisNotice({
          type: "error",
          text: `${field.label} 必须是数字`,
        });
        return;
      }
      const effective = diagnosisPayload.effective[field.key];
      if (String(effective) !== String(num)) {
        body[field.key] = num;
      }
    }
    if (Object.keys(body).length === 0) {
      setDiagnosisNotice({ type: "success", text: "没有需要保存的改动" });
      return;
    }
    setDiagnosisSaving(true);
    setDiagnosisNotice(null);
    try {
      const payload = await diagnosisSettingsApi.update(body);
      applyDiagnosisPayload(payload);
      setDiagnosisNotice({ type: "success", text: "告警设置已保存" });
    } catch (error) {
      setDiagnosisNotice({
        type: "error",
        text: error instanceof Error ? error.message : "保存失败",
      });
    } finally {
      setDiagnosisSaving(false);
    }
  };

  const handleResetDiagnosisField = async (key: string) => {
    if (diagnosisSaving) {
      return;
    }
    setDiagnosisNotice(null);
    try {
      const payload = await diagnosisSettingsApi.reset(key);
      applyDiagnosisPayload(payload);
      setDiagnosisNotice({ type: "success", text: "已恢复为环境默认值" });
    } catch (error) {
      setDiagnosisNotice({
        type: "error",
        text: error instanceof Error ? error.message : "恢复默认失败",
      });
    }
  };

  // --- INOE gateway settings (standalone, backend-persisted) ---
  const [inoePayload, setInoePayload] =
    useState<DiagnosisSettingsPayload | null>(null);
  const [inoeDraft, setInoeDraft] = useState<Record<string, string>>({});
  const [inoeTokenDraft, setInoeTokenDraft] = useState("");
  const [inoeFallbackDraft, setInoeFallbackDraft] = useState(true);
  const [inoeLoading, setInoeLoading] = useState(true);
  const [inoeSaving, setInoeSaving] = useState(false);
  const [inoeNotice, setInoeNotice] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const buildInoeDraft = (payload: DiagnosisSettingsPayload) => {
    const draft: Record<string, string> = {};
    [INOE_TEXT_FIELD.key, INOE_NUMBER_FIELD.key].forEach((key) => {
      const value = payload.effective[key];
      draft[key] =
        value === undefined || value === null || isMaskedSecret(value)
          ? ""
          : String(value);
    });
    return draft;
  };

  const applyInoePayload = (payload: DiagnosisSettingsPayload) => {
    setInoePayload(payload);
    setInoeDraft(buildInoeDraft(payload));
    setInoeTokenDraft("");
    setInoeFallbackDraft(
      Boolean(payload.effective[INOE_BOOL_FIELD.key] ?? true),
    );
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setInoeLoading(true);
      try {
        const payload = await inoeSettingsApi.get();
        if (!cancelled) {
          applyInoePayload(payload);
          setInoeNotice(null);
        }
      } catch (error) {
        if (!cancelled) {
          setInoeNotice({
            type: "error",
            text: error instanceof Error ? error.message : "平台设置加载失败",
          });
        }
      } finally {
        if (!cancelled) {
          setInoeLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleInoeFieldChange = (key: string, value: string) => {
    setInoeDraft((current) => ({ ...current, [key]: value }));
  };

  const inoeDirty = useMemo(() => {
    if (!inoePayload) {
      return false;
    }
    if (inoeTokenDraft.trim() !== "") {
      return true;
    }
    if (
      inoeFallbackDraft !==
      Boolean(inoePayload.effective[INOE_BOOL_FIELD.key] ?? true)
    ) {
      return true;
    }
    const rawNum = (inoeDraft[INOE_NUMBER_FIELD.key] ?? "").trim();
    if (rawNum !== "") {
      const num = Number(rawNum);
      if (Number.isNaN(num)) {
        return true;
      }
      if (
        String(inoePayload.effective[INOE_NUMBER_FIELD.key]) !== String(num)
      ) {
        return true;
      }
    }
    const rawText = (inoeDraft[INOE_TEXT_FIELD.key] ?? "").trim();
    if (rawText !== String(inoePayload.effective[INOE_TEXT_FIELD.key] ?? "")) {
      return true;
    }
    return false;
  }, [inoePayload, inoeDraft, inoeTokenDraft, inoeFallbackDraft]);

  const handleSaveInoeSettings = async () => {
    if (!inoePayload || inoeSaving) {
      return;
    }
    const body: Record<string, number | string | boolean> = {};
    const rawNum = (inoeDraft[INOE_NUMBER_FIELD.key] ?? "").trim();
    if (rawNum !== "") {
      const num = Number(rawNum);
      if (Number.isNaN(num)) {
        setInoeNotice({
          type: "error",
          text: `${INOE_NUMBER_FIELD.label} 必须是数字`,
        });
        return;
      }
      if (
        String(inoePayload.effective[INOE_NUMBER_FIELD.key]) !== String(num)
      ) {
        body[INOE_NUMBER_FIELD.key] = num;
      }
    }
    const rawText = (inoeDraft[INOE_TEXT_FIELD.key] ?? "").trim();
    if (rawText !== String(inoePayload.effective[INOE_TEXT_FIELD.key] ?? "")) {
      body[INOE_TEXT_FIELD.key] = rawText;
    }
    if (inoeTokenDraft.trim() !== "") {
      body[INOE_TOKEN_KEY] = inoeTokenDraft.trim();
    }
    if (
      inoeFallbackDraft !==
      Boolean(inoePayload.effective[INOE_BOOL_FIELD.key] ?? true)
    ) {
      body[INOE_BOOL_FIELD.key] = inoeFallbackDraft;
    }
    if (Object.keys(body).length === 0) {
      setInoeNotice({ type: "success", text: "没有需要保存的改动" });
      return;
    }
    setInoeSaving(true);
    setInoeNotice(null);
    try {
      const payload = await inoeSettingsApi.update(body);
      applyInoePayload(payload);
      setInoeNotice({ type: "success", text: "平台设置已保存" });
    } catch (error) {
      setInoeNotice({
        type: "error",
        text: error instanceof Error ? error.message : "保存失败",
      });
    } finally {
      setInoeSaving(false);
    }
  };

  const handleResetInoeField = async (key: string) => {
    if (inoeSaving) {
      return;
    }
    setInoeNotice(null);
    try {
      const payload =
        key === INOE_TOKEN_KEY
          ? await inoeSettingsApi.update({
              [INOE_TOKEN_KEY]: DIAGNOSIS_TOKEN_CLEAR,
            })
          : await inoeSettingsApi.reset(key);
      applyInoePayload(payload);
      setInoeNotice({ type: "success", text: "已恢复为环境默认值" });
    } catch (error) {
      setInoeNotice({
        type: "error",
        text: error instanceof Error ? error.message : "恢复默认失败",
      });
    }
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
    const scope =
      newNotificationTarget === CUSTOM_NOTIFICATION_TARGET_ID
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
    if (
      BUILTIN_NOTIFICATION_SCOPE_IDS.includes(
        scope as (typeof BUILTIN_NOTIFICATION_SCOPE_IDS)[number],
      )
    ) {
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
              <div
                className="settings-tab-list"
                role="tablist"
                aria-label="设置分类"
              >
                {SETTINGS_TABS.map((tab) => {
                  const active = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      className={
                        active ? "settings-tab active" : "settings-tab"
                      }
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
                        className={
                          processRecordDisplayMode === "expanded"
                            ? "portal-managed-config-toggle active"
                            : "portal-managed-config-toggle"
                        }
                        onClick={() =>
                          handleProcessRecordModeChange("expanded")
                        }
                      >
                        <i className="fas fa-angles-down" />
                        默认展开
                      </button>
                      <button
                        type="button"
                        className={
                          processRecordDisplayMode === "collapsed"
                            ? "portal-managed-config-toggle active"
                            : "portal-managed-config-toggle"
                        }
                        onClick={() =>
                          handleProcessRecordModeChange("collapsed")
                        }
                      >
                        <i className="fas fa-angles-right" />
                        默认折叠
                      </button>
                    </div>

                    <div className="portal-managed-config-hint settings-inline-hint">
                      当前默认：
                      {processRecordDisplayMode === "expanded"
                        ? "展开过程记录"
                        : "折叠过程记录"}
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
                          控制故障根因分析 skill
                          的卡片里是否展示置信度，包括右上角徽标和“定位置信度”等字段，避免影响用户判断。
                        </p>
                      </div>
                    </div>

                    <div className="settings-choice-grid">
                      <button
                        type="button"
                        className={
                          showFaultAnalysisConfidence
                            ? "portal-managed-config-toggle active"
                            : "portal-managed-config-toggle"
                        }
                        onClick={() =>
                          handleFaultAnalysisConfidenceVisibilityChange(true)
                        }
                      >
                        <i className="fas fa-eye" />
                        展示置信度
                      </button>
                      <button
                        type="button"
                        className={
                          !showFaultAnalysisConfidence
                            ? "portal-managed-config-toggle active"
                            : "portal-managed-config-toggle"
                        }
                        onClick={() =>
                          handleFaultAnalysisConfidenceVisibilityChange(false)
                        }
                      >
                        <i className="fas fa-eye-slash" />
                        隐藏置信度
                      </button>
                    </div>

                    <div className="portal-managed-config-hint settings-inline-hint">
                      当前默认：
                      {showFaultAnalysisConfidence
                        ? "展示根因分析置信度"
                        : "隐藏根因分析置信度"}
                    </div>
                  </section>

                  {diagnosisNotice ? (
                    <div className={`settings-notice ${diagnosisNotice.type}`}>
                      {diagnosisNotice.text}
                    </div>
                  ) : null}

                  <section className="settings-section">
                    <div className="portal-model-block-head">
                      <div>
                        <h4>实时告警分析</h4>
                        <p>
                          关闭后将暂停对实时告警的自动轮询与分析，不再消耗大模型
                          token；本地开发或告警量大时可临时关闭。设置即时生效，无需重启。
                          未在此设置的项会回退到 `.env` / 部署环境变量。
                        </p>
                      </div>
                    </div>

                    <div className="settings-choice-grid">
                      <button
                        type="button"
                        className={
                          diagnosisEnabled
                            ? "portal-managed-config-toggle active"
                            : "portal-managed-config-toggle"
                        }
                        disabled={diagnosisLoading || diagnosisTogglePending}
                        onClick={() => handleDiagnosisToggle(true)}
                      >
                        <i className="fas fa-play" />
                        开启实时分析
                      </button>
                      <button
                        type="button"
                        className={
                          !diagnosisEnabled
                            ? "portal-managed-config-toggle active"
                            : "portal-managed-config-toggle"
                        }
                        disabled={diagnosisLoading || diagnosisTogglePending}
                        onClick={() => handleDiagnosisToggle(false)}
                      >
                        <i className="fas fa-pause" />
                        暂停实时分析
                      </button>
                    </div>

                    <div className="portal-managed-config-hint settings-inline-hint">
                      {diagnosisLoading
                        ? "正在加载告警设置…"
                        : `当前：${
                            diagnosisEnabled
                              ? "实时分析进行中"
                              : "实时分析已暂停"
                          }` +
                          `（${
                            diagnosisPayload?.overrides.auto_takeover_enabled
                              ? "页面已设置"
                              : "来自环境变量默认"
                          }）` +
                          (diagnosisEnabled && diagnosisAnchorLabel
                            ? `，实时分析自 ${diagnosisAnchorLabel} 起`
                            : "")}
                    </div>
                  </section>

                  {DIAGNOSIS_GROUP_META.map((group) => {
                    const numberFields = DIAGNOSIS_NUMBER_FIELDS.filter(
                      (field) => field.group === group.id,
                    );
                    return (
                      <section key={group.id} className="settings-section">
                        <div className="portal-model-block-head">
                          <div>
                            <h4>{group.title}</h4>
                            <p>{group.description}</p>
                          </div>
                        </div>

                        {group.id === "recovery" ? (
                          <div className="settings-choice-grid">
                            <button
                              type="button"
                              className={
                                recoveryVerificationEnabled
                                  ? "portal-managed-config-toggle active"
                                  : "portal-managed-config-toggle"
                              }
                              disabled={
                                diagnosisLoading || diagnosisTogglePending
                              }
                              onClick={() =>
                                handleRecoveryVerificationToggle(true)
                              }
                            >
                              <i className="fas fa-shield-halved" />
                              开启恢复验证
                            </button>
                            <button
                              type="button"
                              className={
                                !recoveryVerificationEnabled
                                  ? "portal-managed-config-toggle active"
                                  : "portal-managed-config-toggle"
                              }
                              disabled={
                                diagnosisLoading || diagnosisTogglePending
                              }
                              onClick={() =>
                                handleRecoveryVerificationToggle(false)
                              }
                            >
                              <i className="fas fa-pause" />
                              暂停恢复验证
                            </button>
                          </div>
                        ) : null}

                        {group.id === "alarm_analyst" ? (
                          <div className="settings-choice-grid">
                            <button
                              type="button"
                              className={
                                disposalDetailMode
                                  ? "portal-managed-config-toggle active"
                                  : "portal-managed-config-toggle"
                              }
                              disabled={
                                diagnosisLoading || diagnosisTogglePending
                              }
                              onClick={() =>
                                handleDisposalDetailModeToggle(true)
                              }
                            >
                              <i className="fas fa-list-tree" />
                              开启详细展示
                            </button>
                            <button
                              type="button"
                              className={
                                !disposalDetailMode
                                  ? "portal-managed-config-toggle active"
                                  : "portal-managed-config-toggle"
                              }
                              disabled={
                                diagnosisLoading || diagnosisTogglePending
                              }
                              onClick={() =>
                                handleDisposalDetailModeToggle(false)
                              }
                            >
                              <i className="fas fa-list" />
                              关闭详细展示
                            </button>
                          </div>
                        ) : null}

                        <div className="settings-form-grid">
                          {numberFields.map((field) => {
                            const isOverridden = Boolean(
                              diagnosisPayload?.overrides[field.key],
                            );
                            const envValue = diagnosisPayload?.env[field.key];
                            return (
                              <div
                                key={field.key}
                                className="portal-form-group settings-field"
                              >
                                <label htmlFor={`diag-${field.key}`}>
                                  {field.label}
                                </label>
                                <input
                                  id={`diag-${field.key}`}
                                  type="number"
                                  min={field.min}
                                  max={field.max}
                                  step={field.step}
                                  value={diagnosisDraft[field.key] ?? ""}
                                  disabled={diagnosisLoading || diagnosisSaving}
                                  onChange={(event) =>
                                    handleDiagnosisFieldChange(
                                      field.key,
                                      event.target.value,
                                    )
                                  }
                                />
                                <small>
                                  {field.hint}
                                  {!isMaskedSecret(envValue)
                                    ? `　环境默认：${String(envValue ?? "")}`
                                    : ""}
                                  {isOverridden ? (
                                    <>
                                      {"　"}
                                      <button
                                        type="button"
                                        className="settings-link-btn"
                                        disabled={diagnosisSaving}
                                        onClick={() =>
                                          handleResetDiagnosisField(field.key)
                                        }
                                      >
                                        恢复默认
                                      </button>
                                    </>
                                  ) : null}
                                </small>
                              </div>
                            );
                          })}
                        </div>
                      </section>
                    );
                  })}

                  <div className="portal-model-form-actions compact-row">
                    <button
                      type="button"
                      className="portal-model-btn compact"
                      disabled={
                        diagnosisLoading || diagnosisSaving || !diagnosisDirty
                      }
                      onClick={handleSaveDiagnosisSettings}
                    >
                      <i className="fas fa-floppy-disk" />
                      {diagnosisSaving ? "保存中…" : "保存"}
                    </button>
                  </div>
                </div>
              ) : null}

              {activeTab === "inoe" ? (
                <>
                  <div className="portal-model-shell">
                    <section className="settings-section">
                      <div className="portal-model-block-head">
                        <div>
                          <h4>平台连接（INOE）</h4>
                          <p>
                            平台网关地址、访问令牌与请求超时。监控总览、实时告警、工单桥接等都通过这里的网关访问
                            INOE；修改即时生效，无需重启。未在此设置的项会回退到
                            `.env` / 部署环境变量。
                          </p>
                        </div>
                      </div>

                      {inoeNotice ? (
                        <div className={`settings-notice ${inoeNotice.type}`}>
                          {inoeNotice.text}
                        </div>
                      ) : null}

                      <div className="settings-form-grid">
                        <div className="portal-form-group settings-field">
                          <label htmlFor="inoe-base-url">
                            {INOE_TEXT_FIELD.label}
                          </label>
                          <input
                            id="inoe-base-url"
                            type="text"
                            value={inoeDraft[INOE_TEXT_FIELD.key] ?? ""}
                            disabled={inoeLoading || inoeSaving}
                            placeholder={INOE_TEXT_FIELD.placeholder}
                            onChange={(event) =>
                              handleInoeFieldChange(
                                INOE_TEXT_FIELD.key,
                                event.target.value,
                              )
                            }
                          />
                          <small>
                            {INOE_TEXT_FIELD.hint}
                            {!isMaskedSecret(
                              inoePayload?.env[INOE_TEXT_FIELD.key],
                            )
                              ? `　环境默认：${String(
                                  inoePayload?.env[INOE_TEXT_FIELD.key] ?? "",
                                )}`
                              : ""}
                            {inoePayload?.overrides[INOE_TEXT_FIELD.key] ? (
                              <>
                                {"　"}
                                <button
                                  type="button"
                                  className="settings-link-btn"
                                  disabled={inoeSaving}
                                  onClick={() =>
                                    handleResetInoeField(INOE_TEXT_FIELD.key)
                                  }
                                >
                                  恢复默认
                                </button>
                              </>
                            ) : null}
                          </small>
                        </div>

                        <div className="portal-form-group settings-field">
                          <label htmlFor="inoe-token">INOE 访问令牌</label>
                          <input
                            id="inoe-token"
                            type="password"
                            autoComplete="new-password"
                            value={inoeTokenDraft}
                            disabled={inoeLoading || inoeSaving}
                            placeholder={
                              isMaskedSecret(
                                inoePayload?.effective[INOE_TOKEN_KEY],
                              ) &&
                              (
                                inoePayload?.effective[
                                  INOE_TOKEN_KEY
                                ] as MaskedSecret
                              ).is_set
                                ? `已设置（${
                                    (
                                      inoePayload?.effective[
                                        INOE_TOKEN_KEY
                                      ] as MaskedSecret
                                    ).masked
                                  }），留空则不修改`
                                : "未设置，留空则不修改"
                            }
                            onChange={(event) =>
                              setInoeTokenDraft(event.target.value)
                            }
                          />
                          <small>
                            Bearer 令牌；出于安全不会回显原文。
                            {inoePayload?.overrides[INOE_TOKEN_KEY] ? (
                              <>
                                {"　"}
                                <button
                                  type="button"
                                  className="settings-link-btn"
                                  disabled={inoeSaving}
                                  onClick={() =>
                                    handleResetInoeField(INOE_TOKEN_KEY)
                                  }
                                >
                                  清除并恢复默认
                                </button>
                              </>
                            ) : null}
                          </small>
                        </div>

                        <div className="portal-form-group settings-field">
                          <label htmlFor="inoe-timeout">
                            {INOE_NUMBER_FIELD.label}
                          </label>
                          <input
                            id="inoe-timeout"
                            type="number"
                            min={INOE_NUMBER_FIELD.min}
                            step={INOE_NUMBER_FIELD.step}
                            value={inoeDraft[INOE_NUMBER_FIELD.key] ?? ""}
                            disabled={inoeLoading || inoeSaving}
                            onChange={(event) =>
                              handleInoeFieldChange(
                                INOE_NUMBER_FIELD.key,
                                event.target.value,
                              )
                            }
                          />
                          <small>
                            {INOE_NUMBER_FIELD.hint}
                            {!isMaskedSecret(
                              inoePayload?.env[INOE_NUMBER_FIELD.key],
                            )
                              ? `　环境默认：${String(
                                  inoePayload?.env[INOE_NUMBER_FIELD.key] ?? "",
                                )}`
                              : ""}
                            {inoePayload?.overrides[INOE_NUMBER_FIELD.key] ? (
                              <>
                                {"　"}
                                <button
                                  type="button"
                                  className="settings-link-btn"
                                  disabled={inoeSaving}
                                  onClick={() =>
                                    handleResetInoeField(INOE_NUMBER_FIELD.key)
                                  }
                                >
                                  恢复默认
                                </button>
                              </>
                            ) : null}
                          </small>
                        </div>

                        <div className="portal-form-group settings-field">
                          <label htmlFor="inoe-curl-fallback">
                            {INOE_BOOL_FIELD.label}
                          </label>
                          <label
                            className="settings-checkbox-row"
                            htmlFor="inoe-curl-fallback"
                          >
                            <input
                              id="inoe-curl-fallback"
                              type="checkbox"
                              checked={inoeFallbackDraft}
                              disabled={inoeLoading || inoeSaving}
                              onChange={(event) =>
                                setInoeFallbackDraft(event.target.checked)
                              }
                            />
                            <span>
                              {inoeFallbackDraft ? "已启用" : "已关闭"}
                            </span>
                          </label>
                          <small>
                            {INOE_BOOL_FIELD.hint}
                            {`　环境默认：${
                              inoePayload?.env[INOE_BOOL_FIELD.key] ?? true
                                ? "开"
                                : "关"
                            }`}
                            {inoePayload?.overrides[INOE_BOOL_FIELD.key] ? (
                              <>
                                {"　"}
                                <button
                                  type="button"
                                  className="settings-link-btn"
                                  disabled={inoeSaving}
                                  onClick={() =>
                                    handleResetInoeField(INOE_BOOL_FIELD.key)
                                  }
                                >
                                  恢复默认
                                </button>
                              </>
                            ) : null}
                          </small>
                        </div>
                      </div>

                      <div className="portal-model-form-actions compact-row">
                        <button
                          type="button"
                          className="portal-model-btn compact"
                          disabled={inoeLoading || inoeSaving || !inoeDirty}
                          onClick={handleSaveInoeSettings}
                        >
                          <i className="fas fa-floppy-disk" />
                          {inoeSaving ? "保存中…" : "保存"}
                        </button>
                      </div>
                    </section>
                  </div>
                  <ProviderSettingsSection
                    api={inoeSettingsApi}
                    title="菜单 / 页面导航接口"
                    description="page-navigator 解析门户路由用的 getRouters 接口。地址 / 令牌留空则复用上面的平台连接；修改即时生效，无需重启。"
                    fields={INOE_MENU_FIELDS}
                  />
                </>
              ) : null}

              {activeTab === "sso" ? (
                <ProviderSettingsSection
                  api={ssoSettingsApi}
                  title="INOE 单点登录"
                  description="当前用 token 直通：用户从 INOE 点过来时带上已登录的 token（同 host 时浏览器自动带 cookie），portal 后端拿它调网关 /userinfo 验证并取用户信息。网关地址默认复用「平台」tab 的 INOE 网关地址，通常无需在此填写。下面三个 Client 字段是授权码模式（暂未启用）才需要的，可留空。"
                  fields={SSO_FIELDS}
                />
              ) : null}

              {activeTab === "model-adapters" ? (
                <>
                  <ProviderSettingsSection
                    api={qimingSettingsApi}
                    title="启明大模型（Qiming）"
                    description="启明 OpenAI 兼容 adapter 的网关地址、凭证与模型。修改即时生效，无需重启。未在此设置的项会回退到 .env / 部署环境变量。"
                    fields={QIMING_FIELDS}
                  />
                  <ProviderSettingsSection
                    api={xingchenSettingsApi}
                    title="星辰大模型（Xingchen）"
                    description="星辰 OpenAI 兼容 adapter 的网关地址、凭证与模型。修改即时生效，无需重启。未在此设置的项会回退到 .env / 部署环境变量。"
                    fields={XINGCHEN_FIELDS}
                  />
                  <ProviderSettingsSection
                    api={kunlunSettingsApi}
                    title="昆仑网关大模型（云算网智算统一网关）"
                    description="经昆仑能力开放网关调用别组部署的大模型。adapter 用 App Code/Secret 换网关 OAuth2 token（Authorization），并以 X-Authorization 头下发后端大模型自己的 sk 凭据（网关转成后端 Authorization）。修改即时生效，无需重启。"
                    fields={KUNLUN_FIELDS}
                  />
                </>
              ) : null}

              {activeTab === "cmdb" ? (
                <>
                  <ProviderSettingsSection
                    api={zgopsSettingsApi}
                    title="ZGOPS CMDB 连接"
                    description="zgops CMDB 的地址与账号。修改即时生效，供 zgops-cmdb 等技能与资源导入使用。未在此设置的项会回退到部署环境变量。"
                    fields={ZGOPS_FIELDS}
                  />
                  <ResourceImportLlmSection />
                </>
              ) : null}

              {activeTab === "order" ? (
                <ProviderSettingsSection
                  api={orderSettingsApi}
                  title="工单（ferry）连接"
                  description="工单查询 / 建单走的 ferry 工单接口，独立于平台 INOE。地址 / 令牌留空则回退共享 INOE 连接；修改即时生效，无需重启。"
                  fields={ORDER_FIELDS}
                />
              ) : null}

              {activeTab === "n9e" ? (
                <ProviderSettingsSection
                  api={n9eSettingsApi}
                  title="夜莺日志（N9E）连接"
                  description="夜莺日志网关地址、令牌、数据源与索引。供日志隐患检测、安全扫描、日志查询等技能使用，修改即时生效。"
                  fields={N9E_FIELDS}
                />
              ) : null}

              {activeTab === "operator" ? (
                <ProviderSettingsSection
                  api={operatorSettingsApi}
                  title="操作助手菜单连接"
                  description="页面操作助手（operator / page-operator）解析门户路由用的 getRouters 接口，独立于 page-navigator。地址 / 令牌留空则回退共享 INOE 菜单 / 网关连接；修改即时生效，无需重启。"
                  fields={OPERATOR_FIELDS}
                />
              ) : null}

              {activeTab === "notifications" ? (
                <div className="portal-model-shell">
                  <section className="settings-section">
                    <div className="portal-model-block-head">
                      <div>
                        <h4>通知推送配置</h4>
                        <p>
                          将巡检结果与自动建单结果直接推送到应用、钉钉和飞书。相关
                          skill 会优先读取这里的设置，未设置时再回退到原有
                          `.env` 配置。
                        </p>
                      </div>
                    </div>

                    {notificationNotice ? (
                      <div
                        className={`settings-notice ${notificationNotice.type}`}
                      >
                        {notificationNotice.text}
                      </div>
                    ) : null}

                    <section className="portal-advanced-config-panel settings-notification-card">
                      <div className="portal-model-block-head">
                        <div>
                          <h4>
                            <i className="fas fa-plus-circle" />{" "}
                            新增通知作用位置
                          </h4>
                          <p>
                            选择这组 webhook 要作用的业务位置。当前 order 使用
                            `order_workflow`，后续新 skill
                            可用自定义标识接入同一配置文件。
                          </p>
                        </div>
                      </div>

                      <div className="settings-form-grid">
                        <div className="portal-form-group settings-field">
                          <label htmlFor="notification-target-scope">
                            作用位置
                          </label>
                          <select
                            id="notification-target-scope"
                            value={newNotificationTarget}
                            disabled={
                              notificationLoading ||
                              Boolean(savingNotificationScope)
                            }
                            onChange={(event) =>
                              setNewNotificationTarget(event.target.value)
                            }
                          >
                            {NOTIFICATION_TARGET_OPTIONS.map((option) => (
                              <option key={option.id} value={option.id}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          <small>
                            {NOTIFICATION_TARGET_OPTIONS.find(
                              (option) => option.id === newNotificationTarget,
                            )?.description || "选择通知配置生效的业务位置。"}
                          </small>
                        </div>

                        {newNotificationTarget ===
                        CUSTOM_NOTIFICATION_TARGET_ID ? (
                          <div className="portal-form-group settings-field">
                            <label htmlFor="notification-custom-scope">
                              自定义标识
                            </label>
                            <input
                              id="notification-custom-scope"
                              type="text"
                              value={newCustomNotificationScope}
                              disabled={
                                notificationLoading ||
                                Boolean(savingNotificationScope)
                              }
                              onChange={(event) =>
                                setNewCustomNotificationScope(
                                  event.target.value,
                                )
                              }
                              placeholder="例如 web_monitor 或 change_workflow"
                            />
                            <small>
                              只能使用字母、数字、下划线、短横线和点号，并且以字母开头。
                            </small>
                          </div>
                        ) : null}
                      </div>

                      <div className="portal-model-form-actions compact-row">
                        <button
                          type="button"
                          className="portal-model-btn compact"
                          disabled={
                            notificationLoading ||
                            Boolean(savingNotificationScope)
                          }
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
                        const form =
                          notificationForms[scopeId] ||
                          EMPTY_NOTIFICATION_SCOPE();
                        const dirty = notificationDirty[scopeId];
                        const saving = savingNotificationScope === scopeId;
                        const disabled =
                          notificationLoading ||
                          Boolean(savingNotificationScope);
                        const isBuiltin =
                          BUILTIN_NOTIFICATION_SCOPE_IDS.includes(
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
                                  <i className={`fas ${scope.iconClass}`} />{" "}
                                  {scope.label}
                                </h4>
                                <p>{scope.description}</p>
                              </div>
                            </div>

                            <div className="settings-form-grid">
                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-push-url`}>
                                  消息中心推送地址
                                </label>
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
                                <small>
                                  消息中心 `/api/push/{"{token}"}`
                                  应用推送接口。
                                </small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-timeout`}>
                                  通知超时（秒）
                                </label>
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
                                <small>
                                  超时时间会同时作用于应用、钉钉、飞书通知请求。
                                </small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-dingtalk-webhook`}>
                                  钉钉 Webhook
                                </label>
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
                                <label htmlFor={`${scopeId}-dingtalk-secret`}>
                                  钉钉加签 Secret
                                </label>
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
                                <small>
                                  开启钉钉机器人加签时填写；未启用可留空。
                                </small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-feishu-webhook`}>
                                  飞书 Webhook
                                </label>
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
                                <small>
                                  用于发送 interactive 卡片通知消息。
                                </small>
                              </div>

                              <div className="portal-form-group settings-field">
                                <label htmlFor={`${scopeId}-feishu-secret`}>
                                  飞书签名 Secret
                                </label>
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
                                <small>
                                  开启飞书签名校验时填写；未启用可留空。
                                </small>
                              </div>
                            </div>

                            <div className="settings-choice-block">
                              <div className="settings-choice-title">
                                是否 @ 所有人
                              </div>
                              <div className="settings-choice-grid">
                                <button
                                  type="button"
                                  className={
                                    form.mention_all
                                      ? "portal-managed-config-toggle active"
                                      : "portal-managed-config-toggle"
                                  }
                                  disabled={disabled}
                                  onClick={() =>
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "mention_all",
                                      true,
                                    )
                                  }
                                >
                                  <i className="fas fa-at" />
                                  开启 @所有人
                                </button>
                                <button
                                  type="button"
                                  className={
                                    !form.mention_all
                                      ? "portal-managed-config-toggle active"
                                      : "portal-managed-config-toggle"
                                  }
                                  disabled={disabled}
                                  onClick={() =>
                                    handleNotificationFieldChange(
                                      scopeId,
                                      "mention_all",
                                      false,
                                    )
                                  }
                                >
                                  <i className="fas fa-user-minus" />不 @所有人
                                </button>
                              </div>
                            </div>

                            <div className="portal-managed-config-hint settings-inline-hint">
                              当前状态：
                              {dirty ? "有未保存修改" : "已与工作空间设置同步"}
                            </div>

                            <div className="portal-model-form-actions compact-row">
                              <button
                                type="button"
                                className="portal-model-btn secondary compact"
                                disabled={disabled || !dirty}
                                onClick={() =>
                                  handleResetNotificationScope(scopeId)
                                }
                              >
                                重置
                              </button>
                              {!isBuiltin ? (
                                <button
                                  type="button"
                                  className="portal-model-btn secondary compact"
                                  disabled={disabled}
                                  onClick={() =>
                                    void handleDeleteNotificationScope(scopeId)
                                  }
                                >
                                  删除
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="portal-model-btn compact"
                                disabled={disabled || !dirty}
                                onClick={() =>
                                  void handleSaveNotificationScope(scopeId)
                                }
                              >
                                <i
                                  className={`fas ${
                                    saving
                                      ? "fa-spinner fa-spin"
                                      : "fa-floppy-disk"
                                  }`}
                                />
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
