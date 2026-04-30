import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAlarmAnalystCardRequest,
  getAlarmAnalystReportMarkdown,
  mergeAlarmAnalystCards,
  shouldAttemptAlarmAnalystCardByContent,
  shouldEnableAlarmAnalystCards,
} from "./shared.ts";

test("builds alarm analyst card request from grouped response blocks", () => {
  const message = {
    id: "agent-1",
    enhancementSourceMessageId: "assistant-1",
    processBlocks: [
      { kind: "tool", toolName: "read_file", outputContent: "{\"series\":[]}" },
      { kind: "response", content: "## 根因分析结论\n- MySQL 锁等待放大" },
    ],
  };

  const payload = buildAlarmAnalystCardRequest({
    chatId: "chat-1",
    sessionId: "session-1",
    employeeId: "fault",
    message,
  });

  assert.ok(payload);
  assert.equal(payload?.messageId, "assistant-1");
  assert.equal(payload?.reportMarkdown, "## 根因分析结论\n- MySQL 锁等待放大");
  assert.equal(payload?.processBlocks[0].toolName, "read_file");
});

test("merges stored cards back into grouped messages by source message id", () => {
  const messages = [
    {
      id: "agent-1",
      enhancementSourceMessageId: "assistant-1",
      processBlocks: [{ kind: "response", content: "报告正文" }],
    },
  ];
  const cards = [
    {
      type: "alarm-analyst-card",
      version: "v1",
      source: {
        chatId: "chat-1",
        messageId: "assistant-1",
        skillName: "alarm-analyst",
        contentHash: "abc123",
      },
      summary: {
        title: "数据库锁异常",
        conclusion: "MySQL 锁等待放大",
      },
      rootCause: { reason: "MySQL 锁等待放大" },
      impact: { affectedApplications: [], affectedResources: [] },
      topology: { nodes: [], edges: [] },
      recommendations: [],
      evidence: [],
      rawReportMarkdown: "报告正文",
    },
  ] as any;

  const merged = mergeAlarmAnalystCards(messages, cards);

  assert.equal(getAlarmAnalystReportMarkdown(merged[0]), "报告正文");
  assert.equal(merged[0].alarmAnalystCard.summary.title, "数据库锁异常");
});

test("merges stored cards by raw report markdown when message id differs", () => {
  const messages = [
    {
      id: "agent-2",
      enhancementSourceMessageId: "history-assistant-1",
      processBlocks: [{ kind: "response", content: "报告正文-历史回放" }],
    },
  ];
  const cards = [
    {
      type: "alarm-analyst-card",
      version: "v1",
      source: {
        chatId: "chat-1",
        messageId: "stream-assistant-1",
        skillName: "alarm-analyst",
        contentHash: "hash-1",
      },
      summary: {
        title: "数据库锁异常",
        conclusion: "历史回放兜底匹配",
      },
      rootCause: { reason: "历史回放兜底匹配" },
      impact: { affectedApplications: [], affectedResources: [] },
      topology: { nodes: [], edges: [] },
      recommendations: [],
      evidence: [],
      rawReportMarkdown: "报告正文-历史回放",
    },
  ] as any;

  const merged = mergeAlarmAnalystCards(messages, cards);

  assert.equal(merged[0].alarmAnalystCard.summary.conclusion, "历史回放兜底匹配");
});

test("merges stored cards when report markdown differs only by alarm marker wrapper", () => {
  const messages = [
    {
      id: "agent-3",
      enhancementSourceMessageId: "history-assistant-2",
      processBlocks: [
        {
          kind: "response",
          content:
            "# PORTAL ALARM ANALYST CARD MODE\n\n---\n## 告警分析报告：数据库锁异常\n## 根因判断\n- 锁等待放大",
        },
      ],
    },
  ];
  const cards = [
    {
      type: "alarm-analyst-card",
      version: "v1",
      source: {
        chatId: "chat-1",
        messageId: "stream-assistant-2",
        skillName: "alarm-analyst",
        contentHash: "hash-2",
      },
      summary: {
        title: "数据库锁异常",
        conclusion: "锁等待放大",
      },
      rootCause: { reason: "锁等待放大" },
      impact: { affectedApplications: [], affectedResources: [] },
      topology: { nodes: [], edges: [] },
      recommendations: [],
      evidence: [],
      rawReportMarkdown:
        "## 告警分析报告：数据库锁异常\n## 根因判断\n- 锁等待放大",
    },
  ] as any;

  const merged = mergeAlarmAnalystCards(messages, cards);

  assert.equal(merged[0].alarmAnalystCard.summary.title, "数据库锁异常");
});

