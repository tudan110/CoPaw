import assert from "node:assert/strict";
import test from "node:test";

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
