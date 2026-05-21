# IPRAN/IP 专业告警诊断流程参考

本文档来源于《IPRAN/IP专业告警诊断流程编排图 v1.4》，用于指导 AI 在遇到网络设备类（IP 专业）告警时的诊断分析。

> **使用场景**：当告警涉及 BRAS 设备、路由器、链路、光模块、板卡、风扇、电源、端口等网络基础设施时，参考本文档确定诊断步骤和 API 调用顺序。

---

## 通用诊断编排模式

所有 IP 专业告警均遵循统一的阶段化流程：

```
故障工单 → 故障分类 → 信息获取 → 故障确认 → 指标采集 → 根因分析 → 修复方案 → 故障处置 → 业务复核
```

---

## 可用诊断 API 清单

| API 标识 | 中文名称 | 用途 |
|---------|---------|------|
| RES_IP_PING_ADD_API | 登录设备 Ping | 设备连通性确认 |
| RES_IP_DEVICE_IFTXPOWER_QUERY_API | 设备端口发送光功率查询 | 检测本端光模块发送功率是否正常 |
| RES_IP_DEVICE_IFRXPOWER_QUERY_API | 设备端口接收光功率查询 | 检测接收光功率是否衰减 |
| RES_IP_DEVICE_IFINCRC_QUERY_API | 设备端口 CRC 误码数查询 | 判断传输链路质量 |
| RES_IP_LinkFLUX_GET_API | 设备链路带宽利用率查询 | 判断链路是否拥塞 |
| RES_IP_ROUTER_IGP_ISISNEIGHBOR_QUERY_API | 路由器 IGP ISIS 邻居查询 | 检查路由协议邻居状态 |
| RES_IP_BGP_PEERSTATUS_QUERY_API | 设备 BGP 邻居状态查询 | 检查 BGP 会话是否正常 |
| RES_IP_ROUTER_PORTSNMP_QUERY_API | 设备端口状态查询 | 确认端口 Up/Down 状态 |
| RES_IP_DEVICE_CARDSTATUS_QUERY_API | 设备板卡状态查询 | 检查单板运行状态 |
| RES_IP_DEVICE_FANSTATUS_QUERY_API | 设备风扇状态查询 | 检查风扇是否异常 |
| RES_IP_DEVICE_POWERSTATUS_QUERY_API | 设备电源状态查询 | 检查电源模块状态 |
| RES_IP_DEVICE_VOLTAGE_QUERY_API | 设备电压查询 | 检测供电电压是否正常 |
| RES_IP_DEVICE_TEMPERATURE_QUERY_API | 设备温度查询 | 检测设备温度是否过高 |
| RES_IP_光模块匹配_查询_API | 光模块匹配查询 | 本端与对端光模块参数比对 |

---

## 告警场景诊断流程

### 1. BRAS 设备 NodeDown

**触发条件**：设备不可达、SNMP 超时、设备宕机告警

**诊断步骤**：

1. **Ping 连通性确认** → 调用 `RES_IP_PING_ADD_API`
   - 如果 Ping 通：设备在线，可能是 SNMP 采集问题
   - 如果 Ping 不通：继续下一步
2. **端口状态查询** → 调用 `RES_IP_ROUTER_PORTSNMP_QUERY_API`
   - 确认上联端口是否 Down
3. **光功率检测** → 调用 `RES_IP_DEVICE_IFTXPOWER_QUERY_API` + `RES_IP_DEVICE_IFRXPOWER_QUERY_API`
   - 发送/接收光功率是否在正常范围
4. **CRC 误码检测** → 调用 `RES_IP_DEVICE_IFINCRC_QUERY_API`
   - 误码数是否异常增长
5. **链路带宽查询** → 调用 `RES_IP_LinkFLUX_GET_API`
   - 带宽利用率是否打满
6. **路由协议检查** → 调用 `RES_IP_ROUTER_IGP_ISISNEIGHBOR_QUERY_API` + `RES_IP_BGP_PEERSTATUS_QUERY_API`
   - ISIS/BGP 邻居是否 Down

