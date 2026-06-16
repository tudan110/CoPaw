import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { channelsApi, type ChannelInfo, type ChannelListResponse } from "../../api/channels";
import { portalGatewayAgentId } from "../../config/portalBranding";
import "../channels-panel.css";

// ── Channel icon mapping ──────────────────────────────────────────────────────
const CHANNEL_ICONS: Record<string, string> = {
  console: "💬",
  dingtalk: "🔷",
  feishu: "🐦",
  telegram: "✈️",
  discord: "🎮",
  wechat: "🟢",
  wecom: "🏢",
  qq: "🐧",
  imessage: "💎",
  mqtt: "📡",
  mattermost: "🔲",
  matrix: "🟩",
  voice: "🎙️",
  sip: "📞",
  onebot: "🤖",
  xiaoyi: "🔴",
};

// ── Channel display names ─────────────────────────────────────────────────────
const CHANNEL_LABELS: Record<string, string> = {
  console: "Console",
  dingtalk: "钉钉",
  feishu: "飞书",
  telegram: "Telegram",
  discord: "Discord",
  wechat: "微信",
  wecom: "企业微信",
  qq: "QQ",
  imessage: "iMessage",
  mqtt: "MQTT",
  mattermost: "Mattermost",
  matrix: "Matrix",
  voice: "Voice (Twilio)",
  sip: "SIP",
  onebot: "OneBot",
  xiaoyi: "小艺",
};

// Channels surfaced in the portal UI, in display order. The rest stay fully
// configured on the backend — they are only hidden here for now (not
// removed). To show more, add their keys to this list; the order here is the
// order shown.
const PORTAL_VISIBLE_CHANNELS = ["console", "feishu", "dingtalk"];

// Channels that have streaming_enabled option
const STREAMING_CHANNELS = ["wecom", "telegram", "dingtalk", "feishu"];

// Channels that show access control fields
const ACCESS_CONTROL_CHANNELS = [
  "telegram", "dingtalk", "discord", "feishu", "wecom", "mattermost",
  "matrix", "wechat", "imessage", "onebot", "qq", "mqtt", "xiaoyi",
];

// Base fields excluded from custom channel dynamic rendering
const BASE_FIELDS = ["enabled", "bot_prefix", "filter_tool_messages", "filter_thinking", "isBuiltin", "streaming_enabled"];

// Secret field detection
function isSecretField(field: string): boolean {
  const secrets = ["client_secret", "app_secret", "bot_token", "secret", "sk", "access_token",
    "password", "http_proxy_auth", "twilio_auth_token", "sip_password", "dashscope_api_key",
    "livekit_api_secret", "encrypt_key", "verification_token"];
  return secrets.includes(field) || field.includes("secret") || field.includes("_token") || field.includes("password");
}

function getChannelIcon(key: string): string {
  return CHANNEL_ICONS[key] || "📨";
}
function getChannelLabel(key: string): string {
  return CHANNEL_LABELS[key] || key;
}

// ── Helper components ─────────────────────────────────────────────────────────

function Tooltip({ text }: { text: string }) {
  return (
    <span className="channels-tooltip-wrap">
      <i className="channels-tooltip-icon">ⓘ</i>
      <span className="channels-tooltip-text">{text}</span>
    </span>
  );
}

