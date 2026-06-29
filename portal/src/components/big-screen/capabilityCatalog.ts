/**
 * capabilityCatalog — group big-screen data capabilities by functional
 * domain for the workshop "数据源配置" panel.
 *
 * Backend `GET /ai-big-screens/capability-config` returns one item per
 * capability: {id, name, category, connection, configured, settingsTab,
 * reason}. `category` is the functional domain (alarm / workorder / cmdb
 * / logs / inspection / web / …) and `connection` is the backing store
 * whose health `configured`/`reason` describe. These pure helpers sort
 * the flat list into ordered, human-labelled domain groups and count the
 * unconfigured connections, so the panel can show 已配置/未配置 badges and
 * a "去设置→<tab>" hint without any backend coupling. Pure +
 * dependency-free so it is unit-testable with node --test.
 */

export interface CapabilityConfigItem {
  id: string;
  name: string;
  category: string;
  connection: string;
  configured: boolean;
  settingsTab: string;
  reason: string;
}

export interface CapabilityDomainGroup {
  /** stable domain key (the raw `category`) */
  key: string;
  /** Chinese display label */
  label: string;
  items: CapabilityConfigItem[];
}

// Fixed display order + Chinese labels for the known functional domains.
// Anything not listed falls through to the "其他" bucket, in first-seen
// order, so a freshly installed skill's new domain still shows up.
const DOMAIN_ORDER: Array<{ key: string; label: string }> = [
  { key: "alarm", label: "告警" },
  { key: "workorder", label: "工单" },
  { key: "cmdb", label: "CMDB" },
  { key: "logs", label: "日志" },
  { key: "inspection", label: "巡检" },
  { key: "web", label: "公网检索" },
];

const FALLBACK_LABEL = "其他";

function labelFor(key: string): string {
  const known = DOMAIN_ORDER.find((entry) => entry.key === key);
  return known ? known.label : key || FALLBACK_LABEL;
}

/**
 * Group capabilities by functional domain. Known domains come first in
 * the fixed order above; unknown domains follow in first-seen order. A
 * blank `category` is bucketed under "其他". Empty groups are omitted.
 */
export function groupByDomain(
  items: CapabilityConfigItem[] | undefined,
): CapabilityDomainGroup[] {
  if (!Array.isArray(items) || items.length === 0) return [];

  const buckets = new Map<string, CapabilityConfigItem[]>();
  const seenOrder: string[] = [];
  for (const item of items) {
    const key = (item.category || "").trim() || "其他";
    if (!buckets.has(key)) {
      buckets.set(key, []);
      seenOrder.push(key);
    }
    buckets.get(key)!.push(item);
  }

  const orderedKeys: string[] = [];
  for (const entry of DOMAIN_ORDER) {
    if (buckets.has(entry.key)) orderedKeys.push(entry.key);
  }
  for (const key of seenOrder) {
    if (!orderedKeys.includes(key)) orderedKeys.push(key);
  }

  return orderedKeys.map((key) => ({
    key,
    label: labelFor(key),
    items: buckets.get(key) ?? [],
  }));
}

/** How many capabilities have an unconfigured backing connection. */
export function unconfiguredCount(
  items: CapabilityConfigItem[] | undefined,
): number {
  if (!Array.isArray(items)) return 0;
  return items.filter((item) => item.configured === false).length;
}

/**
 * Distinct unconfigured connections, each with the settings tab that
 * fixes it — for a single "N 个连接待配置" summary line. Keyed by
 * connection so two capabilities sharing INOE only surface it once.
 */
export function unconfiguredConnections(
  items: CapabilityConfigItem[] | undefined,
): Array<{ connection: string; settingsTab: string; reason: string }> {
  if (!Array.isArray(items)) return [];
  const seen = new Map<
    string,
    { connection: string; settingsTab: string; reason: string }
  >();
  for (const item of items) {
    if (item.configured !== false) continue;
    if (seen.has(item.connection)) continue;
    seen.set(item.connection, {
      connection: item.connection,
      settingsTab: item.settingsTab || "",
      reason: item.reason || "",
    });
  }
  return [...seen.values()];
}
