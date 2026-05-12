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

test("keeps full aggregate inspection report after marker and builds summary from per-instance sections", () => {
  const raw =
    "# PORTAL INSPECTION CARD MODE\n\n---\n\n## PostgreSQL 巡检助手 — 全量巡检报告\n\nCMDB 中共发现 **2 个 PostgreSQL 实例**，已全部完成巡检。以下为两个实例的完整巡检结果。\n\n---\n\n## 一、PG-01（能力网关） — 🔴 异常\n\n### 基本信息\n\n| 字段 | 值 |\n| --- | --- |\n| 巡检对象 | 数据库 |\n| 资源名称 | PG-01（能力网关） |\n| 资源类型 | PostgreSQL |\n| 状态 | 异常 |\n| 指标总数 | 11 |\n| 数据来源 | live |\n| 巡检时间 | 2026-05-12 14:53:35 |\n\n### 指标数据\n\n| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max |\n| --- | --- | --- | --- | --- |\n| 连接数使用率 | pg_conn_usage | 1.20 | 2026-05-12 14:53:35 | 1.20/1.20/1.20 |\n| 空闲连接数 | postgresql_connections_idle | 0 | 2026-05-12 14:53:35 | 0/0/0 |\n\n### PG-01 巡检结论\n\n> 空闲连接数异常。\n\n---\n\n## 二、PG-029（天翼智观） — 🟡 需关注\n\n### 基本信息\n\n| 字段 | 值 |\n| --- | --- |\n| 巡检对象 | 数据库 |\n| 资源名称 | PG-029（天翼智观） |\n| 资源类型 | PostgreSQL |\n| 状态 | 需关注 |\n| 指标总数 | 11 |\n| 数据来源 | live |\n| 巡检时间 | 2026-05-12 14:53:42 |\n\n### 指标数据\n\n| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max |\n| --- | --- | --- | --- | --- |\n| 连接数使用率 | pg_conn_usage | 1.28 | 2026-05-12 14:53:42 | 1.28/1.28/1.28 |\n| 每秒命中磁盘块的次数 | pg_disk_blk_hits_per_sec | 6787.31 | 2026-05-12 14:53:42 | 6787.31/6787.31/6787.31 |\n\n### PG-029 巡检结论\n\n> 磁盘块命中频率很高，需关注磁盘 I/O 压力。\n";

  const unwrapped = unwrapPortalInspectionCardContent(raw);
  const display = buildInspectionDisplayModel(raw);

  assert.match(unwrapped, /## 一、PG-01（能力网关）/u);
  assert.match(unwrapped, /## 二、PG-029（天翼智观）/u);
  assert.ok(display);
  assert.equal(display.title, "PostgreSQL 巡检助手 — 全量巡检报告");
  assert.equal(display.metricGroups.length, 2);
  assert.equal(display.stats[0]?.value, "2026-05-12 14:53:42");
  assert.equal(display.stats[1]?.value, "22");
  assert.equal(display.stats[2]?.value, "PostgreSQL");
  assert.match(display.stats[3]?.value || "", /异常|需关注/u);
});