test("merges stored cards when raw report has trailing supplement after marker report", () => {
  const messages = [
    {
      id: "agent-4",
      enhancementSourceMessageId: "history-assistant-3",
      processBlocks: [
        {
          kind: "response",
          content:
            "工单已创建成功\n\n---\n\n# PORTAL ALARM ANALYST CARD MODE\n\n---\n\n## 告警分析报告：数据库锁异常\n## 根因判断\n- 锁等待放大\n## 影响范围\n- 受影响应用：CMDB\n## 处置建议\n- P0：终止异常慢 SQL 会话\n## 📊 总结\n- 置信度：86%\n\n---\n\n> 补充说明：这里不应覆盖主报告",
        },
      ],
    },
  ];
  const cards = [
    {
      type: "alarm-analyst-card",
      version: "v1",
      source: {
        chatId: "chat-1",
        messageId: "stream-assistant-3",
        skillName: "alarm-analyst",
        contentHash: "hash-3",
      },
      summary: {
        title: "数据库锁异常",
        conclusion: "锁等待放大",
      },
      rootCause: { reason: "锁等待放大" },
      impact: { affectedApplications: [], affectedResources: [] },
      topology: { nodes: [], edges: [] },
      recommendations: [],
      evidence: [],
      rawReportMarkdown:
        "## 告警分析报告：数据库锁异常\n## 根因判断\n- 锁等待放大\n## 影响范围\n- 受影响应用：CMDB\n## 处置建议\n- P0：终止异常慢 SQL 会话\n## 📊 总结\n- 置信度：86%",
    },
  ] as any;

  const merged = mergeAlarmAnalystCards(messages, cards);

  assert.equal(merged[0].alarmAnalystCard.summary.title, "数据库锁异常");
});

test("only enables alarm analyst cards for fault workorder sessions", () => {
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { meta: { source: "portal-fault-workorder" } },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { meta: { source: "portal-chat" } },
    }),
    false,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { title: "故障处置 · MySQL 告警 · WO-001" },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { title: "告警分析 · 数据库锁异常 · db_mysql_001" },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { sessionId: "portal-fault-alarm-COMMON__1776338881568_2044739586778116096" },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: {
        title:
          "数据库锁异常（db_mysql_001 10.43.150.186）\n资源 ID（CI ID）：3094\n告警时间：2026-04-15 19:20:00",
      },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "fault",
      session: { detail: "工单：WO-001 · 状态：已完成" },
    }),
    true,
  );
  assert.equal(
    shouldEnableAlarmAnalystCards({
      employeeId: "query",
      session: { meta: { source: "portal-fault-workorder" } },
    }),
    false,
  );
});

test("attempts alarm analyst cards by report content even outside tagged sessions", () => {
  assert.equal(
    shouldAttemptAlarmAnalystCardByContent(
      "## 告警分析报告：数据库锁异常\n## 影响范围\n- CMDB\n## 处置建议\n- 终止异常慢 SQL 会话",
    ),
    true,
  );
  assert.equal(
    shouldAttemptAlarmAnalystCardByContent(
      "# PORTAL ALARM ANALYST CARD MODE\n\n---\n## 根因判断\n- 锁等待放大",
    ),
    true,
  );
  assert.equal(
    shouldAttemptAlarmAnalystCardByContent("普通回复，不包含结构化告警分析报告"),
    false,
  );
});
