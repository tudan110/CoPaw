import assert from "node:assert/strict";
import test from "node:test";
import {
  groupByDomain,
  unconfiguredCount,
  unconfiguredConnections,
  type CapabilityConfigItem,
} from "./capabilityCatalog.ts";

function item(
  over: Partial<CapabilityConfigItem> & { id: string },
): CapabilityConfigItem {
  return {
    name: over.id,
    category: "",
    connection: "inoe",
    configured: true,
    settingsTab: "",
    reason: "",
    ...over,
  };
}

test("empty / missing → no groups", () => {
  assert.deepEqual(groupByDomain(undefined), []);
  assert.deepEqual(groupByDomain([]), []);
});

test("groups by category in the fixed domain order", () => {
  const groups = groupByDomain([
    item({ id: "logs-1", category: "logs", connection: "n9e" }),
    item({ id: "wo-1", category: "workorder" }),
    item({ id: "alarm-1", category: "alarm" }),
    item({ id: "cmdb-1", category: "cmdb" }),
  ]);
  assert.deepEqual(
    groups.map((g) => g.key),
    ["alarm", "workorder", "cmdb", "logs"],
  );
  assert.deepEqual(
    groups.map((g) => g.label),
    ["告警", "工单", "CMDB", "日志"],
  );
});

test("multiple capabilities share a domain bucket", () => {
  const groups = groupByDomain([
    item({ id: "alarm-1", category: "alarm" }),
    item({ id: "alarm-top5", category: "alarm" }),
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].items.length, 2);
});

test("unknown domain falls through to 其他 after known ones", () => {
  const groups = groupByDomain([
    item({ id: "custom-1", category: "weather" }),
    item({ id: "alarm-1", category: "alarm" }),
    item({ id: "blank-1", category: "" }),
  ]);
  // known 'alarm' first, then first-seen unknown 'weather', then blank→其他
  assert.equal(groups[0].key, "alarm");
  const labels = groups.map((g) => g.label);
  assert.ok(labels.includes("其他"));
  // weather keeps its raw key as label (no translation available)
  assert.ok(groups.some((g) => g.key === "weather"));
});

test("unconfiguredCount counts only configured===false", () => {
  const items = [
    item({ id: "a", configured: true }),
    item({ id: "b", configured: false }),
    item({ id: "c", configured: false }),
  ];
  assert.equal(unconfiguredCount(items), 2);
  assert.equal(unconfiguredCount(undefined), 0);
});

test("unconfiguredConnections dedupes by connection", () => {
  const items = [
    item({
      id: "a",
      connection: "inoe",
      configured: false,
      settingsTab: "inoe",
    }),
    item({
      id: "b",
      connection: "inoe",
      configured: false,
      settingsTab: "inoe",
    }),
    item({ id: "c", connection: "n9e", configured: false, settingsTab: "n9e" }),
    item({ id: "d", connection: "inoe", configured: true }),
  ];
  const conns = unconfiguredConnections(items);
  assert.equal(conns.length, 2);
  assert.deepEqual(conns.map((c) => c.connection).sort(), ["inoe", "n9e"]);
});
