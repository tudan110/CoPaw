import assert from "node:assert/strict";
import test from "node:test";

import { buildInspectionDisplayModel } from "./displayModel.ts";
import { unwrapPortalInspectionCardContent } from "../pages/digital-employee/helpers.ts";

test("unwraps inspection report instead of trailing supplement after marker", () => {
  const raw =
    "巡检任务执行完成\n\n---\n\n# PORTAL INSPECTION CARD MODE\n\n---\n\n## 巡检结果\n- 巡检对象：db_mysql_001\n\n## 基本信息\n| 字段 | 值 |\n| --- | --- |\n| 巡检对象 | db_mysql_001 |\n| 资源名称 | db_mysql_001 |\n| 资源类型 | mysql |\n| 状态 | 正常 |\n| 指标总数 | 1 |\n| 数据来源 | live |\n| 巡检时间 | 2026-04-28 16:00:00 |\n\n## 指标数据\n| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max | 数据来源 |\n| --- | --- | --- | --- | --- | --- |\n| 活跃线程数 | threads_running | 12 | 2026-04-28 16:00:00 | 10/11/12 | live |\n\n---\n\n> 补充说明：这里不应覆盖主报告";

  const unwrapped = unwrapPortalInspectionCardContent(raw);

  assert.match(unwrapped, /## 巡检结果/u);
  assert.match(unwrapped, /## 基本信息/u);
  assert.match(unwrapped, /## 指标数据/u);
  assert.doesNotMatch(unwrapped, /^> 补充说明/u);
});

test("builds per-resource metric groups for multi-resource inspection reports", () => {
  const raw =
    "# PORTAL INSPECTION CARD MODE\n\n---\n\n## 巡检结果\n\n天翼智观系统共 2 个 Redis 缓存实例，redis-01 指标数据正常采集，redis-02 指标暂无数据返回。\n\n## 基本信息\n\n| 字段 | 值 |\n| --- | --- |\n| 巡检对象 | 缓存 |\n| 资源名称 | redis-01 / redis-02 |\n| 资源类型 | Redis |\n| 状态 | redis-01 需关注，redis-02 无数据 |\n| 指标总数 | 2 个实例共 36 个指标定义 |\n| 数据来源 | INOE 实时指标 |\n| 巡检时间 | 2026-04-29 |\n\n## 指标数据\n\n### redis-01（CI ID: 3019，IP: 10.43.33.251:6379）— 需关注\n\n| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max |\n| --- | --- | --- | --- | --- |\n| 当前连接数 | redis_connected_clients | 50 | 2026-04-29 14:10 | 50/50/50 |\n| **内存碎片率** | redis_mem_fragmentation_ratio | **3.51** | 2026-04-29 14:10 | **3.51/3.51/3.51** |\n| **阻塞 Key 数** | redis_total_blocking_keys | **2** | 2026-04-29 14:10 | 2/2/2 |\n| 服务状态 | redis_up | 1 | 2026-04-29 14:10 | 1/1/1 |\n\n### redis-02（CI ID: 3020，IP: 10.43.95.171:30079）— 无数据\n\n18 个指标定义已注册，但当前所有指标均无实时数据返回，可能采集器尚未接入或数据延迟。\n";

  const display = buildInspectionDisplayModel(raw);

  assert.ok(display);
  assert.equal(display.metricGroups.length, 2);
  assert.equal(display.metricGroups[0]?.title, "redis-01（CI ID: 3019，IP: 10.43.33.251:6379）— 需关注");
  assert.deepEqual(
    display.metricGroups[0]?.metrics.map((item) => item.label),
    ["内存碎片率", "阻塞 Key 数", "服务状态", "当前连接数"],
  );
  assert.equal(display.metricGroups[1]?.title, "redis-02（CI ID: 3020，IP: 10.43.95.171:30079）— 无数据");
  assert.equal(display.metricGroups[1]?.metrics.length, 0);
  assert.match(display.metricGroups[1]?.summary || "", /无实时数据返回/u);
});
