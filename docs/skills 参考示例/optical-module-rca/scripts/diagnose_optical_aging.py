#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光模块老化故障根因定位 —— 示例诊断脚本

【这个脚本是干什么的】
这是《城域网核心路由器光模块老化故障根因定位方案》文档里"3. 分析思路
与步骤"章节的代码化实现。文档里给出的是一套"四步法"：

    第一步：告警降噪（过滤掉重复/无关的告警，只留下最关键的那条）
    第二步：拓扑-时序双约束因果链推理（判断问题是不是符合"上游先坏、
            下游后坏"的传播规律，顺便排除是不是光纤本身的问题）
    第三步：指标验证（把光模块的各项参数和"正常范围表"逐一比对）
    第四步：根因判定（综合前面三步的结果，给出结论、置信度和处置建议）

这个脚本把"第二步"和"第三步"变成了可以直接运行的代码，"第一步"假设
已经由人工或 Agent 完成（也就是说，调用这个脚本之前，你应该已经把一堆
零散的告警，压缩成了"某个端口的光模块参数"这样一组具体数字），"第四步"
则是脚本根据前面的判断结果自动拼出来的结论。

【这个脚本不做什么】
- 不连接任何真实设备、不发任何网络请求、不需要任何账号密码

【关于参数从哪来】
真实生产环境里，这 5 项参数应该来自监控系统/网管接口的实时采集。但
这是一份演示 demo，目的是让参赛队伍不用真的接一套监控系统、也不用
让使用者手动报一堆数字，就能看到"四步法"完整跑一遍的效果，所以脚本
自带了一份 mock_data.json（几个典型案例，按端口名称查找），只要给出
--port，脚本就会自动从这份 mock 数据里取参数并给出结论，不需要用户
在对话里逐项输入光功率、电流这些数值。

如果你想把这份 demo 改造成接真实数据源的场景，思路是：把下面
"参数来源"这一段替换成调用你自己的监控接口，其余判断逻辑（第二步/
第三步/第四步）都不用动——这也是这个脚本特意把"取数"和"判断"分开
写的原因。

（脚本仍然保留了 --rx-power 等参数，用于开发调试时手动指定某一项
数值覆盖 mock 数据，但正常使用场景下不需要用户提供这些参数。）

【使用方式】
    # 最常见用法：只给端口名称，参数从 mock_data.json 自动取
    python3 scripts/diagnose_optical_aging.py --port GE0/0/1 --output markdown

    # 调试用法：显式覆盖某一项参数，其余仍取自 mock 数据
    python3 scripts/diagnose_optical_aging.py --port GE0/0/1 --temperature 90 --output markdown