function ChannelSelect({ value, options, onChange, placeholder }: {
  value: string; options: { value: string; label: string; description?: string }[];
  onChange: (v: string) => void; placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  const selected = options.find((o) => o.value === value) || null;

  return (
    <div className="portal-select" ref={containerRef}>
      <button
        type="button"
        className={`portal-select-trigger${open ? " active" : ""}`}
        onClick={() => setOpen((p) => !p)}
      >
        <span className="portal-select-copy">
          <span className="portal-select-title">{selected?.label || placeholder || "请选择"}</span>
        </span>
        <i className={`fas ${open ? "fa-chevron-up" : "fa-chevron-down"}`} />
      </button>
      {open && (
        <div className="portal-select-menu">
          {options.map((opt) => {
            const active = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                className={`portal-select-option${active ? " active" : ""}`}
                onClick={() => { onChange(opt.value); setOpen(false); }}
              >
                <span className="portal-select-option-copy">
                  <span className="portal-select-title">{opt.label}</span>
                  {opt.description && <span className="portal-select-desc">{opt.description}</span>}
                </span>
                {active && <i className="fas fa-check" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SwitchField({ label, checked, onChange, hint, tooltip }: {
  label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string; tooltip?: string;
}) {
  return (
    <div className="channels-form-field">
      <label>{label}{tooltip && <Tooltip text={tooltip} />}</label>
      <label className="channel-switch">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="channel-switch-slider" />
      </label>
      {hint && <span className="channels-field-hint">{hint}</span>}
    </div>
  );
}

function TextField({ label, value, onChange, placeholder, type = "text", hint, tooltip }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; hint?: string; tooltip?: string;
}) {
  return (
    <div className="channels-form-field">
      <label>{label}{tooltip && <Tooltip text={tooltip} />}</label>
      <input
        className="channels-input"
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || label}
      />
      {hint && <span className="channels-field-hint">{hint}</span>}
    </div>
  );
}

function NumberField({ label, value, onChange, placeholder, min, max, step, tooltip }: {
  label: string; value: number | string; onChange: (v: number) => void;
  placeholder?: string; min?: number; max?: number; step?: number; tooltip?: string;
}) {
  return (
    <div className="channels-form-field">
      <label>{label}{tooltip && <Tooltip text={tooltip} />}</label>
      <input
        className="channels-input"
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        placeholder={placeholder}
        min={min}
        max={max}
        step={step}
      />
    </div>
  );
}

function SelectField({ label, value, onChange, options, hint, tooltip }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string; description?: string }[]; hint?: string; tooltip?: string;
}) {
  return (
    <div className="channels-form-field">
      <label>{label}{tooltip && <Tooltip text={tooltip} />}</label>
      <ChannelSelect value={value} options={options} onChange={onChange} />
      {hint && <span className="channels-field-hint">{hint}</span>}
    </div>
  );
}

function TextareaField({ label, value, onChange, placeholder, rows = 3 }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; rows?: number;
}) {
  return (
    <div className="channels-form-field">
      <label>{label}</label>
      <textarea
        className="channels-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
      />
    </div>
  );
}

// ── Channel-specific form fields ──────────────────────────────────────────────

function FeishuFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <SelectField
        label="地区 (Region)"
        value={String(config.domain || "feishu")}
        onChange={(v) => onChange("domain", v)}
        options={[
          { value: "feishu", label: "飞书（中国大陆）", description: "中国大陆用户" },
          { value: "lark", label: "Lark（国际版）", description: "海外用户" },
        ]}
        tooltip="国内用户选择飞书，海外用户选择 Lark"
      />
      <TextField label="App ID" value={String(config.app_id || "")} onChange={(v) => onChange("app_id", v)} placeholder="cli_xxx" />
      <TextField label="App Secret" value={String(config.app_secret || "")} onChange={(v) => onChange("app_secret", v)} type="password" />
      <TextField label="Encrypt Key" value={String(config.encrypt_key || "")} onChange={(v) => onChange("encrypt_key", v)} placeholder="可选，用于事件加密" />
      <TextField label="Verification Token" value={String(config.verification_token || "")} onChange={(v) => onChange("verification_token", v)} placeholder="可选" />
      <TextField label="媒体文件目录" value={String(config.media_dir || "")} onChange={(v) => onChange("media_dir", v)} placeholder="{workspace_dir}/media" hint="留空则使用当前 Agent 工作目录下的 media 文件夹" />
    </>
  );
}

function DingtalkFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  const needsCard = config.message_type === "card" || config.cron_message_type === "card";
  return (
    <>
      <TextField label="Client ID" value={String(config.client_id || "")} onChange={(v) => onChange("client_id", v)} placeholder="dingxxxxx" />
      <TextField label="Client Secret" value={String(config.client_secret || "")} onChange={(v) => onChange("client_secret", v)} type="password" />
      <SelectField
        label="消息类型 (Message Type)"
        value={String(config.message_type || "markdown")}
        onChange={(v) => onChange("message_type", v)}
        options={[
          { value: "markdown", label: "markdown", description: "普通消息" },
          { value: "card", label: "card", description: "AI 互动卡片" },
        ]}
        tooltip="markdown: 普通消息; card: AI 互动卡片"
      />
      <SelectField
        label="定时任务消息类型"
        value={String(config.cron_message_type || "markdown")}
        onChange={(v) => onChange("cron_message_type", v)}
        options={[
          { value: "markdown", label: "markdown", description: "普通消息" },
          { value: "card", label: "card", description: "AI 互动卡片" },
        ]}
        tooltip="定时/计划任务发送的消息类型，独立于上方聊天消息类型"
      />
      {needsCard && (
        <>
          <TextField label="Card Template ID" value={String(config.card_template_id || "")} onChange={(v) => onChange("card_template_id", v)} placeholder="dt_card_template_xxx" />
          <TextField label="Card Template Key" value={String(config.card_template_key || "")} onChange={(v) => onChange("card_template_key", v)} placeholder="content" hint="必须与模板变量名完全匹配" />
          <TextField label="Robot Code" value={String(config.robot_code || "")} onChange={(v) => onChange("robot_code", v)} placeholder="robot code（默认 client_id）" hint="群聊场景建议显式配置" />
        </>
      )}
      <SwitchField label="回复时 @ 发送者" checked={Boolean(config.at_sender_on_reply)} onChange={(v) => onChange("at_sender_on_reply", v)} />
    </>
  );
}

function TelegramFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Bot Token" value={String(config.bot_token || "")} onChange={(v) => onChange("bot_token", v)} type="password" placeholder="Telegram bot token from BotFather" />
      <TextField label="HTTP Proxy" value={String(config.http_proxy || "")} onChange={(v) => onChange("http_proxy", v)} placeholder="http://127.0.0.1:18118" />
      <TextField label="HTTP Proxy Auth" value={String(config.http_proxy_auth || "")} onChange={(v) => onChange("http_proxy_auth", v)} placeholder="user:password" />
      <SwitchField label="显示正在输入 (Show Typing)" checked={Boolean(config.show_typing)} onChange={(v) => onChange("show_typing", v)} />
    </>
  );
}

function DiscordFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Bot Token" value={String(config.bot_token || "")} onChange={(v) => onChange("bot_token", v)} type="password" placeholder="Discord bot token" />
      <TextField label="HTTP Proxy" value={String(config.http_proxy || "")} onChange={(v) => onChange("http_proxy", v)} placeholder="http://127.0.0.1:18118" />
      <TextField label="HTTP Proxy Auth" value={String(config.http_proxy_auth || "")} onChange={(v) => onChange("http_proxy_auth", v)} placeholder="user:password" />
      <SwitchField label="接受 Bot 消息" checked={Boolean(config.accept_bot_messages)} onChange={(v) => onChange("accept_bot_messages", v)} />
    </>
  );
}

function QqFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="App ID" value={String(config.app_id || "")} onChange={(v) => onChange("app_id", v)} />
      <TextField label="Client Secret" value={String(config.client_secret || "")} onChange={(v) => onChange("client_secret", v)} type="password" />
      <TextField label="即时确认消息" value={String(config.ack_message || "")} onChange={(v) => onChange("ack_message", v)} placeholder="收到消息后立即确认回复，留空禁用" hint="收到消息后立即发送一条确认回复，在 Agent 处理之前。留空则禁用。" />
    </>
  );
}

function WechatFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Bot Token" value={String(config.bot_token || "")} onChange={(v) => onChange("bot_token", v)} type="password" />
      <TextField label="Token 文件路径" value={String(config.bot_token_file || "")} onChange={(v) => onChange("bot_token_file", v)} placeholder="~/.qwenpaw/wechat_bot_token" />
      <TextField label="媒体文件目录" value={String(config.media_dir || "")} onChange={(v) => onChange("media_dir", v)} placeholder="{workspace_dir}/media" />
      <SwitchField label="消息合并" checked={Boolean(config.message_merge_enabled)} onChange={(v) => onChange("message_merge_enabled", v)} hint="开启后将短时间内的连续消息合并处理" />
      {Boolean(config.message_merge_enabled) && (
        <NumberField label="消息合并延迟 (ms)" value={config.message_merge_delay_ms as number || 0} onChange={(v) => onChange("message_merge_delay_ms", v)} min={0} step={100} placeholder="0" />
      )}
    </>
  );
}

function WecomFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Bot ID" value={String(config.bot_id || "")} onChange={(v) => onChange("bot_id", v)} placeholder="Bot ID from WeCom backend" />
      <TextField label="Secret" value={String(config.secret || "")} onChange={(v) => onChange("secret", v)} type="password" placeholder="Secret from WeCom backend" />
      <TextField label="媒体文件目录" value={String(config.media_dir || "")} onChange={(v) => onChange("media_dir", v)} placeholder="{workspace_dir}/media" />
      <TextField label="欢迎语" value={String(config.welcome_text || "")} onChange={(v) => onChange("welcome_text", v)} placeholder="用户首次对话时发送" />
      <SwitchField label="群内共享会话" checked={Boolean(config.share_session_in_group)} onChange={(v) => onChange("share_session_in_group", v)} hint="开启后群内所有用户共享同一会话上下文" />
    </>
  );
}

function ImessageFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="数据库路径 (DB Path)" value={String(config.db_path || "")} onChange={(v) => onChange("db_path", v)} placeholder="~/Library/Messages/chat.db" />
      <NumberField label="轮询间隔（秒）" value={config.poll_sec as number || 1} onChange={(v) => onChange("poll_sec", v)} min={0.1} step={0.1} placeholder="1" />
    </>
  );
}

function MqttFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="MQTT Host" value={String(config.host || "")} onChange={(v) => onChange("host", v)} placeholder="127.0.0.1" />
      <NumberField label="MQTT Port" value={config.port as number || 1883} onChange={(v) => onChange("port", v)} min={1} max={65535} placeholder="1883" />
      <SelectField
        label="传输方式 (Transport)"
        value={String(config.transport || "tcp")}
        onChange={(v) => onChange("transport", v)}
        options={[
          { value: "tcp", label: "MQTT (tcp)" },
          { value: "websockets", label: "WS (websockets)" },
        ]}
      />
      <SwitchField label="Clean Session" checked={config.clean_session !== false} onChange={(v) => onChange("clean_session", v)} />
      <SelectField
        label="QoS"
        value={String(config.qos ?? "2")}
        onChange={(v) => onChange("qos", v)}
        options={[
          { value: "0", label: "At Most Once (0)" },
          { value: "1", label: "At Least Once (1)" },
          { value: "2", label: "Exactly Once (2)" },
        ]}
      />
      <TextField label="MQTT Username" value={String(config.username || "")} onChange={(v) => onChange("username", v)} placeholder="留空则不使用" />
      <TextField label="MQTT Password" value={String(config.password || "")} onChange={(v) => onChange("password", v)} type="password" placeholder="留空则不使用" />
      <TextField label="Subscribe Topic" value={String(config.subscribe_topic || "")} onChange={(v) => onChange("subscribe_topic", v)} placeholder="server/+/up" />
      <TextField label="Publish Topic" value={String(config.publish_topic || "")} onChange={(v) => onChange("publish_topic", v)} placeholder="client/{client_id}/down" />
      <SwitchField label="启用 TLS" checked={Boolean(config.tls_enabled)} onChange={(v) => onChange("tls_enabled", v)} />
      <TextField label="TLS CA Certs" value={String(config.tls_ca_certs || "")} onChange={(v) => onChange("tls_ca_certs", v)} placeholder="CA 证书文件路径" />
      <TextField label="TLS Certfile" value={String(config.tls_certfile || "")} onChange={(v) => onChange("tls_certfile", v)} placeholder="客户端证书文件路径" />
      <TextField label="TLS Keyfile" value={String(config.tls_keyfile || "")} onChange={(v) => onChange("tls_keyfile", v)} placeholder="客户端密钥文件路径" />
    </>
  );
}

function MattermostFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Mattermost URL" value={String(config.url || "")} onChange={(v) => onChange("url", v)} placeholder="https://mattermost.example.com" />
      <TextField label="Bot Token" value={String(config.bot_token || "")} onChange={(v) => onChange("bot_token", v)} type="password" placeholder="Mattermost bot token" />
      <TextField label="媒体文件目录" value={String(config.media_dir || "")} onChange={(v) => onChange("media_dir", v)} placeholder="{workspace_dir}/media" />
      <SwitchField label="显示正在输入 (Show Typing)" checked={Boolean(config.show_typing)} onChange={(v) => onChange("show_typing", v)} />
      <SwitchField label="无需 @ 跟踪会话" checked={Boolean(config.thread_follow_without_mention)} onChange={(v) => onChange("thread_follow_without_mention", v)} />
    </>
  );
}

function MatrixFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  const authMethod = String(config.auth_method || "token");
  const isPassword = authMethod === "password";
  return (
    <>
      <TextField label="Homeserver URL" value={String(config.homeserver || "")} onChange={(v) => onChange("homeserver", v)} placeholder="https://matrix.org" />
      <TextField label="User ID" value={String(config.user_id || "")} onChange={(v) => onChange("user_id", v)} placeholder="@bot:matrix.org" hint="接受完整 MXID（如 @bot:matrix.org）或仅本地部分（如 bot）" />
      <SelectField
        label="认证方式 (Auth Method)"
        value={authMethod}
        onChange={(v) => onChange("auth_method", v)}
        options={[
          { value: "token", label: "Token" },
          { value: "password", label: "Password" },
        ]}
      />
      {!isPassword && (
        <TextField label="Access Token" value={String(config.access_token || "")} onChange={(v) => onChange("access_token", v)} type="password" placeholder="syt_..." />
      )}
      {isPassword && (
        <>
          <TextField label="Password" value={String(config.password || "")} onChange={(v) => onChange("password", v)} type="password" placeholder="账户登录密码" />
          <SwitchField label="端到端加密 (E2EE)" checked={Boolean(config.encryption)} onChange={(v) => onChange("encryption", v)} hint="启用后需要在 Matrix 客户端中验证设备。需安装 matrix-nio[e2e]" />
        </>
      )}
      <TextField label="设备名称" value={String(config.device_name || "")} onChange={(v) => onChange("device_name", v)} placeholder="qwenpaw-worker" />
      <SwitchField label="禁用私聊" checked={Boolean(config.dm_disabled)} onChange={(v) => onChange("dm_disabled", v)} />
      <SwitchField label="禁用群聊" checked={Boolean(config.group_disabled)} onChange={(v) => onChange("group_disabled", v)} />
    </>
  );
}

function VoiceFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Twilio Account SID" value={String(config.twilio_account_sid || "")} onChange={(v) => onChange("twilio_account_sid", v)} placeholder="ACxxxxxxxx" />
      <TextField label="Twilio Auth Token" value={String(config.twilio_auth_token || "")} onChange={(v) => onChange("twilio_auth_token", v)} type="password" />
      <TextField label="电话号码" value={String(config.phone_number || "")} onChange={(v) => onChange("phone_number", v)} placeholder="+15551234567" />
      <TextField label="Phone Number SID" value={String(config.phone_number_sid || "")} onChange={(v) => onChange("phone_number_sid", v)} placeholder="PNxxxxxxxx" />
      <TextField label="TTS 服务商" value={String(config.tts_provider || "")} onChange={(v) => onChange("tts_provider", v)} placeholder="google" />
      <TextField label="TTS 语音" value={String(config.tts_voice || "")} onChange={(v) => onChange("tts_voice", v)} placeholder="en-US-Journey-D" />
      <TextField label="STT 服务商" value={String(config.stt_provider || "")} onChange={(v) => onChange("stt_provider", v)} placeholder="deepgram" />
      <TextField label="语言" value={String(config.language || "")} onChange={(v) => onChange("language", v)} placeholder="en-US" />
      <TextareaField label="欢迎语" value={String(config.welcome_greeting || "")} onChange={(v) => onChange("welcome_greeting", v)} rows={2} />
    </>
  );
}

function SipFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  const sipMode = String(config.sip_mode || "dev");
  return (
    <>
      <SelectField
        label="SIP 模式"
        value={sipMode}
        onChange={(v) => onChange("sip_mode", v)}
        options={[
          { value: "dev", label: "Dev (pyVoIP)" },
          { value: "livekit", label: "Production (LiveKit)" },
        ]}
      />
      <TextField label="SIP 服务器" value={String(config.sip_server || "")} onChange={(v) => onChange("sip_server", v)} placeholder={sipMode === "livekit" ? "LiveKit SIP server" : "SIP server address"} />
      <TextField label="SIP 用户名" value={String(config.sip_username || "")} onChange={(v) => onChange("sip_username", v)} placeholder="1001" />
      <TextField label="SIP 密码" value={String(config.sip_password || "")} onChange={(v) => onChange("sip_password", v)} type="password" />
      <NumberField label="SIP 端口" value={config.sip_port as number || ""} onChange={(v) => onChange("sip_port", v)} min={1} max={65535} placeholder="5061" />
      <SelectField
        label="SIP 传输"
        value={String(config.sip_transport || "UDP")}
        onChange={(v) => onChange("sip_transport", v)}
        options={[
          { value: "UDP", label: "UDP" },
          { value: "TCP", label: "TCP" },
          { value: "TLS", label: "TLS" },
        ]}
      />
      <TextField label="DashScope API Key" value={String(config.dashscope_api_key || "")} onChange={(v) => onChange("dashscope_api_key", v)} type="password" placeholder="sk-..." />
      <TextField label="TTS 服务商" value={String(config.tts_provider || "")} onChange={(v) => onChange("tts_provider", v)} placeholder="aliyun" />
      <TextField label="TTS 语音" value={String(config.tts_voice || "")} onChange={(v) => onChange("tts_voice", v)} placeholder="longxiaochun" />
      <TextField label="STT 服务商" value={String(config.stt_provider || "")} onChange={(v) => onChange("stt_provider", v)} placeholder="aliyun" />
      <TextField label="语言" value={String(config.language || "")} onChange={(v) => onChange("language", v)} placeholder="zh-CN" />
      <TextareaField label="欢迎语" value={String(config.welcome_greeting || "")} onChange={(v) => onChange("welcome_greeting", v)} rows={2} />
      {sipMode === "livekit" && (
        <>
          <TextField label="LiveKit URL" value={String(config.livekit_url || "")} onChange={(v) => onChange("livekit_url", v)} placeholder="ws://localhost:7880" />
          <TextField label="LiveKit API Key" value={String(config.livekit_api_key || "")} onChange={(v) => onChange("livekit_api_key", v)} />
          <TextField label="LiveKit API Secret" value={String(config.livekit_api_secret || "")} onChange={(v) => onChange("livekit_api_secret", v)} type="password" />
          <TextField label="LiveKit SIP Trunk ID" value={String(config.livekit_sip_trunk_id || "")} onChange={(v) => onChange("livekit_sip_trunk_id", v)} placeholder="ST_xxxx" />
          <TextField label="LiveKit Room Name" value={String(config.livekit_room_name || "")} onChange={(v) => onChange("livekit_room_name", v)} placeholder="sip-inbound" />
        </>
      )}
    </>
  );
}

function OnebotFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="WebSocket Host" value={String(config.ws_host || "")} onChange={(v) => onChange("ws_host", v)} placeholder="0.0.0.0" />
      <NumberField label="WebSocket Port" value={config.ws_port as number || 6199} onChange={(v) => onChange("ws_port", v)} min={1} max={65535} placeholder="6199" />
      <TextField label="Access Token" value={String(config.access_token || "")} onChange={(v) => onChange("access_token", v)} type="password" placeholder="Access token for authentication" />
      <SwitchField label="群内共享会话" checked={Boolean(config.share_session_in_group)} onChange={(v) => onChange("share_session_in_group", v)} />
    </>
  );
}

function XiaoyiFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  return (
    <>
      <TextField label="Access Key (AK)" value={String(config.ak || "")} onChange={(v) => onChange("ak", v)} placeholder="Access Key from Huawei Developer Platform" />
      <TextField label="Secret Key (SK)" value={String(config.sk || "")} onChange={(v) => onChange("sk", v)} type="password" placeholder="Secret Key from Huawei Developer Platform" />
      <TextField label="Agent ID" value={String(config.agent_id || "")} onChange={(v) => onChange("agent_id", v)} placeholder="Agent ID from XiaoYi platform" />
      <TextField label="WebSocket URL" value={String(config.ws_url || "")} onChange={(v) => onChange("ws_url", v)} placeholder="wss://hag.cloud.huawei.com/openclaw/v1/ws/link" />
    </>
  );
}