**根因判断规则**：
- Ping 不通 + 所有端口 Down → 设备硬件故障或电源故障
- Ping 不通 + 上联端口 Down + 光功率异常 → 光纤/光模块故障
- Ping 通 + SNMP 超时 → 设备 CPU 过高或管理面异常
- ISIS/BGP 邻居 Down → 路由协议中断，检查链路层

---

### 2. BRAS-CR 链路中继质差

**触发条件**：链路误码率超标、丢包率升高、时延异常

**诊断步骤**：

1. **光功率检测** → 调用 TxPower + RxPower 查询 API
   - 对比发送/接收功率差值
2. **CRC 误码检测** → 调用 `RES_IP_DEVICE_IFINCRC_QUERY_API`
   - CRC 误码是否持续增长
3. **链路带宽查询** → 调用 `RES_IP_LinkFLUX_GET_API`
   - 是否因带宽拥塞引发丢包
4. **Ping 连通性** → 调用 `RES_IP_PING_ADD_API`
   - 确认丢包率和时延
5. **端口状态查询** → 调用 `RES_IP_ROUTER_PORTSNMP_QUERY_API`
   - 端口是否有错误计数器增长

**根因判断规则**：
- 接收光功率低 + CRC 增长 → 光纤衰减或光模块老化
- 发送光功率正常 + 接收异常 → 对端光模块或中间光纤问题
- CRC 增长 + 带宽未满 → 物理层质量问题（光纤弯折、接头脏污）
- 带宽利用率 > 80% + 丢包 → 拥塞导致的质差，需扩容或调整 QoS

---

### 3. 板卡异常

**触发条件**：板卡状态异常告警、板卡重启、板卡不在位

**诊断步骤**：

1. **板卡状态查询** → 调用 `RES_IP_DEVICE_CARDSTATUS_QUERY_API`
   - 确认板卡类型（主控板/业务板/电源板）
   - 确认板卡运行状态（Normal/Abnormal/Absent）
   - 确认板卡内存利用率
   - 确认板卡用户利用率（业务板）

**根因判断规则**：
- 板卡状态 Absent → 板卡脱落或未插紧
- 板卡状态 Abnormal + 内存高 → 板卡资源耗尽，可能需重启或更换
- 主控板异常 → 影响整机管理面，优先级最高
- 业务板异常 → 影响该板下所有端口业务

---

### 4. 风扇异常

**触发条件**：风扇转速告警、风扇停转、温度升高

**诊断步骤**：

1. **风扇状态查询** → 调用 `RES_IP_DEVICE_FANSTATUS_QUERY_API`
   - 确认风扇是否异常（停转/降速）
   - 确认风扇转速是否低于阈值

**根因判断规则**：
- 单风扇停转 + 温度正常 → 风扇硬件故障，待换但不紧急
- 多风扇停转 + 温度上升 → 紧急，设备面临过温保护关机风险
- 风扇降速 → 可能是灰尘堵塞或轴承磨损

**修复建议**：
- 更换故障风扇模块
- 清洁设备进风口
- 如温度持续升高，评估是否需要临时降低设备负载

---

### 5. 电源异常

**触发条件**：电源模块故障、电压异常、供电中断

**诊断步骤**：

1. **电源状态查询** → 调用 `RES_IP_DEVICE_POWERSTATUS_QUERY_API`
   - 确认电源模块是否正常工作
2. **电压查询** → 调用 `RES_IP_DEVICE_VOLTAGE_QUERY_API`
   - 确认各路电压是否在正常范围
3. **温度查询** → 调用 `RES_IP_DEVICE_TEMPERATURE_QUERY_API`
   - 电源过温可能导致降额或保护

**根因判断规则**：
- 单电源故障 + 设备双电源冗余 → 告警但业务不中断，需尽快更换
- 单电源故障 + 设备单电源 → 高风险，设备面临掉电风险
- 电压偏低 → 可能是市电不稳或 UPS 异常
- 温度过高 + 电源降额 → 环境散热不足

---

