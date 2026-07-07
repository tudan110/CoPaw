import assert from "node:assert/strict";
import test from "node:test";
import {
  extractRuntimeErrorText,
  runtimeErrorToFriendly,
  toFriendlyChatError,
} from "./chatErrorMessage.ts";

const GENERIC = "服务暂时遇到点问题，请稍后重试。";

test("hides raw python tracebacks behind a generic friendly line", () => {
  const raw =
    'Traceback (most recent call last):\n  File "x.py", line 3, in <module>\n    boom()\nRuntimeError: boom';
  const out = toFriendlyChatError(raw);
  assert.equal(out, GENERIC);
  assert.doesNotMatch(out, /Traceback|File "|boom/);
});

test("maps model category codes to friendly Chinese", () => {
  assert.match(toFriendlyChatError("failed (MODEL_TIMEOUT)"), /超时/);
  assert.match(toFriendlyChatError("failed (MODEL_QUOTA_EXCEEDED)"), /访问量较大/);
  assert.match(toFriendlyChatError("failed (MODEL_CONTEXT_LENGTH_EXCEEDED)"), /内容过长/);
  assert.match(toFriendlyChatError("failed (UNAUTHORIZED_MODEL_ACCESS)"), /联系管理员/);
  assert.match(
    toFriendlyChatError("Model execution failed (MODEL_EXECUTION_ERROR)"),
    /模型服务暂时不可用/,
  );
});

test("network interruptions get a retry hint", () => {
  assert.match(
    toFriendlyChatError("httpx.RemoteProtocolError: peer closed connection"),
    /连接中断/,
  );
});

test("never leaks internal dump paths / product names", () => {
  const out = toFriendlyChatError("boom (Details: /tmp/qwenpaw_query_error_abc.json)");
  assert.doesNotMatch(out, /\/tmp|qwenpaw|Details/);
});

test("unknown or empty errors fall back to one friendly line", () => {
  assert.equal(toFriendlyChatError("some totally unmapped weirdness"), GENERIC);
  assert.equal(toFriendlyChatError(""), GENERIC);
  assert.equal(toFriendlyChatError(null), GENERIC);
});

test("extractRuntimeErrorText normalizes string / {code,message} / ERROR item", () => {
  assert.equal(extractRuntimeErrorText("hi"), "hi");
  assert.equal(
    extractRuntimeErrorText({ code: "MODEL_TIMEOUT", message: "took too long" }),
    "took too long (MODEL_TIMEOUT)",
  );
  const errItem = {
    code: "ERR",
    message: "",
    content: [{ type: "text", text: "deep detail" }],
  };
  assert.match(extractRuntimeErrorText(errItem), /deep detail \(ERR\)/);
});

test("runtimeErrorToFriendly maps an {code,message} object end to end", () => {
  assert.match(
    runtimeErrorToFriendly({ code: "MODEL_QUOTA_EXCEEDED", message: "429 rate" }),
    /访问量较大/,
  );
});