// Custom channel: dynamic rendering
function CustomChannelFields({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  const extraKeys = Object.keys(config).filter((k) => !BASE_FIELDS.includes(k));
  if (extraKeys.length === 0) return null;
  return (
    <>
      <div className="channels-section-title">自定义字段</div>
      {extraKeys.map((field) => {
        const value = config[field];
        if (typeof value === "boolean") {
          return <SwitchField key={field} label={field} checked={value} onChange={(v) => onChange(field, v)} />;
        }
        if (typeof value === "number") {
          return <NumberField key={field} label={field} value={value} onChange={(v) => onChange(field, v)} />;
        }
        return (
          <TextField
            key={field}
            label={field}
            value={String(value ?? "")}
            onChange={(v) => onChange(field, v)}
            type={isSecretField(field) ? "password" : "text"}
          />
        );
      })}
    </>
  );
}

// ── Builtin channel fields router ─────────────────────────────────────────────
function BuiltinChannelFields({ channelKey, config, onChange }: {
  channelKey: string; config: Record<string, unknown>; onChange: (f: string, v: unknown) => void;
}) {
  switch (channelKey) {
    case "feishu": return <FeishuFields config={config} onChange={onChange} />;
    case "dingtalk": return <DingtalkFields config={config} onChange={onChange} />;
    case "telegram": return <TelegramFields config={config} onChange={onChange} />;
    case "discord": return <DiscordFields config={config} onChange={onChange} />;
    case "qq": return <QqFields config={config} onChange={onChange} />;
    case "wechat": return <WechatFields config={config} onChange={onChange} />;
    case "wecom": return <WecomFields config={config} onChange={onChange} />;
    case "imessage": return <ImessageFields config={config} onChange={onChange} />;
    case "mqtt": return <MqttFields config={config} onChange={onChange} />;
    case "mattermost": return <MattermostFields config={config} onChange={onChange} />;
    case "matrix": return <MatrixFields config={config} onChange={onChange} />;
    case "voice": return <VoiceFields config={config} onChange={onChange} />;
    case "sip": return <SipFields config={config} onChange={onChange} />;
    case "onebot": return <OnebotFields config={config} onChange={onChange} />;
    case "xiaoyi": return <XiaoyiFields config={config} onChange={onChange} />;
    default: return null;
  }
}

// ── Main Component ────────────────────────────────────────────────────────────

export function ChannelsPanel() {
  const [channels, setChannels] = useState<ChannelListResponse>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeChannel, setActiveChannel] = useState<string | null>(null);
  const [editConfig, setEditConfig] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [toast, setToast] = useState<{ type: "error"; text: string } | null>(null);
  const [restarting, setRestarting] = useState<string | null>(null);

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await channelsApi.listChannels(portalGatewayAgentId);
      setChannels(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels]);

  // Visibility AND display order both come from PORTAL_VISIBLE_CHANNELS; the
  // remaining channels stay configured on the backend, just hidden here.
  const sortedKeys = useMemo(() => {
    const keys = Object.keys(channels);
    return PORTAL_VISIBLE_CHANNELS.filter((k) => keys.includes(k));
  }, [channels]);

  const openDrawer = (key: string) => {
    setActiveChannel(key);
    const config = channels[key] || { enabled: false, bot_prefix: "" };
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { isBuiltin: _ib, ...editable } = config as Record<string, unknown>;
    // Invert filter fields for UI display (UI shows "显示", storage is "过滤")
    setEditConfig({
      ...editable,
      filter_tool_messages: !editable.filter_tool_messages,
      filter_thinking: !editable.filter_thinking,
    });
    setSaveMsg(null);
  };

  const closeDrawer = () => {
    setActiveChannel(null);
    setEditConfig({});
    setSaveMsg(null);
  };

  const handleFieldChange = (field: string, value: unknown) => {
    setEditConfig((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async () => {
    if (!activeChannel) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      // Invert filter fields back for storage
      const payload = {
        ...editConfig,
        filter_tool_messages: !editConfig.filter_tool_messages,
        filter_thinking: !editConfig.filter_thinking,
      };
      await channelsApi.updateChannel(activeChannel, payload, portalGatewayAgentId);
      setSaveMsg({ type: "success", text: "保存成功" });
      await fetchChannels();
    } catch (err: unknown) {
      setSaveMsg({ type: "error", text: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setSaving(false);
    }
  };

  const handleRestart = async (channelName: string) => {
    setRestarting(channelName);
    try {
      await channelsApi.restartChannel(channelName, portalGatewayAgentId);
      setToast(null);
    } catch (err: unknown) {
      setToast({ type: "error", text: `重启 ${channelName} 失败：${err instanceof Error ? err.message : "未知错误"}` });
    } finally {
      setRestarting(null);
    }
  };

  const handleToggleEnabled = async (channelName: string, currentEnabled: boolean) => {
    try {
      const config = channels[channelName] || {};
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { isBuiltin: _ib, ...rest } = config as Record<string, unknown>;
      await channelsApi.updateChannel(channelName, { ...rest, enabled: !currentEnabled }, portalGatewayAgentId);
      await fetchChannels();
    } catch (err: unknown) {
      setToast({ type: "error", text: `切换失败：${err instanceof Error ? err.message : "未知错误"}` });
    }
  };

  const isBuiltin = activeChannel ? Boolean(channels[activeChannel]?.isBuiltin) : false;

  return (
    <div className="channels-panel">
      <div className="channels-panel-static">
        <div className="channels-panel-header">
          <div className="channels-panel-title">
            频道配置 <small>消息接入管理</small>
          </div>
        </div>

        {toast && (
          <div className={`channels-panel-toast ${toast.type}`}>
            {toast.text}
            <button
              style={{ marginLeft: 8, background: "none", border: "none", cursor: "pointer" }}
              onClick={() => setToast(null)}
            >
              ✕
            </button>
          </div>
        )}
      </div>

      <div className="channels-panel-scroll">
        {loading ? (
          <div className="channels-panel-loading">加载中...</div>
        ) : error ? (
          <div className="channels-panel-error">
            {error}
            <button className="channels-retry-btn" onClick={fetchChannels}>
              重试
            </button>
          </div>
        ) : (
          <div className="channels-grid">
          {sortedKeys.map((key) => {
            const info = channels[key] as ChannelInfo;
            const enabled = Boolean(info?.enabled);
            const builtin = Boolean(info?.isBuiltin);
            return (
              <div
                key={key}
                className={`channel-card${enabled ? " enabled" : ""}`}
                onClick={() => openDrawer(key)}
              >
                <div className="channel-card-icon">{getChannelIcon(key)}</div>
                <div className="channel-card-body">
                  <div className="channel-card-name">
                    {getChannelLabel(key)}
                    {builtin && <span className="channel-badge builtin">内置</span>}
                  </div>
                  <div className="channel-card-status">
                    <span className={`channel-status-dot ${enabled ? "on" : "off"}`} />
                    <span className="channel-status-text">{enabled ? "已启用" : "未启用"}</span>
                  </div>
                </div>
                <div
                  className="channel-card-toggle"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleToggleEnabled(key, enabled);
                  }}
                >
                  <label className="channel-switch">
                    <input type="checkbox" checked={enabled} readOnly />
                    <span className="channel-switch-slider" />
                  </label>
                </div>
              </div>
            );
          })}
        </div>
      )}
      </div>

      {/* ── Drawer ────────────────────────────────────────────────────── */}
      {activeChannel && (
        <div className="channels-drawer-overlay" onClick={closeDrawer}>
          <div className="channels-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="channels-drawer-header">
              <h3>
                {getChannelIcon(activeChannel)} {getChannelLabel(activeChannel)} 设置
              </h3>
              <button className="channels-drawer-close" onClick={closeDrawer}>
                ✕
              </button>
            </div>

            <div className="channels-drawer-form">
              {/* 1. 启用 */}
              <SwitchField
                label="启用"
                checked={Boolean(editConfig.enabled)}
                onChange={(v) => handleFieldChange("enabled", v)}
              />

              {/* 2. Bot Prefix (voice 频道除外) */}
              {activeChannel !== "voice" && (
                <TextField
                  label="Bot Prefix"
                  value={String(editConfig.bot_prefix || "")}
                  onChange={(v) => handleFieldChange("bot_prefix", v)}
                  placeholder="@bot"
                  hint="只有包含此前缀的消息会被处理，留空表示处理所有消息"
                />
              )}

              {/* 3-4. 显示工具消息 / 显示思考过程 (console 频道除外) */}
              {activeChannel !== "console" && (
                <>
                  <SwitchField
                    label="显示工具消息"
                    checked={Boolean(editConfig.filter_tool_messages)}
                    onChange={(v) => handleFieldChange("filter_tool_messages", v)}
                    tooltip="向用户显示工具调用和输出消息（关闭则隐藏）"
                  />
                  <SwitchField
                    label="显示思考过程"
                    checked={Boolean(editConfig.filter_thinking)}
                    onChange={(v) => handleFieldChange("filter_thinking", v)}
                    tooltip="向用户显示模型的思考/推理内容（关闭则隐藏）"
                  />
                </>
              )}

              {/* 5. 流式输出 (仅 wecom/telegram/dingtalk/feishu) */}
              {STREAMING_CHANNELS.includes(activeChannel) && (
                <SwitchField
                  label="流式输出"
                  checked={Boolean(editConfig.streaming_enabled)}
                  onChange={(v) => handleFieldChange("streaming_enabled", v)}
                  tooltip={
                    activeChannel === "dingtalk" ? "仅在消息类型为 Card 时生效" :
                    activeChannel === "feishu" ? "需要在飞书开放平台权限管理界面开通 cardkit:card:write 权限" :
                    "启用后消息将逐步输出而非等待完整回复"
                  }
                />
              )}

              {/* Channel-specific fields */}
              {isBuiltin ? (
                <BuiltinChannelFields channelKey={activeChannel} config={editConfig} onChange={handleFieldChange} />
              ) : (
                <CustomChannelFields config={editConfig} onChange={handleFieldChange} />
              )}

              {/* Access control fields */}
              {ACCESS_CONTROL_CHANNELS.includes(activeChannel) && (
                <>
                  <div className="channels-section-title">访问控制</div>
                  <SwitchField
                    label="私聊访问控制"
                    checked={Boolean(editConfig.access_control_dm)}
                    onChange={(v) => handleFieldChange("access_control_dm", v)}
                    hint="开启后，只有白名单用户可以通过私聊与机器人互动"
                  />
                  <SwitchField
                    label="群聊访问控制"
                    checked={Boolean(editConfig.access_control_group)}
                    onChange={(v) => handleFieldChange("access_control_group", v)}
                    hint="开启后，只有白名单用户可以在群聊中与机器人互动"
                  />
                  <SwitchField
                    label="需要 @提及"
                    checked={Boolean(editConfig.require_mention)}
                    onChange={(v) => handleFieldChange("require_mention", v)}
                    hint="开启后，群聊中仅在被 @提及 时才会回复"
                  />
                </>
              )}

              {/* Save message */}
              {saveMsg && (
                <div className={`channels-save-message ${saveMsg.type}`}>{saveMsg.text}</div>
              )}

              {/* Actions */}
              <div className="channels-drawer-actions">
                <button
                  className="channels-btn secondary"
                  onClick={() => handleRestart(activeChannel)}
                  disabled={restarting === activeChannel}
                >
                  {restarting === activeChannel ? "重启中..." : "重启频道"}
                </button>
                <button className="channels-btn secondary" onClick={closeDrawer}>
                  取消
                </button>
                <button className="channels-btn primary" onClick={handleSave} disabled={saving}>
                  {saving ? "保存中..." : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ChannelsPanel;