### 6. LinkDown

**触发条件**：端口 Down、链路中断、物理层故障

**诊断步骤**：

1. **端口状态查询** → 调用 `RES_IP_ROUTER_PORTSNMP_QUERY_API`
   - 确认端口 Admin Status 和 Oper Status
2. **光功率检测** → 调用 TxPower + RxPower 查询 API
   - 检查本端和对端光功率
3. **CRC 误码检测** → 调用 `RES_IP_DEVICE_IFINCRC_QUERY_API`
   - 链路 Down 前是否有误码激增
4. **光模块匹配查询** → 调用 `RES_IP_光模块匹配_查询_API`
   - 确认两端光模块参数是否匹配
5. **链路带宽查询** → 调用 `RES_IP_LinkFLUX_GET_API`
   - 链路 Down 前是否有拥塞

**根因判断规则**：
- Admin Down → 人为关闭端口，确认变更记录
- Oper Down + 光功率正常 → 对端设备/端口问题
- Oper Down + 接收光功率无信号 → 光纤中断或对端光模块故障
- Oper Down + CRC 激增后 Down → 物理层劣化导致协议 Down
- 光模块不匹配 → 两端模块规格不一致（速率/波长/距离）

---

### 7. 端口频繁翻转

**触发条件**：端口在短时间内多次 Up/Down 切换

**诊断步骤**：

1. **光功率检测** → 调用 TxPower + RxPower 查询 API
   - 光功率是否在临界值附近波动
2. **CRC 误码检测** → 调用 `RES_IP_DEVICE_IFINCRC_QUERY_API`
   - 是否伴随误码
3. **光模块匹配查询** → 调用 `RES_IP_光模块匹配_查询_API`
   - 两端光模块参数比对（调用 2 次 TxPower 查询，分别查本端和对端）
4. **端口状态查询** → 调用 `RES_IP_ROUTER_PORTSNMP_QUERY_API`
   - 翻转次数、最近状态变化时间
5. **链路带宽查询** → 调用 `RES_IP_LinkFLUX_GET_API`
   - 翻转是否与流量突增相关

**根因判断规则**：
- 光功率临界值波动 → 光模块老化或光纤接头松动
- CRC 伴随翻转 → 物理层信号质量差
- 光模块不匹配 → 协商不稳定导致反复翻转
- 翻转与流量突增同步 → 可能是带宽过载触发保护
- 无明显物理层异常 → 检查对端设备配置变更或自协商问题

---

## 指标异常阈值参考

| 指标 | 正常范围 | 告警条件 |
|------|---------|---------|
| 接收光功率 | > -25 dBm（短距）/ > -30 dBm（长距） | 低于告警阈值 |
| 发送光功率 | -3 ~ +2 dBm（典型） | 超出正常范围 |
| CRC 误码数 | 0 或不增长 | 持续增长 > 10/min |
| 链路带宽利用率 | < 80% | > 80% 拥塞风险 |
| 设备温度 | < 65°C | > 70°C 告警，> 80°C 危险 |
| 风扇转速 | 制造商标称范围 | 低于正常转速 50% |

---

## 与 alarm-analyst 主流程的映射

| alarm-analyst 阶段 | IP 专业对应动作 |
|-------------------|----------------|
| 第 1 阶段：接收告警 | 提取设备名、端口、告警类型（NodeDown/LinkDown/板卡/风扇/电源/翻转/质差） |
| 第 3 阶段：CMDB 查询 | 确认设备 ciType（router/switch/bras）、所属网络层级、上下联设备 |
| 第 4 阶段：指标采集 | 按上述场景调用对应 API 组合 |
| 第 5 阶段：故障类型识别 | 光纤问题 / 光模块问题 / 设备硬件 / 链路拥塞 / 协议异常 / 环境问题 |
| 第 6 阶段：影响范围 | 受影响的下挂用户数、受影响的业务链路数、是否有冗余路径 |
| 处置建议 | 更换光模块、清理光纤接头、重启板卡、更换风扇/电源、调整 COST 值切换流量 |
