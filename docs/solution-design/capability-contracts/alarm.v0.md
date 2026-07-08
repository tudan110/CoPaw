# 告警能力契约 alarm.query（v0）

> 状态:v0（仅冻结「显示映射」层）· 归属:南北向接口标准化 M0 · 配套代码:`src/qwenpaw/extensions/integrations/alarm_contract.py` · 守护:`tests/unit/extensions/integrations/test_alarm_contract_parity.py`

这是「告警」这一能力域的第一份契约。目的是把散落多处、各自维护的告警语义收敛成**单一权威定义**,让上层消费方（对话表格、AI 大屏、Portal API）以及未来任意告警数据源（智观 / 客户系统）对齐到同一套标准，实现「换数据源，上层不改」。

v0 是绞杀式改造的**第一刀**,只做能**零回归**落地的部分:冻结显示映射。字段命名（key）的统一属于 M1,原因见下文「边界」。

---

## 1. 显示映射（v0 已冻结 · 权威源 = `alarm_contract.py`）

告警级别 / 状态 / 类别的编码 → 人类可读中文名。这三张表此前在技能层（`alarm_normalizer.py`）与集成层（`portal_real_alarms.py`）各存一份且逐字节相同;现已收敛到 `alarm_contract`,技能副本由 parity 测试守护至 M1 收编。

**severity → levelName**

| code | 名称 |
|------|------|
| `1` | 紧急 |
| `2` | 严重 |
| `3` | 普通 |
| `4` | 预警 |

**status → statusName**

| code | 名称 |
|------|------|
| `0` | 自动清除 |
| `1` | 活跃 |
| `2` | 同步清除 |
| `3` | 手工清除 |

**class → className**

| code | 名称 |
|------|------|
| `sys_log` | 设备告警 |
| `threshold` | 性能告警 |
| `derivative` | 衍生告警 |

**severity → level（内部英文分级,非显示名）**:`1→critical / 2→urgent / 3→warning`,其余 `info`。喂给 `level` 字段（组件色调），**不是** `levelName`。集成层独有,技能无对应物,故不参与 parity。

---

## 2. 字段对照表（M1 适配层的实现蓝图 · v0 尚未统一）

同一语义在两套 key 命名空间下的拼写。**技能层用 snake_case（贴近智观原始）,集成层 + 大屏用 camelCase（显示键）。** 这张表是 M1 建「告警行标准 schema + 双向重命名适配层」的直接依据。

| 语义 | 技能层 row key | 集成层 / 大屏 key | 备注 |
|------|---------------|------------------|------|
| 告警唯一ID | `alarmuniqueid` | `id` / `alarmId` | 集成把唯一ID同时写入 id 与 alarmId |
| 告警标题 | `alarmtitle` | `title` | 缺失:技能 `-`,集成 `未命名告警` |
| 级别显示名 | `alarmSeverityName` | `levelName` | 值映射一致（表1） |
| 级别英文分级 | —（无） | `level` | 集成独有,组件色调 |
| 设备名 | `devName` | `deviceName` | 缺失:技能 `-`,集成 `--` |
| 管理IP | `manageIp` | `manageIp` | **三处同名** |
| 网元/CI ID | `neId`（回退 ciId→devId） | `ciId`（回退 neId→devId） | 最终回退目标一致（devId） |
| 资源ID | —（仅回退中） | `resId` | |
| 发生时间 | `eventtime` | `eventTime` | 仅大小写差异 |
| 最近发生 | —（行内无） | `eventLastTime` / `timeLabel` | |
| 专业 | `speciality` | `speciality` | **三处同名** |
| 区域 | `alarmregion` | `region` | |
| 状态显示名 | `alarmStatusName` | `statusName` | 值映射一致（表2） |
| 状态英文 | —（无） | `status`（硬编码 `active`） | |
| 类别显示名 | `alarmClassName`（行内丢弃） | `className` | 值映射一致（表3） |
| 触发次数 | —（无） | `count`（条件存在） | |

**空值哨兵差异**（M1 需保留各自行为,否则回归）:技能统一 `-`;集成为 `--`（设备/IP）/ `""`（时间等）/ `未命名告警`（标题）。
**缺失兜底差异**:severity/status 缺失时技能得字面 `"None"`,集成得 `预警`/`未知`。

---

## 3. 边界:v0 为什么不统一 key

统一行字段 key 看似顺手,但落地前的字段级取证证明它**不能零回归**,故不进第一刀:

1. **两套命名空间**:技能 snake_case vs 集成/大屏 camelCase,强行统一必坏其一。
2. **前端硬编码、无别名兜底**:`portalRealAlarms.ts` / `realAlarms.ts` / `usePortalAlerts.ts` 直接按 key 取值;`id` 改名→告警被去重滤掉,`title/deviceName/manageIp` 改名→告警铃消息变空,`dispatchContent` 改名→点击不触发接管。
3. **技能是跨进程离线子进程**:烧进镜像、import 不到后端包,收编它要连带解决依赖打包。

**结论**:key 统一 = M1,需引入「告警行标准 schema + 双向重命名适配层」,并同步改前端 + 收编技能子进程,分步灰度。本表即其蓝图。

---

## 4. 消费方（改 key 时的完整影响面,供 M1 参考）

- 集成 `_normalize_alarm_row` → `GET /api/portal/real-alarms`、大屏 `fetch_real_alarms`、告警自动接管、`portal_monitoring_overview.query_active_alarm_total`（只读 total）
- 大屏组件 `TableWidget`（列 key 必须 == 行 key）、`AlarmStream`（读 `message/eventTime/title`）
- 前端 `PortalRealAlarmItem` 接口及告警铃 / 接管链路
- 对话侧:技能 `get_alarms.py` 输出**原始 INOE key**,由 LLM 按 `SKILL.md` 渲染;`build_alarm_rows` 生产消费者为 0（仅测试）

---

## 5. 版本

- **v0（当前）**:冻结显示映射三表 + `SEVERITY_TO_LEVEL`;权威源 `alarm_contract.py`;parity 守护技能副本。
- **v1（M1 计划）**:告警行标准 schema（统一 key + extras 透传）+ 双向适配层;收编技能子进程副本;智观重构为第一个 connector,输出对齐本契约。