"""

import argparse
import json
import os
import sys

# 因为 thresholds.py 放在同目录下的 utils/ 文件夹里，用 python3 直接
# 运行本脚本时，Python 会自动把本脚本所在目录（也就是 scripts/）加入
# 搜索路径，所以下面这行 import 不需要额外配置什么 PYTHONPATH。
from utils.thresholds import (
    RX_POWER_NORMAL_RANGE,
    RX_POWER_SENSITIVITY_LIMIT,
    TX_POWER_NORMAL_RANGE,
    BIAS_CURRENT_NORMAL_RANGE,
    TEMPERATURE_NORMAL_RANGE,
    TEMPERATURE_WARNING_THRESHOLD,
    CRC_RATE_NORMAL,
    TOPOLOGY_PROPAGATION_DELAY_RANGE_MIN,
    TOPOLOGY_PROPAGATION_DELAY_TOLERANCE_MIN,
    is_out_of_range,
)

# mock_data.json 和本脚本放在同一个目录（scripts/），用 __file__ 拼出
# 绝对路径，这样不管从哪个工作目录调用这个脚本，都能找到这份文件。
MOCK_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data.json")

# 这几个数值字段名，是 mock_data.json 里的 key，也是命令行参数（转成
# 下划线形式）对应的字段名，两边统一用同一套名字，方便下面用一个循环
# 就能把"命令行显式传的值"和"mock 数据里的值"合并起来。
MOCK_METRIC_FIELDS = (
    "rx_power",
    "tx_power",
    "bias_current",
    "temperature",
    "crc_rate",
    "downlink_alert_delay_min",
    "peer_rx_power",
    "affected_users",
)


def load_mock_metrics(port):
    """
    按端口名称从 mock_data.json 里查一组模拟采集数据。

    这是这份 demo 能"不用真实设备也能跑通四步法"的关键：正常情况下
    这些数值应该来自监控系统的实时采集，但演示场景不需要真的接一套
    监控系统，所以内置了几个典型案例（老化案例/正常案例/疑似光纤
    问题案例），查不到对应端口名称时，退回 "_default" 这一条兜底，
    保证脚本任何时候都能跑出完整结论，而不是报错退出。
    """
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        mock_data = json.load(f)
    entry = mock_data.get(port) or mock_data["_default"]
    # "_case" 只是给人看的说明文字，不是真实参数，取值时要去掉它。
    return {key: entry[key] for key in MOCK_METRIC_FIELDS}


def resolve_metrics(args):
    """
    把"命令行显式传入的值"和"mock 数据里的值"合并成最终参与判断的
    那组参数：命令行传了就用命令行的（方便开发调试时手动覆盖某一项
    数值），命令行没传（argparse 里默认值是 None）就用 mock 数据里的。
    """
    mock_metrics = load_mock_metrics(args.port)
    resolved = {}
    for field in MOCK_METRIC_FIELDS:
        cli_value = getattr(args, field)
        resolved[field] = cli_value if cli_value is not None else mock_metrics[field]
    return resolved


# ======================================================================
# 第三步：指标验证
# ======================================================================
# 下面这一组函数，每个都只负责判断"一个参数是否异常"，并且返回一句
# 人能看懂的解释。之所以每个参数单独写一个函数而不是揉在一起判断，
# 是为了让每条判断逻辑都能单独阅读、单独测试，不用把所有 if 都塞进
# 同一大段代码里。


def check_rx_power(rx_power):
    """
    判断接收光功率是否异常。

    文档里的原始判断依据：
    - 正常范围是 -19 ~ -5 dBm
    - 如果低于 -22 dBm（典型接收灵敏度下限），说明信号已经弱到设备
      快"看不清"了，这是光模块老化/光纤衰减最直接的信号
    """
    is_abnormal = is_out_of_range(rx_power, RX_POWER_NORMAL_RANGE)
    below_sensitivity = rx_power < RX_POWER_SENSITIVITY_LIMIT

    if below_sensitivity:
        reason = (
            f"接收光功率 {rx_power} dBm，已低于接收灵敏度下限"
            f"（约 {RX_POWER_SENSITIVITY_LIMIT} dBm），信号强度不足"
        )
    elif is_abnormal:
        reason = (
            f"接收光功率 {rx_power} dBm，超出正常范围"
            f"（{RX_POWER_NORMAL_RANGE[0]} ~ {RX_POWER_NORMAL_RANGE[1]} dBm）"
        )
    else:
        reason = f"接收光功率 {rx_power} dBm，在正常范围内"

    return {
        "metric": "接收光功率",
        "value": rx_power,
        "unit": "dBm",
        "is_abnormal": is_abnormal or below_sensitivity,
        "reason": reason,
    }


def check_tx_power(tx_power):
    """
    判断发送光功率是否异常。

    发送光功率正常、只有接收光功率异常，说明问题出在"接收方向"，
    这正是文档故障案例里的典型模式；如果发送光功率也异常，说明
    本端光模块的发射器件可能也出了问题，不只是简单的接收端老化。
    """
    is_abnormal = is_out_of_range(tx_power, TX_POWER_NORMAL_RANGE)
    reason = (
        f"发送光功率 {tx_power} dBm，"
        + ("超出正常范围" if is_abnormal else "在正常范围内")
        + f"（{TX_POWER_NORMAL_RANGE[0]} ~ {TX_POWER_NORMAL_RANGE[1]} dBm）"
    )
    return {
        "metric": "发送光功率",
        "value": tx_power,
        "unit": "dBm",
        "is_abnormal": is_abnormal,
        "reason": reason,
    }


def check_bias_current(bias_current):
    """
    判断偏置电流是否异常。

    激光器老化后发光效率下降，驱动电路会不断加大偏置电流去维持同样
    的发送光功率，所以偏置电流持续偏高，是光模块老化最典型的早期
    信号之一 —— 这一项和接收光功率异常同时出现时，老化的可能性会
    大大增加。
    """
    is_abnormal = is_out_of_range(bias_current, BIAS_CURRENT_NORMAL_RANGE)
    reason = (
        f"偏置电流 {bias_current} mA，"
        + ("偏高，表明激光器可能已经老化" if is_abnormal else "在正常范围内")
        + f"（正常范围 {BIAS_CURRENT_NORMAL_RANGE[0]} ~ {BIAS_CURRENT_NORMAL_RANGE[1]} mA）"
    )
    return {
        "metric": "偏置电流",
        "value": bias_current,
        "unit": "mA",
        "is_abnormal": is_abnormal,
        "reason": reason,
    }


def check_temperature(temperature):
    """
    判断光模块温度是否异常。

    温度超过 70°C 会加速器件老化；文档额外建议超过 65°C 就应该提前
    预警，给运维留出提前介入的时间，所以这里除了"是否异常"，还会
    单独标注"是否已经进入预警区间"。
    """
    is_abnormal = is_out_of_range(temperature, TEMPERATURE_NORMAL_RANGE)
    is_warning = temperature >= TEMPERATURE_WARNING_THRESHOLD

    if is_abnormal:
        reason = f"温度 {temperature}°C，超温（正常上限 {TEMPERATURE_NORMAL_RANGE[1]}°C），会加速老化"
    elif is_warning:
        reason = f"温度 {temperature}°C，已进入预警区间（≥{TEMPERATURE_WARNING_THRESHOLD}°C），建议提前关注"
    else:
        reason = f"温度 {temperature}°C，在正常范围内"

    return {
        "metric": "温度",
        "value": temperature,
        "unit": "°C",
        "is_abnormal": is_abnormal,
        "is_warning": is_warning,
        "reason": reason,
    }


def check_crc_rate(crc_rate):
    """
    判断 CRC 错误计数增长速率是否异常。

    正常情况下应该是 0；只要持续增长（大于 0），就说明链路上确实
    存在误码，是"用户侧丢包/卡顿"这些现象最直接的技术证据。
    """
    is_abnormal = crc_rate > CRC_RATE_NORMAL
    reason = (
        f"CRC 错误计数增长速率约 {crc_rate} 个/秒，"
        + ("持续增长，说明链路误码严重" if is_abnormal else "无增长，正常")
    )
    return {
        "metric": "CRC错误计数",
        "value": crc_rate,
        "unit": "个/秒",
        "is_abnormal": is_abnormal,
        "reason": reason,
    }


# ======================================================================
# 第二步：拓扑-时序双约束因果链推理（简化版）
# ======================================================================


def check_topology_timing(downlink_alert_delay_min, peer_rx_power):
    """
    做两件事：

    1）时序校验：核心路由器在拓扑上处于"上游"，下挂的 BRAS/OLT 等
       属于"下游"。如果真的是这个端口的光模块出问题，下游设备的
       告警时间应该"晚于"该端口告警，且延迟大致落在文档给出的经验
       范围（约 1~2 分钟）附近；如果延迟长达数十分钟甚至下游先报警，
       说明因果关系存疑，需要人工复核，不能直接套用这套自动结论。

    2）对端校验：如果对端设备的接收光功率也异常，更可能是光纤本身
       衰减过大，而不是本端光模块老化——这种情况不能只换本端模块，
       要连光纤和对端一起排查。

    这两个参数都是可选的：如果调用方暂时没有这些数据，脚本会照常
    执行，只是不会给出这部分的判断结论。
    """
    result = {
        "timing_consistent": None,
        "timing_note": "未提供下游告警延迟数据，跳过时序校验",
        "peer_suspect_fiber": None,
        "peer_note": "未提供对端接收光功率数据，跳过对端校验",
    }

    if downlink_alert_delay_min is not None:
        low, high = TOPOLOGY_PROPAGATION_DELAY_RANGE_MIN
        if downlink_alert_delay_min < 0:
            result["timing_consistent"] = False
            result["timing_note"] = (
                f"下游告警比该端口告警还早 {abs(downlink_alert_delay_min)} 分钟，"
                "不符合“上游先坏、下游后坏”的传播规律，因果关系存疑，建议人工复核"
            )
        elif downlink_alert_delay_min > TOPOLOGY_PROPAGATION_DELAY_TOLERANCE_MIN:
            result["timing_consistent"] = False
            result["timing_note"] = (
                f"下游告警延迟 {downlink_alert_delay_min} 分钟，远超经验范围"
                f"（{low}~{high} 分钟），因果关系存疑，建议人工复核"
            )
        else:
            result["timing_consistent"] = True
            result["timing_note"] = (
                f"下游告警延迟 {downlink_alert_delay_min} 分钟，"
                f"符合“上游先坏、下游后坏”的经验范围（{low}~{high} 分钟）"
            )

    if peer_rx_power is not None:
        peer_abnormal = is_out_of_range(peer_rx_power, RX_POWER_NORMAL_RANGE)
        result["peer_suspect_fiber"] = peer_abnormal
        if peer_abnormal:
            result["peer_note"] = (
                f"对端接收光功率 {peer_rx_power} dBm 也异常，"
                "更可能是光纤本身衰减过大，需要连光纤和对端一起排查，"
                "不能只换本端光模块"
            )
        else:
            result["peer_note"] = (
                f"对端接收光功率 {peer_rx_power} dBm 正常，"
                "问题更可能集中在本端光模块，而不是光纤"
            )

    return result


# ======================================================================
# 第四步：根因判定
# ======================================================================


def determine_root_cause(port, metric_checks, topology_result):
    """
    汇总前面所有判断，给出根因结论、置信度和处置建议的"分级"。

    这里的置信度算法很朴素：每一项异常指标算一份证据，证据越多，
    说明"是光模块老化"的把握就越大。这不是严格的概率模型，只是把
    文档里"综合判断、给出置信度"这个思路，用一种最容易理解的方式
    实现出来，方便演示——你完全可以把这里换成自己更严谨的打分规则。
    """
    abnormal_metrics = [c for c in metric_checks if c["is_abnormal"]]
    abnormal_count = len(abnormal_metrics)
    total_count = len(metric_checks)

    # 如果对端/光纤也有问题，这份"光模块老化"结论的可信度要打折扣，
    # 因为问题很可能不只在本端光模块上。
    peer_suspect_fiber = topology_result.get("peer_suspect_fiber")

    if peer_suspect_fiber is True:
        confidence_percent = 50
        conclusion = (
            f"端口 {port} 存在异常，但对端设备接收光功率也异常，"
            "根因可能是光纤衰减，而不仅仅是本端光模块老化，"
            "建议先排查光纤和对端设备，再判断是否需要更换本端光模块"
        )
        severity = "待确认"
    elif abnormal_count == 0:
        confidence_percent = 0
        conclusion = f"端口 {port} 各项参数均在正常范围内，未发现光模块老化迹象"
        severity = "正常"
    else:
        # 异常指标越多，置信度越高；这里只是按比例简单换算成百分比，
        # 再加一点"保底基础分"，让哪怕只有 1 项异常也能有个基础判断。
        confidence_percent = min(95, 40 + int(60 * abnormal_count / total_count))
        abnormal_names = "、".join(c["metric"] for c in abnormal_metrics)
        conclusion = (
            f"端口 {port} 的光模块存在老化迹象，异常项包括：{abnormal_names}，"
            "综合判断为光模块性能劣化导致的误码率上升"
        )
        severity = "严重" if abnormal_count >= 3 else "一般"

    return {
        "port": port,
        "abnormal_count": abnormal_count,
        "total_count": total_count,
        "confidence_percent": confidence_percent,
        "severity": severity,
        "conclusion": conclusion,
    }


# ======================================================================
# 处置建议：直接照抄文档"4. 处置预案与建议方案"章节的思路，
# 按根因判定的严重程度，给出"紧急止血 / 根因修复 / 预防措施"三档建议。
# 完整背景说明见 references/remediation-playbook.md，这里只挑最关键的
# 几条动作，方便直接展示给用户。
# ======================================================================


def build_remediation_suggestions(root_cause):
    if root_cause["severity"] == "正常":
        return ["无需处置，建议维持日常巡检节奏"]

    suggestions = []

    if root_cause["severity"] in ("一般", "严重", "待确认"):
        suggestions.append("紧急止血：若有备用链路，先将该端口流量切换至备用链路")

    if root_cause["severity"] == "严重":
        suggestions.append("紧急止血：必要时可临时降低端口速率，降低误码率、保住业务连续性")
        suggestions.append("根因修复：准备同型号光模块，在业务低谷期更换")

    if root_cause["severity"] == "待确认":
        suggestions.append("根因修复：先排查光纤连接与对端光模块，确认问题范围后再决定是否更换本端光模块")

    suggestions.append("预防措施：建立该光模块的参数基线，定期采集偏置电流、温度，提前预测剩余寿命")

    return suggestions


# ======================================================================
# 输出格式化
# ======================================================================


def build_result(port, metric_checks, topology_result, root_cause, affected_users):
    """把前面几步的结果，拼成一份完整的诊断结果字典。"""
    return {
        "port": port,
        "affected_users": affected_users,
        "metrics": metric_checks,
        "topology": topology_result,
        "root_cause": root_cause,
        "remediation_suggestions": build_remediation_suggestions(root_cause),
    }


def render_markdown(result):
    """
    按文档"故障报告模板"章节的字段顺序，拼出一份适合直接发给用户看的
    Markdown 报告。
    """
    root_cause = result["root_cause"]
    lines = []

    lines.append(f"## 光模块老化诊断报告 —— 端口 {result['port']}")
    lines.append("")
    lines.append(f"**根因结论**：{root_cause['conclusion']}")
    lines.append(f"**置信度**：{root_cause['confidence_percent']}%")
    lines.append(f"**严重程度**：{root_cause['severity']}")
    if result["affected_users"] is not None:
        lines.append(f"**受影响用户数**：约 {result['affected_users']} 人")
    lines.append("")

    lines.append("### 指标验证明细")
    lines.append("")
    lines.append("| 指标 | 数值 | 是否异常 | 说明 |")
    lines.append("|------|------|----------|------|")
    for m in result["metrics"]:
        flag = "⚠️ 异常" if m["is_abnormal"] else "正常"
        lines.append(f"| {m['metric']} | {m['value']} {m['unit']} | {flag} | {m['reason']} |")
    lines.append("")

    topology = result["topology"]
    lines.append("### 拓扑-时序校验")
    lines.append("")
    lines.append(f"- {topology['timing_note']}")
    lines.append(f"- {topology['peer_note']}")
    lines.append("")

    lines.append("### 处置建议")
    lines.append("")
    for suggestion in result["remediation_suggestions"]:
        lines.append(f"- {suggestion}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="根据光模块参数，按四步法给出光模块老化根因诊断（示例脚本，参数默认取自 mock_data.json，不连接真实设备）",
        epilog=(
            "示例：\n"
            "  # 最常见用法：只给端口名称，参数从 mock_data.json 自动取\n"
            "  python3 scripts/diagnose_optical_aging.py --port GE0/0/1 --output markdown\n"
            "  # 调试用法：显式覆盖某一项参数，其余仍取自 mock 数据\n"
            "  python3 scripts/diagnose_optical_aging.py --port GE0/0/1 --temperature 90 --output markdown"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--port", required=True, help="出问题的端口名称，例如 GE0/0/1（用于从 mock_data.json 查找对应参数）")

    # 下面这几项都不再是必填参数：默认从 mock_data.json 按 --port 自动
    # 取值，只有在开发调试、需要临时覆盖某一项数值时才需要显式传入。
    parser.add_argument("--rx-power", type=float, default=None, help="接收光功率，单位 dBm（不传则取自 mock 数据）")
    parser.add_argument("--tx-power", type=float, default=None, help="发送光功率，单位 dBm（不传则取自 mock 数据）")
    parser.add_argument("--bias-current", type=float, default=None, help="偏置电流，单位 mA（不传则取自 mock 数据）")
    parser.add_argument("--temperature", type=float, default=None, help="光模块温度，单位 °C（不传则取自 mock 数据）")
    parser.add_argument("--crc-rate", type=float, default=None, help="CRC 错误计数增长速率，单位 个/秒（不传则取自 mock 数据）")
    parser.add_argument(
        "--downlink-alert-delay-min",
        type=float,
        default=None,
        help="下游设备告警比该端口告警晚多少分钟（不传则取自 mock 数据）",
    )
    parser.add_argument(
        "--peer-rx-power",
        type=float,
        default=None,
        help="对端设备的接收光功率，单位 dBm（不传则取自 mock 数据）",
    )
    parser.add_argument("--affected-users", type=int, default=None, help="受影响用户数（不传则取自 mock 数据）")
    parser.add_argument("--output", choices=["json", "markdown"], default="markdown", help="输出格式，默认 markdown")

    args = parser.parse_args()

    # 把命令行显式传入的值和 mock_data.json 里的值合并成最终参数
    metrics = resolve_metrics(args)

    # 第三步：逐项做指标验证
    metric_checks = [
        check_rx_power(metrics["rx_power"]),
        check_tx_power(metrics["tx_power"]),
        check_bias_current(metrics["bias_current"]),
        check_temperature(metrics["temperature"]),
        check_crc_rate(metrics["crc_rate"]),
    ]

    # 第二步：拓扑-时序双约束因果链推理
    topology_result = check_topology_timing(
        metrics["downlink_alert_delay_min"], metrics["peer_rx_power"]
    )

    # 第四步：根因判定
    root_cause = determine_root_cause(args.port, metric_checks, topology_result)

    result = build_result(args.port, metric_checks, topology_result, root_cause, metrics["affected_users"])

    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(result))

    # 约定：诊断出异常时退出码为 1，一切正常时退出码为 0，方便被其他
    # 脚本或 Agent 通过退出码快速判断"要不要进一步处理"。
    sys.exit(0 if root_cause["severity"] in ("正常",) else 1)


if __name__ == "__main__":
    main()
